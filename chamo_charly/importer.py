"""Convert the copied Lotto Activo text into the project's CSV format."""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from chamo_charly.catalog import ANIMALS

DATE_HEADER = re.compile(r"^#*\s*Resultados del dia: (\d{2}/\d{2}/\d{4})$")
RESULT_LINE = re.compile(r"^#*\s*(\d{1,2}|00)\s+(.+?)\s*$")
TIME_LINE = re.compile(r"^Lotto Activo (\d{1,2}):(\d{2}) (AM|PM)$")
NAME_ALIASES = {"Caiman": "Caimán", "Delfin": "Delfín"}


def _iso_date(value: str) -> str:
    return datetime.strptime(value, "%d/%m/%Y").date().isoformat()


def _time_24_hour(hour: str, minute: str, period: str) -> str:
    parsed = datetime.strptime(f"{hour}:{minute} {period}", "%I:%M %p")
    return parsed.strftime("%H:%M")


def parse_raw_text(raw_text: str) -> tuple[list[dict[str, str]], list[str]]:
    records: dict[tuple[str, str, str, str], dict[str, str]] = {}
    warnings: list[str] = []
    current_date: str | None = None
    pending_result: tuple[str, str] | None = None

    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        date_match = DATE_HEADER.match(line)
        if date_match:
            current_date = _iso_date(date_match.group(1))
            pending_result = None
            continue

        result_match = RESULT_LINE.match(line)
        if result_match:
            pending_result = (result_match.group(1), NAME_ALIASES.get(result_match.group(2), result_match.group(2)))
            continue

        time_match = TIME_LINE.match(line)
        if not time_match or pending_result is None:
            continue
        if current_date is None:
            warnings.append(f"Línea {line_number}: resultado sin fecha.")
            pending_result = None
            continue

        code, animal = pending_result
        if code not in ANIMALS:
            warnings.append(f"Línea {line_number}: código fuera de catálogo: {code}.")
        elif ANIMALS[code] != animal:
            warnings.append(f"Línea {line_number}: {code} corresponde a {ANIMALS[code]}, no {animal}.")
        else:
            draw_time = _time_24_hour(time_match.group(1), time_match.group(2), time_match.group(3))
            key = (current_date, draw_time, code, animal)
            records[key] = {
                "fecha": current_date,
                "hora": draw_time,
                "codigo": code,
                "animal": animal,
            }
        pending_result = None

    return sorted(records.values(), key=lambda row: (row["fecha"], row["hora"])), warnings


def write_clean_csv(records: list[dict[str, str]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=["fecha", "hora", "codigo", "animal"])
        writer.writeheader()
        writer.writerows(records)


def clean_file(input_path: str | Path, output_path: str | Path) -> tuple[int, list[str]]:
    records, warnings = parse_raw_text(Path(input_path).read_text(encoding="utf-8"))
    write_clean_csv(records, output_path)
    return len(records), warnings