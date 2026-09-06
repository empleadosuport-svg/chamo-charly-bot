from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from chamo_charly.database import BASE_WEIGHTS, connect, chronological_draws
from chamo_charly.predictor import _coverage_score, _draw_datetime, _hourly_signal, _markov_hour_signal, _normalize_signal, _penalizacion_signal, _recent_decay_signal, _dia_hora_signal
from chamo_charly.catalog import ANIMALS
from chamo_charly.piramide import pyramid_scores


DEFAULT_MODEL = "6_pilares"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _weight_map(model_name: str, overrides: dict[str, float] | None = None) -> dict[str, float]:
    weights = BASE_WEIGHTS.copy()
    if model_name == "6_pilares":
        return weights
    if model_name == "13_pilares":
        weights.update({
            "base": 0.18,
            "hora": 0.32,
            "dia_hora": 0.22,
            "markov": 0.16,
            "reciente": 0.10,
            "penalizacion": 0.02,
        })
        return weights
    if model_name == "7_pilares_piramide":
        weights["piramide"] = 0.02
        return weights
    if overrides:
        weights.update(overrides)
    return weights


def _build_prediction_rows(rows: list[dict], target_date: str, target_time: str, weights: dict[str, float]) -> list[dict]:
    target_dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
    relevant = [row for row in rows if _draw_datetime(row) < target_dt]
    pyramid_weight = float(weights.get("piramide", 0.0))
    base_weights = {key: value for key, value in weights.items() if key != "piramide"}
    score_map = _coverage_score(relevant, target_date, target_time, base_weights)
    if pyramid_weight > 0:
        digits = target_date[8:10] + target_date[5:7] + target_date[:4] + target_time.replace(":", "")
        pyramid = pyramid_scores(digits)
        score_map = {
            code: (1.0 - pyramid_weight) * score_map.get(code, 0.0)
            + pyramid_weight * pyramid.get(code, 0.0)
            for code in ANIMALS
        }
    ranking = [
        {
            "codigo": code,
            "animal": animal,
            "probabilidad": score_map.get(code, 0.0),
            "hora": _hourly_signal(relevant, target_time).get(code, 0.0),
            "dia_hora": _dia_hora_signal(relevant, target_date, target_time).get(code, 0.0),
            "markov": _markov_hour_signal(relevant, target_time).get(code, 0.0),
            "reciente": _recent_decay_signal(relevant, target_time).get(code, 0.0),
            "penalizacion": _penalizacion_signal(relevant, target_time).get(code, 0.0),
        }
        for code, animal in ANIMALS.items()
    ]
    ranking.sort(key=lambda item: (-item["probabilidad"], item["codigo"]))
    return ranking


def _resolve_position(ranking: list[dict], code: str) -> int:
    for index, item in enumerate(ranking, start=1):
        if item["codigo"] == code:
            return index
    return len(ANIMALS) + 1


def _summarize_predictions(ranking: list[dict], rows: list[dict]) -> dict[str, float | int]:
    positions = []
    top5 = 0
    top10 = 0
    top20 = 0
    for row in rows:
        if not ranking:
            break
        winner = row["codigo"]
        position = _resolve_position(ranking, winner)
        positions.append(position)
        if position <= 5:
            top5 += 1
        if position <= 10:
            top10 += 1
        if position <= 20:
            top20 += 1
    return {
        "posicion_promedio": sum(positions) / len(positions) if positions else 0.0,
        "top5": top5,
        "top10": top10,
        "top20": top20,
        "sorteos": len(positions),
    }


