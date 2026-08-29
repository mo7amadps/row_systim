"""
حساب XP "ذكي" لكل رسالة - مو رقم عشوائي، منطقي حسب فحوى الرسالة:
- رسالة فاضية/رمز واحد/تكرار حرف (سبام) = صفر XP.
- رسالة عادية قصيرة = 1 XP.
- رسالة فيها كام كلمة فعلية = 2 XP.
- رسالة طويلة ومفيدة = 3 XP.
- مرفق (صورة/ملف) = +1 XP إضافي.
- الحد الأقصى بالرسالة الواحدة محدود (مربوط بإعداد xp_max بالسيت اب) حتى ما حد يستغلها.
"""


def compute_message_xp(content: str, attachment_count: int = 0) -> int:
    text = (content or "").strip()

    if not text and attachment_count == 0:
        return 0

    # سبام حرف واحد مكرر (زي "ككككككك" أو "؟؟؟؟؟؟؟") - ما تستاهل XP
    stripped = text.replace(" ", "")
    unique_chars = len(set(stripped))
    if stripped and unique_chars <= 1 and len(stripped) > 2:
        return 0

    # رسالة قصيرة جداً (حرف أو حرفين بس) وبدون مرفق - غالباً رد آلي ("ok"، "لا") مو تفاعل حقيقي
    if len(text) < 2 and attachment_count == 0:
        return 0

    words = [w for w in text.split() if w]
    word_count = len(words)

    xp = 1  # أساس أي رسالة فيها محتوى حقيقي
    if word_count >= 5:
        xp += 1
    if word_count >= 15:
        xp += 1
    if attachment_count > 0:
        xp += 1

    return xp


def clamp_xp(amount: int, xp_min: int, xp_max: int) -> int:
    """بتحدد القيمة المحسوبة بين الحد الأدنى والأقصى المُعدين، إلا إذا كانت أصلاً صفر (سبام/فاضية)."""
    if amount <= 0:
        return 0
    return max(xp_min, min(amount, xp_max))
