"""Telegram Bot and Keep-Alive Server for Chamo Charly Producción.

Designed for 24/7 deployment on Render / Cloud Free VPS with UptimeRobot pinging.
Fully driven by inline keyboard buttons — no slash commands needed after login.
Reads and saves official predictions directly from the Chamo Charly database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from chamo_charly.catalog import ANIMALS, code_for_animal
from chamo_charly.database import (
    init_db,
    insert_draw,
    recent_draws,
    latest_prediction,
    prediction_for_target,
    save_prediction,
    verify_prediction,
)
from chamo_charly.predictor import coverage_prediction, next_target
from chamo_charly.verificador_diario import run_daily_verification

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DATABASE_PATH = Path("data/chamo_charly.db")
BOT_PASSWORD  = os.environ.get("BOT_PASSWORD", "Charly2026")
BOT_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ── State ─────────────────────────────────────────────────────────────────────
authenticated_chats: set[int] = set()

# ── Flask Keep-Alive ──────────────────────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
@flask_app.route("/health")
def healthcheck():
    return jsonify({"status": "ok", "app": "Chamo Charly Bot",
                    "time": datetime.now().isoformat()}), 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Iniciando servidor Keep-Alive HTTP en puerto {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ── Keyboards ─────────────────────────────────────────────────────────────────
def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Menú principal con botones grandes."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Ver Predicción", callback_data="prediccion")],
        [InlineKeyboardButton("✅ Ingresar Resultado", callback_data="resultado")],
        [InlineKeyboardButton("📊 Verificar Sistema", callback_data="verificar"),
         InlineKeyboardButton("🔒 Cerrar Sesión", callback_data="logout")],
    ])

def back_keyboard() -> InlineKeyboardMarkup:
    """Botón para volver al menú."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver al Menú", callback_data="menu")]
    ])

def resultado_keyboard(top_animals: list[dict]) -> InlineKeyboardMarkup:
    """Grid de los top animales predichos como botones de resultado."""
    buttons = []
    row = []
    for item in top_animals[:20]:
        label = f"{item['codigo']} {item['animal']}"
        row.append(InlineKeyboardButton(label, callback_data=f"res_{item['codigo']}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


# ── Helpers & Active Prediction Manager ───────────────────────────────────────
def is_auth(chat_id: int) -> bool:
    return chat_id in authenticated_chats

def rank_label(rank: int) -> str:
    if rank <= 5:
        return f"🏆 *¡ACIERTO DIRECTO EN TOP 5!* (Puesto #{rank})"
    elif rank <= 10:
        return f"🎯 *¡ACIERTO EN TOP 10!* (Puesto #{rank})"
    elif rank <= 20:
        return f"🛡️ *¡CAPTURADO EN MALLA TOP 20!* (Puesto #{rank})"
    else:
        return f"❌ *Fuera de Malla Top 20* (Puesto #{rank} de 36)"

def get_active_prediction() -> dict:
    """Obtiene la predicción oficial guardada en la BD o la genera con coverage_prediction y la guarda."""
    target_date, target_time = next_target(DATABASE_PATH)
    latest = latest_prediction(DATABASE_PATH)
    
    if latest and latest.get("objetivo_fecha") == target_date and latest.get("objetivo_hora") == target_time:
        ranking = json.loads(latest.get("ranking_completo") or latest.get("probabilidades_json") or "[]")
        top10 = json.loads(latest.get("top10_json") or "[]")
        
        escalation = []
        for item in ranking[:3]:
            delta = item.get("probabilidad", 0.0) - (1.0 / len(ANIMALS))
            if delta > 0:
                escalation.append((item["codigo"], delta))

        return {
            "id": latest["id"],
            "target_date": latest["objetivo_fecha"],
            "target_time": latest["objetivo_hora"],
            "observations": latest["observaciones"],
            "model": latest["modelo"],
            "top5": ranking[:5],
            "top10": top10 if top10 else ranking[:10],
            "top11_20": ranking[10:20],
            "ranking": ranking,
            "escalation": escalation,
        }

    # Si no existe en la BD para este objetivo, generar con el motor oficial de Chamo Charly y guardar
    pred = coverage_prediction(DATABASE_PATH)
    pred_id = save_prediction(DATABASE_PATH, pred)
    pred["id"] = pred_id
    return pred


async def send_prediccion(chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                          edit_message=None) -> None:
    """Muestra la predicción oficial proveniente de Chamo Charly Producción."""
    pred = get_active_prediction()
    top5_str = "\n".join([
        f"  {i+1}. *{it['codigo']} - {it['animal']}* ({it['probabilidad']:.2%})"
        for i, it in enumerate(pred['top5'])
    ])
    top6_10_str = "\n".join([
        f"  {i+6}. {it['codigo']} - {it['animal']} ({it['probabilidad']:.2%})"
        for i, it in enumerate(pred['top10'][5:10])
    ])
    top11_20_str = "\n".join([
        f"  {i+11}. {it['codigo']} - {it['animal']} ({it['probabilidad']:.2%})"
        for i, it in enumerate(pred['top11_20'])
    ])
    escalation_str = "\n".join([
        f"  🔥 *{code} - {ANIMALS.get(code, code)}* (+{delta*100:.2f}%)"
        for code, delta in pred.get('escalation', [])
    ])

    text = (
        f"🎯 *PREDICCIÓN BMA DIRICHLET*\n"
        f"📅 *Objetivo:* {pred['target_date']} a las {pred['target_time']}\n"
        f"📊 *Experiencia:* {pred['observations']} sorteos acumulados\n\n"
        f"🏆 *TOP 5 PRINCIPAL*\n{top5_str}\n\n"
        f"🎯 *TOP 6–10*\n{top6_10_str}\n\n"
        f"🛡️ *TOP 11–20 (MALLA DE SEGURIDAD)*\n{top11_20_str}\n\n"
        f"⚡ *EMPUJE BAYESIANO*\n{escalation_str}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ingresar Resultado", callback_data="resultado")],
        [InlineKeyboardButton("🔄 Actualizar Predicción", callback_data="prediccion"),
         InlineKeyboardButton("⬅️ Menú", callback_data="menu")],
    ])

    if edit_message:
        await edit_message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id, text,
                                       parse_mode="Markdown", reply_markup=keyboard)


