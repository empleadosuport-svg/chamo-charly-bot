"""Telegram Bot and Keep-Alive Server for Chamo Charly Producción.

Designed for 24/7 deployment on Render / Cloud Free VPS with UptimeRobot pinging.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, date, time
from pathlib import Path
from flask import Flask, jsonify

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from chamo_charly.catalog import ANIMALS, code_for_animal, validate_result
from chamo_charly.database import (
    chronological_draws,
    init_db,
    insert_draw,
    latest_prediction,
    recent_draws,
    save_prediction,
)
from chamo_charly.predictor import bma_prediction
from chamo_charly.verificador_diario import run_daily_verification

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DATABASE_PATH = Path("data/chamo_charly.db")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD", "Charly2026")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# In-memory authentication sessions (Chat IDs)
authenticated_chats: set[int] = set()

# Flask Keep-Alive Server
flask_app = Flask(__name__)


@flask_app.route("/")
@flask_app.route("/health")
def healthcheck():
    return jsonify({"status": "ok", "app": "Chamo Charly Bot", "time": datetime.now().isoformat()}), 200


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Iniciando servidor Keep-Alive HTTP en puerto {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# Telegram Bot Command Handlers
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in authenticated_chats:
        text = (
            "🤖 *Bienvenido a Chamo Charly Producción*\n\n"
            "✅ *Sesión Activa*\n\n"
            "Comandos disponibles:\n"
            "• `/prediccion` — Obtener predicción activa BMA Dirichlet (4 Niveles)\n"
            "• `/resultado <animal_o_codigo>` — Registrar resultado real y auditar acierto\n"
            "• `/verificar` — Auditar la salud del sistema y total de sorteos\n"
            "• `/logout` — Cerrar sesión"
        )
    else:
        text = (
            "🔒 *Bot Protegido — Chamo Charly*\n\n"
            "Para acceder a las predicciones y funciones del sistema, por favor inicia sesión:\n\n"
            "👉 `/login <tu_contraseña>`"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def login_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("⚠️ Uso: `/login <contraseña>`", parse_mode="Markdown")
        return

    provided_password = context.args[0]
    if provided_password == BOT_PASSWORD:
        authenticated_chats.add(chat_id)
        await update.message.reply_text(
            "✅ *Acceso Concedido*\n\n"
            "Bienvenido al panel oficial de Chamo Charly BMA.\n"
            "Usa `/prediccion` para obtener la predicción activa.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ *Contraseña incorrecta.* Intenta de nuevo con `/login <clave>`.", parse_mode="Markdown")


async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    authenticated_chats.discard(chat_id)
    await update.message.reply_text("🔒 *Sesión cerrada exitosamente.*", parse_mode="Markdown")


def is_auth(update: Update) -> bool:
    return update.effective_chat.id in authenticated_chats


async def prediccion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_auth(update):
        await update.message.reply_text("🔒 *Acceso denegado.* Por favor inicia sesión con `/login <clave>`.", parse_mode="Markdown")
        return

    msg = await update.message.reply_text("⏳ Calculando predicción BMA Dirichlet (1 Año de Experiencia)...")
    try:
        pred = bma_prediction(DATABASE_PATH)
        top5_str = "\n".join([f"  {i+1}. *{item['codigo']} - {item['animal']}* ({item['probabilidad']:.2%})" for i, item in enumerate(pred['top5'])])
        top6_10_str = "\n".join([f"  {i+6}. {item['codigo']} - {item['animal']} ({item['probabilidad']:.2%})" for i, item in enumerate(pred['top10'][5:10])])
        top11_20_str = "\n".join([f"  {i+11}. {item['codigo']} - {item['animal']} ({item['probabilidad']:.2%})" for i, item in enumerate(pred['top11_20'])])
        escalation_str = "\n".join([f"  🔥 *{code} - {ANIMALS.get(code, code)}* (+{delta*100:.2f}%)" for code, delta in pred['escalation']])

        response_text = (
            f"🎯 *PREDICCIÓN BMA DIRICHLET*\n"
            f"📅 *Objetivo:* {pred['target_date']} a las {pred['target_time']}\n"
            f"📊 *Experiencia:* {pred['observations']} sorteos acumulados\n\n"
            f"🏆 *TOP 5 PRINCIPAL*\n{top5_str}\n\n"
            f"🎯 *TOP 6–10*\n{top6_10_str}\n\n"
            f"🛡️ *TOP 11–20 (MALLA DE SEGURIDAD)*\n{top11_20_str}\n\n"
            f"⚡ *EMPUJE BAYESIANO (TOP ESCALADA)*\n{escalation_str}"
        )
        await msg.edit_text(response_text, parse_mode="Markdown")
    except Exception as exc:
        logger.error(f"Error generando predicción: {exc}", exc_info=True)
        await msg.edit_text(f"❌ Error al calcular predicción: {exc}")


async def resultado_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_auth(update):
        await update.message.reply_text("🔒 *Acceso denegado.* Por favor inicia sesión con `/login <clave>`.", parse_mode="Markdown")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Uso: `/resultado <codigo_o_animal>` (Ejemplo: `/resultado 34` o `/resultado Venado`)", parse_mode="Markdown")
        return

    raw_input = " ".join(context.args).strip()
    # Resolve code
    code = None
    if raw_input in ANIMALS:
        code = raw_input
        animal = ANIMALS[code]
    else:
        # Check animal name search
        code = code_for_animal(raw_input)
        animal = ANIMALS.get(code, raw_input) if code else raw_input

    if not code:
        await update.message.reply_text(f"❌ No se pudo identificar el animal o código '{raw_input}'.", parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"⏳ Registrando resultado *{code} - {animal}* y auditando acierto...", parse_mode="Markdown")
    try:
        # Determine latest draw slot or current draw target
        latest = recent_draws(DATABASE_PATH, 1)
        if latest:
            last_dt = datetime.strptime(f"{latest[0]['fecha_sorteo']} {latest[0]['hora_sorteo']}", "%Y-%m-%d %H:%M")
            if last_dt.hour >= 19:
                next_dt = (last_dt.replace(hour=8, minute=0) + timedelta(days=1))
            else:
                next_dt = last_dt.replace(minute=0, second=0) + timedelta(hours=1)
        else:
            next_dt = datetime.now().replace(minute=0, second=0)

        draw_date_str = next_dt.strftime("%Y-%m-%d")
        draw_time_str = next_dt.strftime("%H:%M")
        weekday_str = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][next_dt.weekday()]

        # Generate prediction prior to insert for audit
        pred = bma_prediction(DATABASE_PATH)
        
        # Rank of winner
        rank = next((idx + 1 for idx, item in enumerate(pred["ranking"]) if item["codigo"] == code), 38)
        
        if rank <= 5:
            tier_msg = f"🏆 *¡ACIERTO DIRECTO EN TOP 5!* (Puesto #{rank})"
        elif rank <= 10:
            tier_msg = f"🎯 *¡ACIERTO EN TOP 10!* (Puesto #{rank})"
        elif rank <= 20:
            tier_msg = f"🛡️ *¡CAPTURADO EN MALLA TOP 20!* (Puesto #{rank})"
        else:
            tier_msg = f"❌ *Fuera de Malla Top 20* (Puesto #{rank})"

        # Insert draw into DB
        now_iso = datetime.now().isoformat()
        insert_draw(
            DATABASE_PATH,
            draw_date_str,
            draw_time_str,
            code,
            animal,
            weekday_str,
            fuente="telegram_bot",
            capturado_en=now_iso,
            estado="confirmado",
        )

        # Generate next prediction post-insert
        next_pred = bma_prediction(DATABASE_PATH)

        response_text = (
            f"✅ *RESULTADO REGISTRADO EXITOSAMENTE*\n\n"
            f"📌 *Sorteo:* {draw_date_str} {draw_time_str}\n"
            f"🐾 *Ganador:* `{code} - {animal}`\n"
            f"{tier_msg}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔮 *SIGUIENTE PREDICCIÓN ( BMA DIRICHLET )*\n"
            f"📅 *Objetivo:* {next_pred['target_date']} a las {next_pred['target_time']}\n\n"
            f"🏆 *TOP 5 PRINCIPAL:*\n" +
            "\n".join([f"  {i+1}. *{item['codigo']} - {item['animal']}* ({item['probabilidad']:.2%})" for i, item in enumerate(next_pred['top5'])])
        )
        await msg.edit_text(response_text, parse_mode="Markdown")
    except Exception as exc:
        logger.error(f"Error registrando resultado: {exc}", exc_info=True)
        await msg.edit_text(f"❌ Error al registrar resultado: {exc}")


async def verificar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_auth(update):
        await update.message.reply_text("🔒 *Acceso denegado.* Por favor inicia sesión con `/login <clave>`.", parse_mode="Markdown")
        return

    status = run_daily_verification(DATABASE_PATH)
    top5_str = "\n".join([f"  • {item}" for item in status["top5_principal"]])
    empuje_str = "\n".join([f"  🔥 {item}" for item in status["empuje_bayesiano"]])

    text = (
        f"🏥 *AUDITORÍA Y SALUD DEL SISTEMA*\n\n"
        f"📊 *Sorteos Acumulados:* {status['total_sorteos']}\n"
        f"📌 *Último Sorteo:* {status['ultimo_sorteo']}\n"
        f"🎯 *Próximo Objetivo:* {status['proximo_objetivo']}\n\n"
        f"🏆 *TOP 5 PRINCIPAL:*\n{top5_str}\n\n"
        f"⚡ *EMPUJE BAYESIANO:*\n{empuje_str}\n\n"
        f"💚 *Estado:* {status['salud_sistema']}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


def main():
    init_db(DATABASE_PATH)

    # 1. Start Flask HTTP Keep-Alive server in daemon thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 2. Start Telegram Bot Application
    if not BOT_TOKEN:
        logger.warning(
            "TELEGRAM_BOT_TOKEN no configurado. El servidor Keep-Alive HTTP está activo, pero el bot de Telegram requiere TELEGRAM_BOT_TOKEN para conectarse a Telegram."
        )
        # Keep main thread alive for Flask
        flask_thread.join()
        return

    logger.info("Iniciando Bot de Telegram Chamo Charly...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("login", login_handler))
    app.add_handler(CommandHandler("logout", logout_handler))
    app.add_handler(CommandHandler("prediccion", prediccion_handler))
    app.add_handler(CommandHandler("resultado", resultado_handler))
    app.add_handler(CommandHandler("verificar", verificar_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
