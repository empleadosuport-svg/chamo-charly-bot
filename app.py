"""Local Streamlit panel for Chamo Charly."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from chamo_charly.catalog import ANIMALS, code_for_animal, validate_result
from chamo_charly.analytics import (
    exponential_scores,
    frequency_table,
    history_frame,
    hourly_summary,
    markov_transitions,
    runs_test,
    uniformity_test,
)
from chamo_charly.database import (
    count_draws,
    confirm_provisional_draw,
    draw_for_slot,
    frequency_by_animal,
    historical_runs,
    init_db,
    insert_draw,
    latest_prediction,
    pending_predictions,
    prediction_by_id,
    prediction_for_target,
    prediction_history,
    recent_draws,
    save_prediction,
    context_weight_rows,
    verified_position_summary,
    verify_prediction,
)
from chamo_charly.evaluador import run_historical_evaluation, save_historical_evaluation
from chamo_charly.predictor import baseline_prediction, composite_prediction, confidence_label, coverage_prediction

DATABASE_PATH = Path("data/chamo_charly.db")
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

st.set_page_config(page_title="Chamo Charly", page_icon="CC", layout="wide")
init_db(DATABASE_PATH)


def weekday_for(draw_date: date) -> str:
    return WEEKDAYS[draw_date.weekday()]


def resolve_result_from_animal(animal: str | None) -> str | None:
    if not animal:
        return None
    return code_for_animal(animal)


def ensure_latest_result_target() -> tuple[date, time]:
    latest = recent_draws(DATABASE_PATH, 1)
    if latest:
        latest_dt = datetime.strptime(f"{latest[0]['fecha_sorteo']} {latest[0]['hora_sorteo']}", "%Y-%m-%d %H:%M")
        if latest_dt.hour >= 19:
            next_dt = (latest_dt + timedelta(days=1)).replace(hour=8, minute=0)
        else:
            next_dt = latest_dt + timedelta(hours=1)
        return next_dt.date(), next_dt.time().replace(second=0, microsecond=0)
    return date.today(), time(8, 0)


def build_verification_summary(prediction: dict, code: str) -> str:
    if not prediction:
        return "Sin predicción activa."
    top10 = json.loads(prediction["top10_json"])
    metrics = next((entry for entry in top10 if entry["codigo"] == code), None)
    if metrics is None:
        return f"El animal {ANIMALS.get(code, code)} no estuvo en el top 10 de la predicción activa."
    return (
        f"Estuvo en el top 10 con {metrics['probabilidad']:.2%}. "
        f"Hora: {metrics.get('hora', 0):.2%} | día+hora: {metrics.get('dia_hora', 0):.2%} | "
        f"Markov: {metrics.get('markov', 0):.2%} | reciente: {metrics.get('reciente', 0):.2%}."
    )


def save_result(draw_date: date, draw_time: time, code: str, animal: str, source: str = "panel") -> bool:
    error = validate_result(code, animal)
    if error:
        st.error(error)
        return False
    now = datetime.now().astimezone()
    target = datetime.combine(draw_date, draw_time).replace(tzinfo=now.tzinfo)
    if now < target + timedelta(minutes=1):
        st.error("Este sorteo todavía no está habilitado para registrar el resultado real.")
        return False
    existing_draw = draw_for_slot(DATABASE_PATH, draw_date.isoformat(), draw_time.strftime("%H:%M"))
    if existing_draw and existing_draw.get("estado") != "pendiente_confirmacion":
        st.error("Ya existe un resultado para esta fecha y hora. No se puede agregar otro.")
        return False
    prediction = prediction_for_target(DATABASE_PATH, draw_date.isoformat(), draw_time.strftime("%H:%M"))
    if prediction is None or prediction.get("estado", "pendiente") != "pendiente" or prediction.get("acierto") is not None:
        if not (existing_draw and existing_draw.get("estado") == "pendiente_confirmacion" and prediction and prediction.get("estado") == "pendiente_confirmacion"):
            st.error("No existe una predicción pendiente y válida para esta fecha y hora.")
            return False
    if existing_draw and existing_draw.get("estado") == "pendiente_confirmacion":
        try:
            confirm_provisional_draw(
                DATABASE_PATH,
                draw_date.isoformat(),
                draw_time.strftime("%H:%M"),
                code,
                animal,
                "Confirmación posterior de un registro provisional.",
            )
        except ValueError as exc:
            st.error(str(exc))
            return False
        st.success(f"Resultado provisional confirmado: {code} - {animal}")
        return True
    try:
        insert_draw(
            DATABASE_PATH,
            draw_date.isoformat(),
            draw_time.strftime("%H:%M"),
            code,
            animal,
            weekday_for(draw_date),
            source,
        )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            st.error("Ya existe un resultado para esa fecha y hora.")
        else:
            st.error(f"No se pudo guardar el resultado: {exc}")
        return False
    st.success(f"Resultado guardado: {code} - {animal}")
    return True


@st.dialog("Confirmar resultado real")
def confirm_result_dialog(draw_date: date, draw_time: time, code: str, animal: str) -> None:
    now = datetime.now().astimezone()
    st.warning("Confirma que este resultado corresponde al sorteo indicado y que la hora oficial ya pasó.")
    st.write(f"**Sorteo:** {draw_date.isoformat()} {draw_time.strftime('%H:%M')}")
    st.write(f"**Resultado:** {code} - {animal}")
    st.write(f"**Hora del sistema:** {now.strftime('%Y-%m-%d %H:%M:%S %z')}")
    confirmed = st.checkbox("Confirmo que deseo guardarlo como resultado real.")
    if st.button("Confirmar y guardar", type="primary", disabled=not confirmed):
        if save_result(draw_date, draw_time, code, animal):
            prediction = prediction_for_target(DATABASE_PATH, draw_date.isoformat(), draw_time.strftime("%H:%M"))
            if prediction:
                hit = verify_prediction(DATABASE_PATH, prediction["id"], code, animal)
                st.success("Resultado verificado: el ganador apareció dentro del top 10 activo." if hit else "Resultado verificado: el ganador quedó fuera del top 10 activo.")
            st.session_state.pop("pending_result_confirmation", None)
            st.rerun()


def save_direct_result() -> None:
    latest_prediction_row = latest_prediction(DATABASE_PATH)
    if latest_prediction_row:
        target_date = date.fromisoformat(latest_prediction_row["objetivo_fecha"])
        target_time = datetime.strptime(latest_prediction_row["objetivo_hora"], "%H:%M").time()
    else:
        target_date, target_time = ensure_latest_result_target()

    animal = st.session_state.get("selected_result_animal")
    resolved_code = resolve_result_from_animal(animal)
    if not resolved_code:
        st.warning("Selecciona un animal válido para registrar el resultado.")
        return

    save_result(target_date, target_time, resolved_code, animal, source="panel")
    prediction = latest_prediction(DATABASE_PATH)
    if prediction:
        top10 = json.loads(prediction["top10_json"])
        winner_in_top10 = any(item["codigo"] == resolved_code for item in top10)
        if winner_in_top10:
            st.success("El ganador quedó dentro del top 10 de la predicción activa.")
        else:
            st.warning("El ganador quedó fuera del top 10 de la predicción activa.")
        st.caption(build_verification_summary(prediction, resolved_code))

    if st.button("Generar siguiente predicción"):
        next_prediction = coverage_prediction(DATABASE_PATH, reference_time=datetime.combine(target_date, target_time))
        save_prediction(DATABASE_PATH, next_prediction)
        st.success(f"Nueva predicción guardada para {next_prediction['target_date']} a las {next_prediction['target_time']}.")
        st.rerun()


st.title("Chamo Charly")
st.caption("Registro local y análisis estadístico de resultados")

tab_dashboard, tab_ingreso, tab_prediction, tab_verify, tab_analysis, tab_historial, tab_prediction_history, tab_evaluacion = st.tabs(
    ["Dashboard", "Ingreso", "Predicción", "Verificación", "Análisis", "Historial", "Historia de predicciones", "Evaluación Histórica"]
)

with tab_dashboard:
    total = count_draws(DATABASE_PATH)
    latest = recent_draws(DATABASE_PATH, 1)
    first_col, second_col, third_col = st.columns(3)
    first_col.metric("Sorteos registrados", total)
    second_col.metric("Etapa", "Observación" if total < 154 else "Análisis")
    second_col.caption("Los primeros 14 días son descriptivos.")
    third_col.metric("Universo", "38 animales")
    current_prediction = latest_prediction(DATABASE_PATH)
    if current_prediction:
        st.subheader("Predicción vigente")
        top10 = json.loads(current_prediction["top10_json"])
        ranking = json.loads(current_prediction["ranking_completo"] or current_prediction["probabilidades_json"])
        st.write(", ".join(f"{item['codigo']} - {item['animal']}" for item in top10))
        st.caption(
            f"Objetivo: {current_prediction['objetivo_fecha']} {current_prediction['objetivo_hora']} | "
            f"Cobertura estimada del top 10: {current_prediction['probabilidad_conjunto']:.2%}"
        )
        with st.expander("Ver Top 20"):
            top20_display = pd.DataFrame(ranking[:20])
            top20_display.insert(0, "posición", range(1, len(top20_display) + 1))
            st.dataframe(top20_display, width="stretch", hide_index=True)
        with st.expander("Ver ranking completo (1-38)"):
            full_display = pd.DataFrame(ranking)
            full_display.insert(0, "posición", range(1, len(full_display) + 1))
            st.dataframe(full_display, width="stretch", hide_index=True)
    if latest:
        st.subheader("Último resultado")
        st.write(f"**{latest[0]['codigo']} - {latest[0]['animal']}** | {latest[0]['fecha_sorteo']} {latest[0]['hora_sorteo']}")
    frequencies = frequency_by_animal(DATABASE_PATH)
    if frequencies:
        st.subheader("Frecuencias observadas")
        st.dataframe(pd.DataFrame(frequencies), width="stretch", hide_index=True)
    else:
        st.info("Aún no hay resultados. Regístralos desde la pestaña Ingreso.")

with tab_ingreso:
    st.subheader("Registrar resultado")
    st.info("La fecha y la hora se rellenan automáticamente con el sorteo activo para evitar errores humanos.")

    latest_prediction_row = latest_prediction(DATABASE_PATH)
    if latest_prediction_row:
        auto_date = date.fromisoformat(latest_prediction_row["objetivo_fecha"])
        auto_time = datetime.strptime(latest_prediction_row["objetivo_hora"], "%H:%M").time()
    else:
        auto_date, auto_time = ensure_latest_result_target()

    with st.form("manual_result_form", clear_on_submit=True):
        first_col, second_col = st.columns(2)
        draw_date = first_col.date_input("Fecha del sorteo", value=auto_date, disabled=True)
        draw_time = second_col.time_input("Hora del sorteo", value=auto_time, disabled=True)

        animal = st.selectbox(
            "Animal",
            list(ANIMALS.values()),
            index=0,
            key="selected_result_animal",
        )
        code = resolve_result_from_animal(animal)
        if code:
            st.caption(f"Código detectado automáticamente: {code} - {animal}")
        else:
            st.caption("No se pudo resolver el código del animal seleccionado.")

        submitted = st.form_submit_button("Guardar resultado y verificar")
    if submitted:
        if code is None:
            st.error("Selecciona un animal válido.")
        else:
            st.session_state["pending_result_confirmation"] = {
                "date": draw_date.isoformat(),
                "time": draw_time.strftime("%H:%M"),
                "code": code,
                "animal": animal,
            }

    pending_confirmation = st.session_state.get("pending_result_confirmation")
    if pending_confirmation:
        confirm_result_dialog(
            date.fromisoformat(pending_confirmation["date"]),
            datetime.strptime(pending_confirmation["time"], "%H:%M").time(),
            pending_confirmation["code"],
            pending_confirmation["animal"],
        )

    if st.session_state.get("result_ready_for_prediction"):
        if st.button("Crear siguiente predicción", key="create_next_prediction"):
            next_prediction = coverage_prediction(DATABASE_PATH, reference_time=datetime.now())
            save_prediction(DATABASE_PATH, next_prediction)
            st.session_state["result_ready_for_prediction"] = False
            st.success(f"Predicción nueva guardada para {next_prediction['target_date']} a las {next_prediction['target_time']}.")
            st.rerun()

    st.subheader("Carga masiva CSV")
    st.caption("Columnas obligatorias: fecha, hora, codigo, animal. Formato de fecha: YYYY-MM-DD.")
    uploaded_file = st.file_uploader("Selecciona un CSV", type="csv")
    if uploaded_file is not None and st.button("Validar y guardar CSV"):
        try:
            frame = pd.read_csv(uploaded_file, dtype={"codigo": str})
            required = {"fecha", "hora", "codigo", "animal"}
            missing = required - set(frame.columns)
            if missing:
                st.error(f"Faltan columnas: {', '.join(sorted(missing))}")
            else:
                rows = []
                errors = []
                for index, row in frame.iterrows():
                    normalized_code = str(row["codigo"]).strip()
                    error = validate_result(normalized_code, str(row["animal"]).strip())
                    if error:
                        errors.append(f"Fila {index + 2}: {error}")
                        continue
                    parsed_date = pd.to_datetime(row["fecha"], errors="coerce")
                    if pd.isna(parsed_date):
                        errors.append(f"Fila {index + 2}: fecha inválida.")
                        continue
                    rows.append((
                        parsed_date.date().isoformat(),
                        str(row["hora"]).strip(),
                        normalized_code,
                        str(row["animal"]).strip(),
                        weekday_for(parsed_date.date()),
                        "csv",
                        pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
                    ))
                if errors:
                    st.error("El CSV no se guardó porque contiene errores.")
                    st.code("\n".join(errors))
                else:
                    try:
                        from chamo_charly.database import insert_many
                        inserted, skipped = insert_many(DATABASE_PATH, rows)
                        st.success(f"Se guardaron {inserted} resultados nuevos.")
                        if skipped:
                            st.info(f"Se omitieron {skipped} resultados ya registrados.")
                    except Exception as exc:
                        st.error(f"No se pudo guardar el CSV: {exc}")
        except Exception as exc:
            st.error(f"No se pudo leer el CSV: {exc}")

with tab_prediction:
    st.subheader("Predicción BMA Dirichlet (1 Año de Experiencia)")
    st.info("🧬 Motor Activo: Bayesian Model Averaging (BMA) Dirichlet con 1 Año de Experiencia (4,140 Sorteos), Suavización Laplace Adaptativa, Calibración Vespertina y Empuje Bayesiano.")
    if st.button("Generar predicción para el próximo sorteo"):
        prediction = coverage_prediction(DATABASE_PATH, reference_time=datetime.now())
        save_prediction(DATABASE_PATH, prediction)
        st.success(
            f"Predicción BMA guardada para {prediction['target_date']} a las {prediction['target_time']} con 1 Año de Experiencia."
        )
        st.rerun()
    prediction = latest_prediction(DATABASE_PATH)
    if prediction:
        ranking = json.loads(prediction["probabilidades_json"])
        st.write(
            f"**Sorteo objetivo:** {prediction['objetivo_fecha']} {prediction['objetivo_hora']}  \n"
            f"**Experiencia del Modelo:** {prediction['observaciones']} sorteos  \n"
            f"**Modelo:** {prediction['modelo']}"
        )
        
        # Display Tiers
        top5_df = pd.DataFrame(ranking[:5])
        top5_df["probabilidad"] = top5_df["probabilidad"].map(lambda v: f"{v:.2%}")
        
        top6_10_df = pd.DataFrame(ranking[5:10])
        top6_10_df["probabilidad"] = top6_10_df["probabilidad"].map(lambda v: f"{v:.2%}")
        
        top11_20_df = pd.DataFrame(ranking[10:20])
        top11_20_df["probabilidad"] = top11_20_df["probabilidad"].map(lambda v: f"{v:.2%}")

        st.markdown("### 🏆 Top 5 Principal")
        st.dataframe(top5_df[["codigo", "animal", "probabilidad"]], width="stretch", hide_index=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 🎯 Top 6–10")
            st.dataframe(top6_10_df[["codigo", "animal", "probabilidad"]], width="stretch", hide_index=True)
        with col2:
            st.markdown("### 🛡️ Top 11–20 (Malla de Seguridad)")
            st.dataframe(top11_20_df[["codigo", "animal", "probabilidad"]], width="stretch", hide_index=True)

        st.metric("Probabilidad acumulada del Top 10", f"{prediction['probabilidad_conjunto']:.2%}")
        st.caption(confidence_label(prediction["probabilidad_conjunto"], prediction["observaciones"]))
        with st.expander("¿Por qué esta decisión?"):
            for explanation in json.loads(prediction["explicacion_json"]):
                st.write(f"- {explanation}")
            st.caption("Las probabilidades se estiman mediante ensamble BMA Dirichlet; no alteran el sorteo.")
        with st.expander("Ranking completo (38 animales)"):
            full_display = pd.DataFrame(ranking)
            full_display["probabilidad"] = full_display["probabilidad"].map(lambda value: f"{value:.2%}")
            st.dataframe(full_display, width="stretch", hide_index=True)
    else:
        st.warning("Todavía no existe una predicción. Genera una cuando quieras iniciar la evaluación.")

with tab_verify:
    st.subheader("Verificar predicción")
    pending = pending_predictions(DATABASE_PATH)
    if not pending:
        st.info("No hay predicciones pendientes de verificación.")
    else:
        options = {
            f"#{item['id']} - {item['objetivo_fecha']} {item['objetivo_hora']}": item
            for item in pending
        }
        selected_label = st.selectbox("Predicción", list(options))
        selected = options[selected_label]
        target_dt = datetime.strptime(f"{selected['objetivo_fecha']} {selected['objetivo_hora']}", "%Y-%m-%d %H:%M")
        if datetime.now() < target_dt:
            st.info(
                f"⏳ La predicción **#{selected['id']}** está programada para el sorteo del **{selected['objetivo_fecha']} a las {selected['objetivo_hora']}**. "
                f"Una vez publicado el resultado oficial de esa hora, podrás seleccionarlo aquí abajo para verificar su acierto."
            )
        code = st.selectbox(
            "Resultado real",
            list(ANIMALS),
            format_func=lambda item: f"{item} - {ANIMALS[item]}",
            key="verification_code",
        )
        if st.button("Verificar resultado"):
            hit = verify_prediction(DATABASE_PATH, selected["id"], code, ANIMALS[code])
            verified_prediction = prediction_by_id(DATABASE_PATH, selected["id"])
            if hit:
                st.success("Acierto: el resultado estaba dentro del top 10.")
            else:
                prediction = json.loads(selected["probabilidades_json"])
                item = next((entry for entry in prediction if entry["codigo"] == code), None)
                if item is not None:
                    st.warning(
                        f"No acertó: el resultado {code} - {ANIMALS[code]} quedó fuera del top 10 porque su score fue demasiado bajo en esta hora. "
                        f"Score total: {item['probabilidad']:.4%} | hora: {item.get('hora', 0):.4%} | día+hora: {item.get('dia_hora', 0):.4%} | Markov: {item.get('markov', 0):.4%} | reciente: {item.get('reciente', 0):.4%}."
                    )
                else:
                    st.warning("No acertó: el resultado no estaba dentro del top 10.")
            if verified_prediction:
                with st.expander("Posición y señales del ganador"):
                    st.write(
                        f"**Posición:** #{verified_prediction['posicion_ganador']} | "
                        f"**Franja:** {verified_prediction['franja']}"
                    )
                    st.json(json.loads(verified_prediction["pilares_influyentes"] or "{}"))

with tab_analysis:
    st.subheader("Análisis estadístico")
    st.info("Estas métricas describen el histórico. Una alerta estadística no demuestra fraude ni garantiza el próximo resultado.")
    analysis_frame = history_frame(str(DATABASE_PATH))
    if analysis_frame.empty:
        st.warning("Necesitas resultados registrados para ejecutar el análisis.")
    else:
        uniformity = uniformity_test(analysis_frame)
        first_col, second_col, third_col = st.columns(3)
        first_col.metric("Observaciones", uniformity["observaciones"])
        second_col.metric("Chi-cuadrado", f"{uniformity['estadistico']:.2f}")
        third_col.metric("P-valor", f"{uniformity['p_valor']:.4f}")
        st.caption("El p-valor se interpreta junto con el tamaño de muestra y no prueba por sí solo que exista un sesgo.")

        st.subheader("Frecuencias y peso reciente")
        frequencies = frequency_table(analysis_frame)
        recent = exponential_scores(analysis_frame)
        frequency_view = frequencies.merge(recent[["codigo", "peso_reciente"]], on="codigo")
        frequency_view["porcentaje"] = frequency_view["porcentaje"].map(lambda value: f"{value:.2%}")
        frequency_view["peso_reciente"] = frequency_view["peso_reciente"].map(lambda value: f"{value:.2%}")
        st.dataframe(frequency_view, width="stretch", hide_index=True)

        st.subheader("Rachas y horarios")
        run_result = runs_test(analysis_frame)
        st.write(
            f"**Rachas observadas:** {run_result['rachas']} | "
            f"**P-valor:** {run_result['p_valor']:.4f} | "
            f"**Interpretación:** {run_result['interpretacion']}"
        )
        st.dataframe(hourly_summary(analysis_frame), width="stretch", hide_index=True)

        st.subheader("Transiciones de Markov")
        transitions = markov_transitions(analysis_frame)
        if transitions.empty:
            st.info("Aún no hay suficientes transiciones para mostrar.")
        else:
            transitions["probabilidad"] = transitions["probabilidad"].map(lambda value: f"{value:.2%}")
            st.dataframe(transitions.head(25), width="stretch", hide_index=True)

        st.subheader("Aprendizaje de Charly")
        learning = verified_position_summary(DATABASE_PATH)
        metric_cols = st.columns(4)
        metric_cols[0].metric("Verificaciones", learning["total"])
        metric_cols[1].metric("Posición promedio", f"#{learning['promedio']:.1f}" if learning["promedio"] else "Sin datos")
        metric_cols[2].metric("Ganadores en top 10", learning["top10"])
        metric_cols[3].metric("Ganadores en top 20", learning["top20"])
        st.caption("Los pesos se actualizan gradualmente después de cada verificación y nunca usan el animal ganador como regla directa.")
        weight_rows = context_weight_rows(DATABASE_PATH)
        if weight_rows:
            weight_view = pd.DataFrame(weight_rows)
            weight_view["contexto"] = weight_view.apply(
                lambda row: f"{row['hora']:02d}:00 / día {row['dia_semana']}" if row["hora"] >= 0 else "Global",
                axis=1,
            )
            st.dataframe(
                weight_view[["contexto", "pilar", "peso", "total_verificaciones", "ultima_actualizacion"]],
                width="stretch",
                hide_index=True,
            )

with tab_historial:
    st.subheader("Últimos resultados")
    rows = recent_draws(DATABASE_PATH, 100)
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

with tab_prediction_history:
    st.subheader("Historia de predicciones")
    st.caption("Todas las predicciones verificadas y pendientes, desde la más reciente hasta la más antigua.")
    prediction_rows = prediction_history(DATABASE_PATH)
    history_view = []
    for prediction_row in prediction_rows:
        ranking = json.loads(prediction_row["ranking_completo"] or "[]")
        if not ranking:
            ranking = json.loads(prediction_row["probabilidades_json"] or "[]")
        result_code = prediction_row["resultado_codigo"]
        winner_position = next(
            (position for position, item in enumerate(ranking, start=1) if item.get("codigo") == result_code),
            None,
        )
        history_view.append({
            "fecha": prediction_row["objetivo_fecha"],
            "hora": prediction_row["objetivo_hora"],
            "modelo": prediction_row["modelo"],
            "resultado": (
                f"{result_code} - {prediction_row['resultado_animal']}"
                if result_code else "Pendiente"
            ),
            "posición": winner_position or "Pendiente",
            "top 5": "Sí" if winner_position and winner_position <= 5 else "No" if winner_position else "Pendiente",
            "top 10": "Sí" if winner_position and winner_position <= 10 else "No" if winner_position else "Pendiente",
            "top 20": "Sí" if winner_position and winner_position <= 20 else "No" if winner_position else "Pendiente",
            "franja": prediction_row["franja"] or "Pendiente",
        })
    if history_view:
        st.dataframe(pd.DataFrame(history_view), width="stretch", hide_index=True)
    else:
        st.info("Todavía no hay predicciones registradas.")

with tab_evaluacion:
    st.subheader("Evaluación histórica de la línea base")
    st.info("Esta prueba es de lectura y registro: ejecuta un backtest cronológico en producción y guarda el resultado en una tabla independiente sin tocar la predicción activa.")

    model_choice = st.selectbox("Modelo", ["6_pilares", "13_pilares"], index=0)
    train_pct = st.slider("Entrenamiento (%)", 40, 80, 60) / 100
    val_pct = st.slider("Validación (%)", 10, 35, 20) / 100
    test_pct = max(0.05, round(1.0 - train_pct - val_pct, 2))

    if st.button("Ejecutar evaluación histórica"):
        start = datetime.now()
        result = run_historical_evaluation(
            DATABASE_PATH,
            model_name=model_choice,
            train_pct=train_pct,
            val_pct=val_pct,
            test_pct=test_pct,
        )
        elapsed = (datetime.now() - start).total_seconds()
        result["duracion_segundos"] = elapsed
        result["fecha_ejecucion"] = datetime.now().astimezone().isoformat(timespec="seconds")
        save_historical_evaluation(DATABASE_PATH, result)
        st.success(f"Evaluación ejecutada en {elapsed:.2f}s y guardada en la base de datos.")
        st.json({
            "modelo": result["modelo"],
            "posicion_promedio": result["posicion_promedio"],
            "top5": result["top5"],
            "top10": result["top10"],
            "top20": result["top20"],
            "sorteos_entrenamiento": result["sorteos_entrenamiento"],
            "sorteos_validacion": result["sorteos_validacion"],
            "sorteos_prueba": result["sorteos_prueba"],
        })

    history = historical_runs(DATABASE_PATH)
    if history:
        history_view = pd.DataFrame(history)
        history_view = history_view.sort_values("id", ascending=False)
        display_cols = [
            "id",
            "modelo",
            "particion",
            "posicion_promedio",
            "top5",
            "top10",
            "top20",
            "sorteos_entrenamiento",
            "sorteos_validacion",
            "sorteos_prueba",
            "fecha_ejecucion",
            "duracion_segundos",
        ]
        st.dataframe(history_view[display_cols], width="stretch", hide_index=True)
    else:
        st.info("Todavía no hay ejecuciones históricas guardadas.")
