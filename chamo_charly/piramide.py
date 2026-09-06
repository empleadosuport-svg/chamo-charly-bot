"""Experimental date/time pyramid signal, isolated from production prediction."""

from __future__ import annotations

from collections import Counter
from datetime import date, time

from chamo_charly.catalog import ANIMALS


MAX_CODE = 37
DEFAULT_LIMIT = 10


def _reduce_to_two_digits(value: int) -> int:
    while value >= 100:
        value = sum(int(digit) for digit in str(value))
    return value


def pyramid_rows(digits: str) -> list[list[int]]:
    """Build adjacent-sum rows from the input digits through the single apex."""
    rows = [[int(digit) for digit in digits]]
    while len(rows[-1]) > 1:
        previous = rows[-1]
        rows.append([left + right for left, right in zip(previous, previous[1:])])
    return rows


def pyramid_signal(digits: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Return the most frequent valid animal codes from every pyramid row.

    Frequencies are compared descending; ties preserve first left-to-right
    appearance while scanning rows from the input row to the apex.
    """
    if not digits or not digits.isdecimal():
        raise ValueError("La entrada debe contener únicamente dígitos.")
    if limit < 1:
        raise ValueError("El límite debe ser positivo.")

    counts: Counter[int] = Counter()
    first_seen: dict[int, int] = {}
    appearance = 0
    for row in pyramid_rows(digits):
        for value in row:
            reduced = _reduce_to_two_digits(value)
            if reduced <= MAX_CODE:
                counts[reduced] += 1
                first_seen.setdefault(reduced, appearance)
            appearance += 1

    ordered = sorted(
        (value for value in counts if f"{value:02d}" in ANIMALS),
        key=lambda value: (-counts[value], first_seen[value]),
    )
    return [f"{code:02d}" for code in ordered[:limit]]


def pyramid_scores(digits: str) -> dict[str, float]:
    """Return normalized valid-code frequencies for experimental evaluation."""
    if not digits or not digits.isdecimal():
        raise ValueError("La entrada debe contener únicamente dígitos.")

    counts: Counter[int] = Counter()
    for row in pyramid_rows(digits):
        for value in row:
            reduced = _reduce_to_two_digits(value)
            if reduced <= MAX_CODE and f"{reduced:02d}" in ANIMALS:
                counts[reduced] += 1
    total = sum(counts.values())
    return {
        code: counts.get(int(code), 0) / total if total else 0.0
        for code in ANIMALS
    }


def pyramid_signal_for_target(target_date: date, target_time: time, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Generate the experimental signal for a target draw slot."""
    digits = target_date.strftime("%d%m%Y") + target_time.strftime("%H%M")
    return pyramid_signal(digits, limit=limit)


__all__ = ["pyramid_rows", "pyramid_scores", "pyramid_signal", "pyramid_signal_for_target"]
