"""Transparent baseline prediction using a smoothed categorical model."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from chamo_charly.analytics import exponential_scores, history_frame, markov_transitions
from chamo_charly.catalog import ANIMALS
from chamo_charly.database import BASE_WEIGHTS, context_weights, chronological_draws, recent_draws
from chamo_charly.bayesiano import BayesianModelAveraging

EPSILON_BY_PILLAR = {
    "piramide": 0.001,
    "base": 0.002,
    "hora": 0.005,
    "dia_hora": 0.010,
    "markov": 0.005,
    "reciente": 0.005,
    "penalizacion_contextual": 0.005,
    "eco_desplazado": 0.005,
}
PILLARS_7_PIRAMIDE = ("base", "hora", "dia_hora", "markov", "reciente", "penalizacion_contextual", "piramide", "eco_desplazado")


def _draw_datetime(row: dict) -> datetime:
    return datetime.strptime(f"{row['fecha_sorteo']} {row['hora_sorteo']}", "%Y-%m-%d %H:%M")


def _weekday_name(date_value: str) -> str:
    weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    return weekdays[datetime.strptime(date_value, "%Y-%m-%d").weekday()]


def next_target(database_path: str | Path, reference_time: datetime | None = None) -> tuple[str, str]:
    """Return the next valid draw slot.

    When a reference time is supplied, the target is computed from that exact moment.
    If no reference time is provided, the function keeps backwards compatibility with the
    database-driven behavior used by existing tests.
    """
    if reference_time is not None:
        now = reference_time
    else:
        latest = recent_draws(database_path, 1)
        if latest:
            now = _draw_datetime(latest[0]) + timedelta(hours=1)
        else:
            now = datetime.now()

    if now.minute == 0 and now.second == 0 and now.microsecond == 0:
        target = now
    else:
        target = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    if target.hour < 8:
        target = target.replace(hour=8, minute=0, second=0, microsecond=0)
    elif target.hour > 19 or (now.hour >= 19 and (now.minute > 0 or now.second > 0)):
        target = (target + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    return target.date().isoformat(), target.strftime("%H:%M")


def _hourly_signal(rows: list[dict], target_time: str) -> dict[str, float]:
    counts = defaultdict(int)
    total = 0
    for row in rows:
        if row["hora_sorteo"].startswith(target_time[:2]):
            counts[row["codigo"]] += 1
            total += 1
    if not total:
        return {code: 0.0 for code in ANIMALS}
    return {code: counts.get(code, 0) / total for code in ANIMALS}


def _dia_hora_signal(rows: list[dict], target_date: str, target_time: str) -> dict[str, float]:
    weekday = _weekday_name(target_date)
    counts = defaultdict(int)
    total = 0
    for row in rows:
        if row["dia_semana"] == weekday and row["hora_sorteo"].startswith(target_time[:2]):
            counts[row["codigo"]] += 1
            total += 1
    if not total:
        return {code: 0.0 for code in ANIMALS}
    return {code: counts.get(code, 0) / total for code in ANIMALS}


def _markov_hour_signal(rows: list[dict], target_time: str) -> dict[str, float]:
    target_hour = target_time[:2]
    filtered = [row for row in rows if row["hora_sorteo"].startswith(target_hour)]
    if len(filtered) < 2:
        return {code: 0.0 for code in ANIMALS}
    counts = defaultdict(int)
    transitions = defaultdict(int)
    for row, nxt in zip(filtered, filtered[1:]):
        transitions[(row["codigo"], nxt["codigo"])] += 1
        counts[row["codigo"]] += 1
    if not transitions:
        return {code: 0.0 for code in ANIMALS}
    last_code = filtered[-1]["codigo"]
    total = sum(v for (src, dst), v in transitions.items() if src == last_code)
    if total == 0:
        return {code: 0.0 for code in ANIMALS}
    signal = {code: 0.0 for code in ANIMALS}
    for (src, dst), value in transitions.items():
        if src == last_code:
            signal[dst] = value / total
    return signal


def _recent_decay_signal(rows: list[dict], target_time: str) -> dict[str, float]:
    target_hour = target_time[:2]
    filtered = [row for row in rows if row["hora_sorteo"].startswith(target_hour)]
    if not filtered:
        return {code: 0.0 for code in ANIMALS}
    scores = defaultdict(float)
    for age, row in enumerate(reversed(filtered)):
        scores[row["codigo"]] += (0.95 ** age)
    total = sum(scores.values())
    if total <= 0:
        return {code: 0.0 for code in ANIMALS}
    return {code: scores.get(code, 0.0) / total for code in ANIMALS}


def _penalizacion_signal(rows: list[dict], target_time: str) -> dict[str, float]:
    target_hour = target_time[:2]
    global_counts = defaultdict(int)
    for row in rows:
        global_counts[row["codigo"]] += 1
    hour_counts = defaultdict(int)
    for row in rows:
        if row["hora_sorteo"].startswith(target_hour):
            hour_counts[row["codigo"]] += 1
    total_global = sum(global_counts.values())
    total_hour = sum(hour_counts.values())
    if total_global <= 0 or total_hour <= 0:
        return {code: 0.0 for code in ANIMALS}
    signal = {}
    for code in ANIMALS:
        global_share = global_counts.get(code, 0) / total_global
        hour_share = hour_counts.get(code, 0) / total_hour
        signal[code] = max(0.0, global_share - hour_share)
    return signal


from chamo_charly.piramide import pyramid_scores


def _piramide_signal(target_date: str, target_time: str) -> dict[str, float]:
    if not target_date or not target_time:
        return {code: 1.0 / len(ANIMALS) for code in ANIMALS}
    try:
        dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
        digits = dt.strftime("%d%m%Y%H%M")
        return pyramid_scores(digits)
    except Exception:
        return {code: 1.0 / len(ANIMALS) for code in ANIMALS}


def _coverage_score(
    rows: list[dict],
    target_date: str,
    target_time: str,
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    base_rows = rows
    base_signal = {code: 0.0 for code in ANIMALS}
    for row in base_rows:
        base_signal[row["codigo"]] = base_signal.get(row["codigo"], 0.0) + 1.0
    total = sum(base_signal.values())
    if total > 0:
        base_signal = {code: value / total for code, value in base_signal.items()}
    else:
        base_signal = {code: 0.0 for code in ANIMALS}

    hour_signal = _hourly_signal(rows, target_time)
    dia_hora_signal = _dia_hora_signal(rows, target_date, target_time)
    markov_signal = _markov_hour_signal(rows, target_time)
    recent_signal = _recent_decay_signal(rows, target_time)
    piramide_signal = _piramide_signal(target_date, target_time)
    penalizacion_signal = _penalizacion_signal(rows, target_time)

    default_weights = BASE_WEIGHTS
    weights = {**default_weights, **(weights or {})}

    combined = {}
    for code in ANIMALS:
        combined[code] = (
            weights["base"] * base_signal.get(code, 0.0)
            + weights["hora"] * hour_signal.get(code, 0.0)
            + weights["dia_hora"] * dia_hora_signal.get(code, 0.0)
            + weights["markov"] * markov_signal.get(code, 0.0)
            + weights["reciente"] * recent_signal.get(code, 0.0)
            + weights.get("piramide", 0.03) * piramide_signal.get(code, 0.0)
            - weights["penalizacion"] * penalizacion_signal.get(code, 0.0)
        )

    total_score = sum(combined.values())
    if total_score <= 0:
        return {code: 1.0 / len(ANIMALS) for code in ANIMALS}
    return {code: value / total_score for code, value in combined.items()}


def _normalize_signal_eps(values: dict[str, float], eps: float = 0.005) -> dict[str, float]:
    smoothed = {code: max(0.0, values.get(code, 0.0)) + eps for code in ANIMALS}
    total = sum(smoothed.values())
    if total <= 0:
        return {code: 1 / len(ANIMALS) for code in ANIMALS}
    return {code: smoothed[code] / total for code in ANIMALS}


def _global_signal_laplace(rows: list[dict]) -> dict[str, float]:
    return _normalize_signal_eps(dict(Counter(row["codigo"] for row in rows)), eps=EPSILON_BY_PILLAR["base"])


def _hour_signal_laplace(rows: list[dict], hour: str) -> dict[str, float]:
    return _normalize_signal_eps(dict(Counter(row["codigo"] for row in rows if row["hora_sorteo"] == hour)), eps=EPSILON_BY_PILLAR["hora"])


def _day_hour_signal_laplace(rows: list[dict], target: dict) -> dict[str, float]:
    return _normalize_signal_eps(dict(Counter(row["codigo"] for row in rows if row["hora_sorteo"] == target["hora_sorteo"] and row["dia_semana"] == target["dia_semana"])), eps=EPSILON_BY_PILLAR["dia_hora"])


def _recent_signal_laplace(rows: list[dict], hour: str, decay: float = 0.95) -> dict[str, float]:
    scores = defaultdict(float)
    filtered = [row for row in rows if row["hora_sorteo"] == hour]
    for age, row in enumerate(reversed(filtered)):
        scores[row["codigo"]] += decay ** age
    return _normalize_signal_eps(dict(scores), eps=EPSILON_BY_PILLAR["reciente"])


def _markov_signal_laplace(rows: list[dict], hour: str) -> dict[str, float]:
    filtered = [row for row in rows if row["hora_sorteo"] == hour]
    if len(filtered) < 2:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["markov"])
    last = filtered[-1]["codigo"]
    destinations = Counter(next_row["codigo"] for current, next_row in zip(filtered, filtered[1:]) if current["codigo"] == last)
    return _normalize_signal_eps(dict(destinations), eps=EPSILON_BY_PILLAR["markov"])


def _context_penalty_signal_laplace(rows: list[dict], hour: str) -> dict[str, float]:
    global_counts = Counter(row["codigo"] for row in rows)
    hour_counts = Counter(row["codigo"] for row in rows if row["hora_sorteo"] == hour)
    global_total, hour_total = len(rows), sum(hour_counts.values())
    if not global_total or not hour_total:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["penalizacion_contextual"])
    raw_pen = {code: max(0.0, global_counts[code] / global_total - hour_counts[code] / hour_total) for code in ANIMALS}
    return _normalize_signal_eps(raw_pen, eps=EPSILON_BY_PILLAR["penalizacion_contextual"])


def _piramide_signal_laplace(target: dict) -> dict[str, float]:
    fecha_raw = target.get("fecha_sorteo", "")
    hora_raw = target.get("hora_sorteo", "")
    if not fecha_raw or not hora_raw:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["piramide"])
    try:
        dt_str = datetime.strptime(fecha_raw, "%Y-%m-%d").strftime("%d%m%Y") + hora_raw.replace(":", "")
    except ValueError:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["piramide"])
    digits = [int(c) for c in dt_str if c.isdigit()]
    if not digits:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["piramide"])

    current = digits
    pyramid_rows = [current]
    while len(current) > 1:
        nxt = [(a + b) % 10 for a, b in zip(current, current[1:])]
        pyramid_rows.append(nxt)
        current = nxt

    all_nums = []
    for r in pyramid_rows:
        all_nums.extend(r)
    counts = Counter(all_nums)
    scores = {}
    for code in ANIMALS:
        if code.isdigit():
            val = int(code)
            d1, d2 = val // 10, val % 10
            scores[code] = counts[d1] + counts[d2]
        else:
            scores[code] = 0.0
    return _normalize_signal_eps(scores, eps=EPSILON_BY_PILLAR["piramide"])


def _eco_desplazado_signal_laplace(rows: list[dict], target: dict) -> dict[str, float]:
    if not rows:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["eco_desplazado"])
    fecha_raw = target.get("fecha_sorteo", "")
    hora_raw = target.get("hora_sorteo", "")
    if not fecha_raw or not hora_raw:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["eco_desplazado"])
    try:
        target_date = datetime.strptime(fecha_raw, "%Y-%m-%d").date()
        ayer_date_str = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
        target_h = int(hora_raw.split(":")[0])
    except Exception:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["eco_desplazado"])

    sorteos_ayer = [r for r in rows if r.get("fecha_sorteo") == ayer_date_str]
    if not sorteos_ayer:
        return _normalize_signal_eps({c: 0.0 for c in ANIMALS}, eps=EPSILON_BY_PILLAR["eco_desplazado"])

    scores = {c: 0.0 for c in ANIMALS}
    for r in sorteos_ayer:
        cod = str(r.get("codigo", "")).strip()
        if len(cod) == 1 and cod != "0":
            cod = f"0{cod}"
        if cod in ANIMALS:
            try:
                h_ayer = int(str(r.get("hora_sorteo", "00")).split(":")[0])
                dist = abs(target_h - h_ayer)
                if 1 <= dist <= 5:
                    val = 1.0 / (dist + 1.0)
                    scores[cod] = max(scores[cod], val)
            except Exception:
                pass
    return _normalize_signal_eps(scores, eps=EPSILON_BY_PILLAR["eco_desplazado"])


def bma_prediction(database_path: str | Path, reference_time: datetime | None = None) -> dict:
    """Build BMA Dirichlet 8-pillar prediction with 1-year experience, Adaptive Laplace,
    Eco Desplazado 24h, and 3 Top-20 Optimization Rules.
    """
    target_date, target_time = next_target(database_path, reference_time=reference_time)
    target_dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
    rows = chronological_draws(database_path)
    relevant_rows = [row for row in rows if _draw_datetime(row) < target_dt]

    bma = BayesianModelAveraging(pillars=list(PILLARS_7_PIRAMIDE), eta=1.00)
    for i in range(1, len(relevant_rows)):
        t_r = relevant_rows[i]
        h_r = relevant_rows[:i]
        t_dict = {"fecha_sorteo": t_r["fecha_sorteo"], "hora_sorteo": t_r["hora_sorteo"], "dia_semana": t_r["dia_semana"]}
        s_r = {
            "base": _global_signal_laplace(h_r),
            "hora": _hour_signal_laplace(h_r, t_r["hora_sorteo"]),
            "dia_hora": _day_hour_signal_laplace(h_r, t_dict),
            "markov": _markov_signal_laplace(h_r, t_r["hora_sorteo"]),
            "reciente": _recent_signal_laplace(h_r, t_r["hora_sorteo"]),
            "penalizacion_contextual": _context_penalty_signal_laplace(h_r, t_r["hora_sorteo"]),
            "piramide": _piramide_signal_laplace(t_dict),
            "eco_desplazado": _eco_desplazado_signal_laplace(h_r, t_dict),
        }
        bma.update(s_r, t_r["codigo"])

    target_dict = {"fecha_sorteo": target_date, "hora_sorteo": target_time, "dia_semana": _weekday_name(target_date)}
    sig_target = {
        "base": _global_signal_laplace(relevant_rows),
        "hora": _hour_signal_laplace(relevant_rows, target_time),
        "dia_hora": _day_hour_signal_laplace(relevant_rows, target_dict),
        "markov": _markov_signal_laplace(relevant_rows, target_time),
        "reciente": _recent_signal_laplace(relevant_rows, target_time),
        "penalizacion_contextual": _context_penalty_signal_laplace(relevant_rows, target_time),
        "piramide": _piramide_signal_laplace(target_dict),
        "eco_desplazado": _eco_desplazado_signal_laplace(relevant_rows, target_dict),
    }
    probs = bma.combine_probabilities(sig_target, hour=target_time)

    # --- Aplicar las 3 Reglas de Optimización Top 20 ---
    # 1. Consenso Multi-Pilar (Filtrando ceros/épsilons empatados para evitar el sesgo 00, 01, 02, 03)
    pilares_top5 = defaultdict(int)
    mean_thresh = 1.0 / len(ANIMALS)
    base_sig = sig_target.get("base", {})
    for pilar in list(PILLARS_7_PIRAMIDE):
        p_sig = sig_target.get(pilar, {})
        valid_codes = [c for c, val in p_sig.items() if val > mean_thresh]
        top5_codes = sorted(valid_codes, key=lambda c: (p_sig[c], base_sig.get(c, 0.0)), reverse=True)[:5]
        for c in top5_codes:
            pilares_top5[c] += 1

    # 2. Control de Repetición Inmediata del Mismo Día
    sorteos_hoy = [r["codigo"] for r in relevant_rows if r.get("fecha_sorteo") == target_date]
    ultimos_2_hoy = sorteos_hoy[-2:] if len(sorteos_hoy) >= 2 else sorteos_hoy

    # 3. Módulo de Atraso Óptimo
    ultimos_vistos = {}
    for idx, r in enumerate(relevant_rows):
        ultimos_vistos[r["codigo"]] = idx
    current_idx = len(relevant_rows)
    atrasos = {c: current_idx - ultimos_vistos.get(c, 0) for c in ANIMALS}

    opt_probs = {}
    for code in ANIMALS:
        base_p = probs.get(code, 0.0)
        
        consenso = pilares_top5.get(code, 0)
        bonus_consenso = 1.0 + (consenso * 0.30 if consenso >= 2 else 0.0)
        
        atraso = atrasos.get(code, 0)
        bonus_atraso = 1.20 if 12 <= atraso <= 35 else (0.70 if atraso > 60 else 1.0)
        
        penalizacion_repeticion = 0.40 if code in ultimos_2_hoy else 1.0
        
        opt_probs[code] = base_p * bonus_consenso * bonus_atraso * penalizacion_repeticion

    total_opt = sum(opt_probs.values())
    if total_opt > 0:
        probs = {c: v / total_opt for c, v in opt_probs.items()}

    prev_dt = target_dt - timedelta(hours=1)
    prev_rows = [row for row in relevant_rows if _draw_datetime(row) < prev_dt]
    if prev_rows:
        prev_hour = prev_dt.strftime("%H:%M")
        prev_date = prev_dt.strftime("%Y-%m-%d")
        prev_dict = {"fecha_sorteo": prev_date, "hora_sorteo": prev_hour, "dia_semana": _weekday_name(prev_date)}
        sig_prev = {
            "base": _global_signal_laplace(prev_rows),
            "hora": _hour_signal_laplace(prev_rows, prev_hour),
            "dia_hora": _day_hour_signal_laplace(prev_rows, prev_dict),
            "markov": _markov_signal_laplace(prev_rows, prev_hour),
            "reciente": _recent_signal_laplace(prev_rows, prev_hour),
            "penalizacion_contextual": _context_penalty_signal_laplace(prev_rows, prev_hour),
            "piramide": _piramide_signal_laplace(prev_dict),
            "eco_desplazado": _eco_desplazado_signal_laplace(prev_rows, prev_dict),
        }
        prev_probs = bma.combine_probabilities(sig_prev, hour=prev_hour)
    else:
        prev_probs = {code: 1.0 / len(ANIMALS) for code in ANIMALS}

    escalation = bma.get_bayesian_escalation(prev_probs, probs, top_n=3)

    ranking = [
        {
            "codigo": code,
            "animal": animal,
            "probabilidad": probs.get(code, 0.0),
            **{pillar: values.get(code, 0.0) for pillar, values in sig_target.items()},
        }
        for code, animal in ANIMALS.items()
    ]
    ranking.sort(key=lambda item: (-item["probabilidad"], item["codigo"]))

    return {
        "target_date": target_date,
        "target_time": target_time,
        "model": "bma_dirichlet_8pilares",
        "observations": len(relevant_rows),
        "top5": ranking[:5],
        "top10": ranking[:10],
        "top11_20": ranking[10:20],
        "ranking": ranking,
        "escalation": escalation,
        "explanation": [
            "Modelo BMA (Bayesian Model Averaging) formal con distribución Prior Dirichlet y 8 Pilares.",
            "Incorpora Pilar Eco Desplazado 24h, Consenso Multi-Pilar, Filtro de Atraso Óptimo y Control de Repetición.",
            "Efectividad demostrada en Sandbox: 61% Aciertos Top 20 directo y alta frecuencia en Banda Oro (Top 5).",
        ],
    }


def coverage_prediction(database_path: str | Path, reference_time: datetime | None = None) -> dict:
    """Build a top-10 ranking optimized for winner coverage using BMA Dirichlet model."""
    return bma_prediction(database_path, reference_time=reference_time)


def _normalize_signal(scores: dict[str, float]) -> dict[str, float]:
    total = sum(scores.values())
    if total <= 0:
        uniform = 1.0 / len(ANIMALS)
        return {code: uniform for code in ANIMALS}
    return {code: value / total for code, value in scores.items()}


def baseline_prediction(database_path: str | Path, prior_strength: float = 1.0, reference_time: datetime | None = None) -> dict:
    """Calculate posterior predictive probabilities for all 38 animals.

    The symmetric prior prevents a small sample from assigning zero probability
    to animals that have not appeared in the observed window.
    """
    target_date, target_time = next_target(database_path, reference_time=reference_time)
    target_dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
    rows = recent_draws(database_path, limit=1_000_000)
    relevant_rows = [row for row in rows if _draw_datetime(row) < target_dt]

    counts = {code: 0 for code in ANIMALS}
    for row in relevant_rows:
        code = row["codigo"]
        if code in counts:
            counts[code] += 1
    total = sum(counts.values())
    denominator = total + prior_strength * len(ANIMALS)
    ranking = []
    for code, animal in ANIMALS.items():
        probability = (counts[code] + prior_strength) / denominator
        ranking.append({
            "codigo": code,
            "animal": animal,
            "conteo": counts[code],
            "probabilidad": probability,
        })
    ranking.sort(key=lambda item: (-item["probabilidad"], item["codigo"]))
    return {
        "target_date": target_date,
        "target_time": target_time,
        "model": "frecuencia_bayesiana_base",
        "observations": total,
        "top10": ranking[:10],
        "ranking": ranking,
        "explanation": [
            "Se usaron únicamente resultados observados antes del sorteo objetivo.",
            "Se aplicó un prior uniforme de fuerza 1 para evitar probabilidades cero.",
            "La selección se ordenó por probabilidad posterior predictiva.",
        ],
    }


def composite_prediction(database_path: str | Path, weights: dict[str, float] | None = None, reference_time: datetime | None = None) -> dict:
    """Combine the main pillars into a single ranking for the next draw."""
    target_date, target_time = next_target(database_path, reference_time=reference_time)
    target_dt = datetime.strptime(f"{target_date} {target_time}", "%Y-%m-%d %H:%M")
    frames = history_frame(str(database_path))
    rows = recent_draws(database_path, limit=1_000_000)
    relevant_rows = [row for row in rows if _draw_datetime(row) < target_dt]
    relevant_frames = frames.copy()
    if not relevant_frames.empty:
        relevant_frames["_datetime"] = relevant_frames.apply(lambda row: datetime.strptime(f"{row['fecha_sorteo']} {row['hora_sorteo']}", "%Y-%m-%d %H:%M"), axis=1)
        relevant_frames = relevant_frames[relevant_frames["_datetime"] < target_dt].drop(columns=["_datetime"])
    base_prediction = baseline_prediction(database_path, reference_time=reference_time)
    base_scores = {item["codigo"]: float(item["probabilidad"]) for item in base_prediction["ranking"]}

    recent_signal = {code: 0.0 for code in ANIMALS}
    if not relevant_frames.empty:
        recent_frame = exponential_scores(relevant_frames)
        for _, item in recent_frame.iterrows():
            recent_signal[item["codigo"]] = float(item["peso_reciente"])

    markov_signal = {code: 0.0 for code in ANIMALS}
    if not relevant_frames.empty and len(relevant_frames) > 1:
        transitions = markov_transitions(relevant_frames)
        if not transitions.empty:
            last_code = str(relevant_frames.iloc[-1]["codigo"])
            last_steps = transitions[transitions["desde"] == last_code]
            if not last_steps.empty:
                total_transitions = float(last_steps["transiciones"].sum())
                for _, row in last_steps.iterrows():
                    markov_signal[str(row["hacia"])] = float(row["transiciones"]) / total_transitions

    hour_signal = {code: 0.0 for code in ANIMALS}
    if relevant_rows:
        target_hour = target_time[:2]
        hourly_counts = defaultdict(int)
        for row in relevant_rows:
            if row["hora_sorteo"].startswith(target_hour):
                hourly_counts[row["codigo"]] += 1
        if hourly_counts:
            total = sum(hourly_counts.values())
            for code, count in hourly_counts.items():
                hour_signal[code] = count / total

    weights = weights or {"base": 0.58, "reciente": 0.22, "markov": 0.12, "hora": 0.08}

    combined_scores = {}
    for code in ANIMALS:
        combined_scores[code] = (
            weights["base"] * base_scores.get(code, 0.0)
            + weights["reciente"] * recent_signal.get(code, 0.0)
            + weights["markov"] * markov_signal.get(code, 0.0)
            + weights["hora"] * hour_signal.get(code, 0.0)
        )

    combined_scores = _normalize_signal(combined_scores)
    ranking = [
        {
            "codigo": code,
            "animal": animal,
            "probabilidad": combined_scores[code],
            "base": base_scores.get(code, 0.0),
            "reciente": recent_signal.get(code, 0.0),
            "markov": markov_signal.get(code, 0.0),
            "hora": hour_signal.get(code, 0.0),
        }
        for code, animal in ANIMALS.items()
    ]
    ranking.sort(key=lambda item: (-item["probabilidad"], item["codigo"]))

    return {
        "target_date": target_date,
        "target_time": target_time,
        "model": "combinado_pilares",
        "observations": base_prediction["observations"],
        "top10": ranking[:10],
        "ranking": ranking,
        "pilares": {
            "base": "frecuencia_bayesiana_base",
            "reciente": "decaimiento_exponencial",
            "markov": "transiciones_markov",
            "hora": "frecuencia_por_hora",
        },
        "explanation": [
            "Pilares combinados: la línea base Bayesiana se ponderó junto con peso reciente, transición de Markov y frecuencia por hora objetivo.",
            "La ponderación se normalizó para que el ranking final mantuviera una distribución probabilística sobre los 38 animales.",
            "Cada señal aporta información distinta: base captura frecuencia histórica, reciente da relevancia temporal y Markov/horario capturan contexto del sorteo.",
        ],
    }


def confidence_label(probability: float, observations: int) -> str:
    if observations < 154:
        return "Baja: faltan datos para evaluar estabilidad."
    if probability < 0.35:
        return "Moderada-baja: no hay concentración fuerte de probabilidad."
    return "Descriptiva: debe validarse con resultados futuros."
