"""
تحليل وقت نشر المهمة اللي بيكتبه المسؤول (بتوقيت فلسطين - بيتعامل تلقائياً مع التوقيت الصيفي/الشتوي).
"""

import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    PALESTINE_TZ = ZoneInfo("Asia/Hebron")
except Exception:  # احتياط لو zoneinfo مو متوفر لأي سبب
    PALESTINE_TZ = None

IMMEDIATE_WORDS = {"الآن", "الحين", "دلوقتي", "فوري", "فورا", "فوراً", "now"}

_RELATIVE_RE = re.compile(r"^بعد\s+(\d+)\s*(دقيقة|دقايق|دقائق|ساعة|ساعات|ساع)$")
_CLOCK_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(ص|صباحا|صباحاً|صباح|عصر|مساء|مساءً|م)?$")


def parse_quest_start_time(text: str):
    """
    بترجع (ok: bool, when_utc: datetime|None, error: str|None)
    when_utc=None معناها نشر فوري (لو ok=True).
    """
    t = (text or "").strip()
    if not t:
        return False, None, "لازم تكتب وقت. اكتب: الآن / 3 عصر / 10 صباحا / بعد ساعتين / بعد 30 دقيقة"

    if t in IMMEDIATE_WORDS:
        return True, None, None

    now_local = datetime.now(PALESTINE_TZ) if PALESTINE_TZ else datetime.now(timezone.utc)

    m = _RELATIVE_RE.match(t)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        delta = timedelta(minutes=amount) if "دقي" in unit else timedelta(hours=amount)
        target_local = now_local + delta
        return True, _to_utc(target_local), None

    m = _CLOCK_RE.match(t)
    if not m:
        return False, None, "ما قدرت أفهم الوقت. اكتب مثلاً: الآن / 3 عصر / 10 صباحا / 15:00 / بعد ساعتين"

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    marker = m.group(3)

    if marker in ("ص", "صباح", "صباحا", "صباحاً"):
        if hour == 12:
            hour = 0
    elif marker in ("عصر", "مساء", "مساءً", "م"):
        if hour != 12:
            hour += 12

    if hour > 23 or minute > 59:
        return False, None, "الوقت مو صحيح."

    candidate_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate_local <= now_local:
        candidate_local += timedelta(days=1)

    return True, _to_utc(candidate_local), None


def _to_utc(dt_local: datetime) -> datetime:
    if dt_local.tzinfo is None:
        return dt_local.replace(tzinfo=timezone.utc)
    return dt_local.astimezone(timezone.utc)