# ── /start ────────────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if is_auth(chat_id):
        await update.message.reply_text(
            "🤖 *Chamo Charly — Panel Principal*\n\n"
            "Selecciona una opción:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            "🔒 *Bot Protegido — Chamo Charly*\n\n"
            "Para acceder escribe:\n"
            "`/login <tu_contraseña>`",
            parse_mode="Markdown",
        )


# ── /login ────────────────────────────────────────────────────────────────────
async def login_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "⚠️ Uso: `/login <contraseña>`", parse_mode="Markdown"
        )
        return

    if context.args[0] == BOT_PASSWORD:
        authenticated_chats.add(chat_id)
        await update.message.reply_text(
            "✅ *¡Acceso Concedido!*\n\n"
            "Bienvenido al panel oficial de Chamo Charly BMA.\n"
            "Selecciona una opción:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            "❌ *Contraseña incorrecta.* Intenta de nuevo con `/login <clave>`.",
            parse_mode="Markdown",
        )


# ── Callbacks ─────────────────────────────────────────────────────────────────
async def menu_callback(query, context):
    await query.edit_message_text(
        "🤖 *Chamo Charly — Panel Principal*\n\nSelecciona una opción:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def prediccion_callback(query, context):
    await query.edit_message_text("⏳ Obteniendo predicción oficial de Chamo Charly...")
    try:
        await send_prediccion(query.message.chat_id, context, edit_message=query.message)
    except Exception as exc:
        logger.error(f"Error predicción: {exc}", exc_info=True)
        await query.edit_message_text(f"❌ Error al consultar predicción: {exc}",
                                      reply_markup=back_keyboard())


async def resultado_callback(query, context):
    """Muestra los 20 animales predichos oficialmente como botones de resultado."""
    await query.edit_message_text("⏳ Cargando animales predichos...")
    try:
        pred = get_active_prediction()
        ranking = pred.get("ranking", pred["top5"] + pred["top10"][5:] + pred.get("top11_20", []))

        await query.edit_message_text(
            f"✅ *¿Cuál fue el animal ganador para {pred['target_date']} {pred['target_time']}?*\n\n"
            "Toca el animal que salió en el sorteo:",
            parse_mode="Markdown",
            reply_markup=resultado_keyboard(ranking[:20]),
        )
    except Exception as exc:
        logger.error(f"Error cargando resultado: {exc}", exc_info=True)
        await query.edit_message_text(f"❌ Error: {exc}", reply_markup=back_keyboard())


async def registrar_resultado_callback(query, context, code: str):
    """Registra el animal ganador, audita la predicción activa y genera/guarda la siguiente."""
    animal = ANIMALS.get(code, code)
    await query.edit_message_text(
        f"⏳ Registrando *{code} - {animal}* en Chamo Charly Producción...",
        parse_mode="Markdown",
    )
    try:
        pred = get_active_prediction()
        ranking = pred.get("ranking", pred["top5"] + pred["top10"][5:] + pred.get("top11_20", []))
        rank = next((idx + 1 for idx, it in enumerate(ranking) if it["codigo"] == code), 37)

        target_date_str = pred["target_date"]
        target_time_str = pred["target_time"]
        dt_obj = datetime.strptime(f"{target_date_str} {target_time_str}", "%Y-%m-%d %H:%M")
        weekday_str = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"][dt_obj.weekday()]

        # 1. Guardar el sorteo en la tabla 'sorteos'
        insert_draw(
            DATABASE_PATH, target_date_str, target_time_str, code, animal,
            weekday_str, fuente="telegram_bot",
            capturado_en=datetime.now().isoformat(), estado="confirmado",
        )

        # 2. Verificar la predicción activa si tiene ID
        if pred.get("id"):
            try:
                verify_prediction(DATABASE_PATH, pred["id"], code, animal)
            except Exception as exc:
                logger.warning(f"Auditoría predicción {pred.get('id')}: {exc}")

        # 3. Generar y GUARDAR la siguiente predicción en la base de datos de producción
        next_pred = coverage_prediction(DATABASE_PATH)
        save_prediction(DATABASE_PATH, next_pred)

        next_top5 = "\n".join([
            f"  {i+1}. *{it['codigo']} - {it['animal']}* ({it['probabilidad']:.2%})"
            for i, it in enumerate(next_pred["top5"])
        ])

        text = (
            f"✅ *RESULTADO REGISTRADO EN PRODUCCIÓN*\n\n"
            f"🐾 *Ganador:* `{code} - {animal}`\n"
            f"{rank_label(rank)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔮 *SIGUIENTE PREDICCIÓN (Chamo Charly)* ({next_pred['target_date']} {next_pred['target_time']})\n\n"
            f"🏆 *TOP 5 PRINCIPAL:*\n{next_top5}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Ver Predicción Completa", callback_data="prediccion")],
            [InlineKeyboardButton("⬅️ Menú Principal", callback_data="menu")],
        ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    except Exception as exc:
        logger.error(f"Error registrando resultado: {exc}", exc_info=True)
        await query.edit_message_text(f"❌ Error: {exc}", reply_markup=back_keyboard())


