"""Scraper module for Lotto Activo live draw verification."""

from __future__ import annotations

import logging
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.lottoactivo.com/resultados/lotto_activo/",
}

def format_animal_code(raw_num: str | int) -> str:
    """Format raw animal number string/int to standard 2-char catalog code."""
    s = str(raw_num).strip()
    if s == "0" or s == "00":
        return s
    try:
        val = int(s)
        return f"{val:02d}"
    except ValueError:
        return s

def fetch_lotto_activo_day(date_str: str) -> List[Dict]:
    """Fetch all draw results for a given date (YYYY-MM-DD) from Lotto Activo API."""
    url_page = f"https://www.lottoactivo.com/resultados/lotto_activo/{date_str}/"
    url_api = "https://www.lottoactivo.com/core/process.php"

    try:
        resp = requests.get(url_page, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Lotto Activo HTTP {resp.status_code} for {date_str}")
            return []

        token_match = re.search(
            r"function results_image\(\).*?data\s*=\s*\{\s*'option':'([^']+)",
            resp.text,
            re.DOTALL,
        )
        if not token_match:
            logger.warning(f"Token no encontrado en HTML para {date_str}")
            return []

        token = token_match.group(1)
        payload = {
            "option": token,
            "loteria": "lotto_activo",
            "fecha": date_str,
        }
        api_resp = requests.post(url_api, data=payload, headers={**HEADERS, "Referer": url_page}, timeout=15)
        api_resp.raise_for_status()
        data = api_resp.json()

        results = []
        for item in data.get("datos", []):
            code = format_animal_code(item.get("number_animal", ""))
            results.append({
                "fecha": date_str,
                "hora_s": item.get("time_s", ""),           # e.g. "08:00 AM"
                "hora_24": item.get("time_schedule", "")[:5], # e.g. "08:00"
                "codigo": code,
                "animal": item.get("name_animal", "").capitalize(),
            })
        return results

    except Exception as exc:
        logger.error(f"Error consultando Lotto Activo para {date_str}: {exc}")
        return []

def fetch_lotto_activo_draw(date_str: str, time_str: str) -> Optional[Dict]:
    """Fetch specific draw result for date (YYYY-MM-DD) and time (HH:MM in 24h format)."""
    draws = fetch_lotto_activo_day(date_str)
    for draw in draws:
        if draw["hora_24"] == time_str:
            return draw
    return None