def run_historical_evaluation(
    database_path: str | Path,
    model_name: str = DEFAULT_MODEL,
    weights: dict[str, float] | None = None,
    train_pct: float = 0.6,
    val_pct: float = 0.2,
    test_pct: float = 0.2,
) -> dict[str, Any]:
    """Run a simple 60/20/20 chronological historical evaluation without mutating the live prediction state."""
    rows = chronological_draws(database_path, limit=1_000_000)
    if not rows:
        return {
            "modelo": model_name,
            "posicion_promedio": 0.0,
            "top5": 0,
            "top10": 0,
            "top20": 0,
            "sorteos_entrenamiento": 0,
            "sorteos_validacion": 0,
            "sorteos_prueba": 0,
        }

    total = len(rows)
    train_end = max(1, int(total * train_pct))
    val_end = max(train_end + 1, int(total * (train_pct + val_pct)))
    test_end = total

    train_rows = rows[:train_end]
    val_rows = rows[train_end:val_end]
    test_rows = rows[val_end:test_end]

    model_weights = _weight_map(model_name, weights)

    train_summary = {"posicion_promedio": 0.0, "top5": 0, "top10": 0, "top20": 0, "sorteos": 0}
    if train_rows:
        train_summary = {"posicion_promedio": 0.0, "top5": 0, "top10": 0, "top20": 0, "sorteos": 0}
        for idx in range(1, len(train_rows)):
            target = train_rows[idx]
            ranking = _build_prediction_rows(train_rows[:idx], target["fecha_sorteo"], target["hora_sorteo"], model_weights)
            position = _resolve_position(ranking, target["codigo"])
            train_summary["sorteos"] += 1
            train_summary["posicion_promedio"] += position
            if position <= 5:
                train_summary["top5"] += 1
            if position <= 10:
                train_summary["top10"] += 1
            if position <= 20:
                train_summary["top20"] += 1
        if train_summary["sorteos"]:
            train_summary["posicion_promedio"] = train_summary["posicion_promedio"] / train_summary["sorteos"]

    validation_metrics: dict[str, float | int] = {"posicion_promedio": 0.0, "top5": 0, "top10": 0, "top20": 0, "sorteos": 0}
    if val_rows:
        validation_positions = []
        for idx, target in enumerate(val_rows, start=train_end):
            history = rows[:idx]
            ranking = _build_prediction_rows(history, target["fecha_sorteo"], target["hora_sorteo"], model_weights)
            position = _resolve_position(ranking, target["codigo"])
            validation_positions.append(position)
            if position <= 5:
                validation_metrics["top5"] += 1
            if position <= 10:
                validation_metrics["top10"] += 1
            if position <= 20:
                validation_metrics["top20"] += 1
        validation_metrics["sorteos"] = len(validation_positions)
        validation_metrics["posicion_promedio"] = sum(validation_positions) / len(validation_positions) if validation_positions else 0.0

    test_metrics: dict[str, float | int] = {"posicion_promedio": 0.0, "top5": 0, "top10": 0, "top20": 0, "sorteos": 0}
    if test_rows:
        test_positions = []
        for idx, target in enumerate(test_rows, start=val_end):
            history = rows[:idx]
            ranking = _build_prediction_rows(history, target["fecha_sorteo"], target["hora_sorteo"], model_weights)
            position = _resolve_position(ranking, target["codigo"])
            test_positions.append(position)
            if position <= 5:
                test_metrics["top5"] += 1
            if position <= 10:
                test_metrics["top10"] += 1
            if position <= 20:
                test_metrics["top20"] += 1
        test_metrics["sorteos"] = len(test_positions)
        test_metrics["posicion_promedio"] = sum(test_positions) / len(test_positions) if test_positions else 0.0

    detail = {
        "modelo": model_name,
        "configuracion": json.dumps(model_weights, ensure_ascii=False),
        "posicion_promedio": float(validation_metrics["posicion_promedio"]),
        "top5": int(validation_metrics["top5"]),
        "top10": int(validation_metrics["top10"]),
        "top20": int(validation_metrics["top20"]),
        "sorteos_entrenamiento": int(train_summary["sorteos"]),
        "sorteos_validacion": int(validation_metrics["sorteos"]),
        "sorteos_prueba": int(test_metrics["sorteos"]),
        "prueba_final": test_metrics,
        "validacion_final": validation_metrics,
    }
    return detail


def save_historical_evaluation(database_path: str | Path, result: dict[str, Any]) -> int:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO pruebas_historicas
            (configuracion, modelo, particion, rango_dias, posicion_promedio, top5, top10, top20,
             sorteos_entrenamiento, sorteos_validacion, sorteos_prueba, fecha_ejecucion, duracion_segundos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("configuracion", "{}"),
                result.get("modelo", DEFAULT_MODEL),
                "60/20/20",
                len(chronological_draws(database_path, limit=1_000_000)),
                float(result.get("posicion_promedio", 0.0)),
                int(result.get("top5", 0)),
                int(result.get("top10", 0)),
                int(result.get("top20", 0)),
                int(result.get("sorteos_entrenamiento", 0)),
                int(result.get("sorteos_validacion", 0)),
                int(result.get("sorteos_prueba", 0)),
                datetime.now().astimezone().isoformat(timespec="seconds"),
                0.0,
            ),
        )
        return int(cursor.lastrowid)


__all__ = ["run_historical_evaluation", "save_historical_evaluation"]