async def verificar_callback(query, context):
    await query.edit_message_text("⏳ Auditando sistema Chamo Charly...")
    try:
        status = run_daily_verification(DATABASE_PATH)
        top5_str = "\n".join([f"  • {it}" for it in status["top5_principal"]])
        empuje_str = "\n".join([f"  🔥 {it}" for it in status["empuje_bayesiano"]])
        text = (
            f"🏥 *AUDITORÍA DEL SISTEMA*\n\n"
            f"📊 *Sorteos Acumulados:* {status['total_sorteos']}\n"
            f"📌 *Último Sorteo:* {status['ultimo_sorteo']}\n"
            f"🎯 *Próximo Objetivo:* {status['proximo_objetivo']}\n\n"
            f"🏆 *TOP 5:*\n{top5_str}\n\n"
            f"⚡ *EMPUJE BAYESIANO:*\n{empuje_str}\n\n"
            f"💚 *Estado:* {status['salud_sistema']}"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
    except Exception as exc:
        logger.error(f"Error verificando: {exc}", exc_info=True)
        await query.edit_message_text(f"❌ Error: {exc}", reply_markup=back_keyboard())


async def logout_callback(query, context):
    authenticated_chats.discard(query.message.chat_id)
    await query.edit_message_text(
        "🔒 *Sesión cerrada exitosamente.*\n\n"
        "Escribe `/login <contraseña>` para volver a entrar.",
        parse_mode="Markdown",
    )


# ── Router principal ──────────────────────────────────────────────────────────
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if not is_auth(chat_id) and query.data != "logout":
        await query.edit_message_text(
            "🔒 *Sesión expirada.*\n\nEscribe `/login <contraseña>` para volver a entrar.",
            parse_mode="Markdown",
        )
        return

    data = query.data

    if data == "menu":
        await menu_callback(query, context)
    elif data == "prediccion":
        await prediccion_callback(query, context)
    elif data == "resultado":
        await resultado_callback(query, context)
    elif data.startswith("res_"):
        code = data.replace("res_", "")
        await registrar_resultado_callback(query, context, code)
    elif data == "verificar":
        await verificar_callback(query, context)
    elif data == "logout":
        await logout_callback(query, context)


# ── Bot runner ────────────────────────────────────────────────────────────────
async def run_bot():
    logger.info("Iniciando Bot de Telegram Chamo Charly...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("login", login_handler))
    app.add_handler(CallbackQueryHandler(button_router))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot de Telegram activo y escuchando con botones...")

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def main():
    init_db(DATABASE_PATH)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN no configurado.")
        flask_thread.join()
        return

    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
