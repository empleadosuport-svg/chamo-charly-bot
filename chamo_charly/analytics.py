"""Statistical diagnostics for the observed draw history."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt

import pandas as pd
from scipy.stats import chisquare, norm

from chamo_charly.catalog import ANIMALS
from chamo_charly.database import recent_draws


def history_frame(database_path: str) -> pd.DataFrame:
    rows = recent_draws(database_path, limit=1_000_000)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["fecha_sorteo", "hora_sorteo", "codigo", "animal", "dia_semana"])
    return frame.sort_values(["fecha_sorteo", "hora_sorteo", "id"]).reset_index(drop=True)


def frequency_table(frame: pd.DataFrame) -> pd.DataFrame:
    counts = frame["codigo"].value_counts() if not frame.empty else pd.Series(dtype="int64")
    total = len(frame)
    return pd.DataFrame([
        {
            "codigo": code,
            "animal": animal,
            "salidas": int(counts.get(code, 0)),
            "porcentaje": (int(counts.get(code, 0)) / total) if total else 0.0,
        }
        for code, animal in ANIMALS.items()
    ]).sort_values(["salidas", "codigo"], ascending=[False, True], ignore_index=True)


def uniformity_test(frame: pd.DataFrame) -> dict:
    counts = [int((frame["codigo"] == code).sum()) for code in ANIMALS]
    expected = [len(frame) / len(ANIMALS)] * len(ANIMALS)
    if not frame.empty:
        statistic, p_value = chisquare(counts, expected)
    else:
        statistic, p_value = 0.0, 1.0
    return {"estadistico": float(statistic), "p_valor": float(p_value), "observaciones": len(frame)}


def exponential_scores(frame: pd.DataFrame, decay: float = 0.95) -> pd.DataFrame:
    scores = Counter({code: 0.0 for code in ANIMALS})
    for age, code in enumerate(reversed(frame["codigo"].tolist())):
        if code in scores:
            scores[code] += decay**age
    total = sum(scores.values())
    return pd.DataFrame([
        {"codigo": code, "animal": ANIMALS[code], "peso_reciente": scores[code] / total if total else 0.0}
        for code in ANIMALS
    ]).sort_values("peso_reciente", ascending=False, ignore_index=True)


def markov_transitions(frame: pd.DataFrame) -> pd.DataFrame:
    transitions: dict[str, Counter] = defaultdict(Counter)
    codes = frame["codigo"].tolist()
    for current, following in zip(codes, codes[1:]):
        transitions[current][following] += 1
    rows = []
    for current, following_counts in transitions.items():
        total = sum(following_counts.values())
        for following, count in following_counts.items():
            rows.append({
                "desde": current,
                "desde_animal": ANIMALS.get(current, current),
                "hacia": following,
                "hacia_animal": ANIMALS.get(following, following),
                "transiciones": count,
                "probabilidad": count / total,
            })
    return pd.DataFrame(rows).sort_values("probabilidad", ascending=False, ignore_index=True) if rows else pd.DataFrame()


def runs_test(frame: pd.DataFrame) -> dict:
    values = [int(code) for code in frame["codigo"] if code.isdigit()]
    binary = [value % 2 for value in values]
    if len(binary) < 2 or len(set(binary)) < 2:
        return {"rachas": 0, "z": 0.0, "p_valor": 1.0, "interpretacion": "Datos insuficientes"}
    runs = 1 + sum(left != right for left, right in zip(binary, binary[1:]))
    ones = sum(binary)
    zeros = len(binary) - ones
    expected = 1 + (2 * ones * zeros / len(binary))
    variance = (2 * ones * zeros * (2 * ones * zeros - len(binary))) / (
        len(binary) ** 2 * (len(binary) - 1)
    )
    z_score = (runs - expected) / sqrt(variance) if variance > 0 else 0.0
    p_value = float(2 * norm.sf(abs(z_score)))
    interpretation = "Compatible con aleatoriedad"
    if p_value < 0.05:
        interpretation = "Secuencia atípica; requiere validación posterior"
    return {"rachas": runs, "z": float(z_score), "p_valor": p_value, "interpretacion": interpretation}


def hourly_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["hora", "salidas"])
    return frame.groupby("hora_sorteo", as_index=False).size().rename(columns={"size": "salidas"})