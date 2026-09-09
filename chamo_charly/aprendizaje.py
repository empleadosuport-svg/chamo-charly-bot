"""Módulo de Auto-Aprendizaje Real para Chamo Charly.

Este módulo cierra el ciclo de aprendizaje que antes estaba roto:

    Resultado Real → actualizar_bma_con_resultado() → alpha actualizado en DB
                                                      ↑
    Siguiente predicción carga este alpha y predice   │
    con los pesos que el sistema APRENDIÓ, no los     │
    hardcodeados de BASE_WEIGHTS.                     ┘

Uso:
    from chamo_charly.aprendizaje import actualizar_bma_con_resultado
    actualizar_bma_con_resultado(DATABASE_PATH, winning_code, hora, dia_semana)
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from chamo_charly.bayesiano import BayesianModelAveraging
from chamo_charly.database import (
    chronological_draws,
    load_bma_alpha,
    save_bma_alpha,
)
from chamo_charly.predictor import (
    PILLARS_7_PIRAMIDE,
    _context_penalty_signal_laplace,
    _day_hour_signal_laplace,
    _disparadores_click_signal_laplace,
    _eco_desplazado_signal_laplace,
    _estacionalidad_mes_signal_laplace,
    _global_signal_laplace,
    _hour_signal_laplace,
    _markov_signal_laplace,
    _piramide_signal_laplace,
    _recent_signal_laplace,
)

logger = logging.getLogger(__name__)

VET = ZoneInfo("America/Caracas")

# Cuántos sorteos recientes se usan para la actualización incremental.
# En bootstrap (primera vez) se procesan TODOS los históricos.
_VENTANA_INCREMENTAL = 60


def _get_eta_actual() -> float:
    """Retorna eta=0.70 si estamos en el periodo Turbo (7 días hasta 2026-09-16), o 0.30 normal."""
    today_str = datetime.now(VET).strftime("%Y-%m-%d")
    if today_str <= "2026-09-16":
        return 0.70
    return 0.30



def actualizar_bma_con_resultado(
    database_path: str | Path,
    winning_code: str,
    hora: str,
    dia_semana: str,
) -> dict[str, float]:
    """Actualiza el BMA con un resultado real recién verificado.

    Este es el núcleo del auto-aprendizaje. Se llama cada vez que se confirma
    un resultado real (automático por scraper o manual por el usuario).

    Flujo:
        1. Carga el alpha guardado en DB (o hace bootstrap si no existe)
        2. Toma la ventana de los últimos _VENTANA_INCREMENTAL sorteos
        3. Calcula señales de los 8 pilares para el sorteo ganador
        4. Llama a bma.update() -> ajusta alpha según la evidencia
        5. Guarda el nuevo alpha en DB

    Args:
        database_path: Ruta a la base de datos SQLite.
        winning_code: Código del animal ganador (ej. "06").
        hora: Hora del sorteo en formato "HH:MM" (ej. "10:00").
        dia_semana: Nombre del día (ej. "lunes").

    Returns:
        Los pesos esperados E[w] = alpha_m / sum(alpha) del BMA actualizado.
    """
    rows = chronological_draws(database_path)
    if len(rows) < 2:
        logger.warning("Insuficientes sorteos para actualizar el BMA.")
        return {}

    # El target es el último sorteo registrado (recién confirmado)
    t_row = rows[-1]
    h_rows = rows[:-1]

    # Ventana incremental: solo los últimos N para contexto de señales
    h_ventana = h_rows[-_VENTANA_INCREMENTAL:]

    target = {
        "fecha_sorteo": t_row["fecha_sorteo"],
        "hora_sorteo": t_row["hora_sorteo"],
        "dia_semana": t_row.get("dia_semana") or dia_semana,
    }

    # Cargar o crear el BMA con su estado alpha acumulado
    saved_alpha = load_bma_alpha(database_path)

    if saved_alpha is None:
        logger.info("Primer resultado real: ejecutando bootstrap histórico completo...")
        bootstrap_bma_desde_historico(database_path)
        saved_alpha = load_bma_alpha(database_path)

    eta_val = _get_eta_actual()
    bma = BayesianModelAveraging(
        pillars=list(PILLARS_7_PIRAMIDE),
        eta=eta_val,   # Modo Turbo 0.70 (hasta 2026-09-16) / 0.30 normal
    )
    if saved_alpha:
        bma.alpha = {p: saved_alpha.get(p, bma.alpha.get(p, 1.0)) for p in bma.pillars}

    # Calcular señales y actualizar alpha
    signals = _build_signals(h_ventana, target)
    bma.update(signals, winning_code)

    # Persistir el nuevo estado alpha
    save_bma_alpha(database_path, bma.alpha)

    # Retornar pesos esperados actualizados para logging
    new_weights = bma.get_expected_weights()
    logger.info(
        "BMA actualizado | Ganador: %s (%s) | Pilares top: %s",
        winning_code, hora,
        sorted(new_weights, key=new_weights.get, reverse=True)[:3],
    )
    return new_weights
