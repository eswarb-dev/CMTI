from __future__ import annotations

from datetime import timedelta

from .config import START


CASE_WINDOWS = {
    "CASE-001": (START + timedelta(days=0), START + timedelta(days=29, hours=23)),
    "CASE-002": (START + timedelta(days=31), START + timedelta(days=36, hours=23)),
    "CASE-003": (START + timedelta(days=9), START + timedelta(days=18, hours=23)),
    "CASE-004": (START + timedelta(days=38), START + timedelta(days=43, hours=23)),
    "CASE-005": (START + timedelta(days=22), START + timedelta(days=34, hours=23)),
}


def in_window(timestamp, case_id: str) -> bool:
    start, end = CASE_WINDOWS[case_id]
    return start <= timestamp <= end


def case001_vibration_multiplier(timestamp) -> float:
    day = (timestamp.date() - START.date()).days + 1
    if day <= 10:
        return 1.0
    if day <= 15:
        return 1.25
    if day <= 20:
        return 1.65
    if day <= 25:
        return 1.95
    if day <= 29:
        return 2.25
    return 1.0


def case003_temperature_add(timestamp) -> float:
    day = (timestamp.date() - START.date()).days + 1
    if 10 <= day <= 18:
        return (day - 9) * 1.25
    return 0.0

