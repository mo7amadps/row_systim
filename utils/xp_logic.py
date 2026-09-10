"""
حساب XP بسيط لكل رسالة - أي رسالة حقيقية (مش سبام/فاضية) = XP عشوائي بحدود يحددها الأدمن.
"""

import random


def is_valid_for_xp(content: str, attachment_count: int = 0) -> bool:
    text = (content or "").strip()

    if not text and attachment_count == 0:
        return False

    # سبام حرف واحد مكرر (زي "ككككككك" أو "؟؟؟؟؟؟؟") - ما تستاهل XP
    stripped = text.replace(" ", "")
    unique_chars = len(set(stripped))
    if stripped and unique_chars <= 1 and len(stripped) > 2:
        return False

    # رسالة قصيرة جداً (حرف أو حرفين بس) وبدون مرفق - غالباً رد آلي مو تفاعل حقيقي
    if len(text) < 2 and attachment_count == 0:
        return False

    return True


def roll_message_xp(xp_min: int, xp_max: int) -> int:
    return random.randint(xp_min, xp_max)

