"""
دوال مساعدة مشتركة: التحقق من الصلاحيات، حماية التسلسل الهرمي للرتب،
وحساب الرتب المتاحة للتعديل.
"""

import discord


def has_role(member: discord.Member, role_id) -> bool:
    if not role_id:
        return False
    return any(r.id == role_id for r in member.roles)


def is_owner(member: discord.Member) -> bool:
    return member.guild.owner_id == member.id


def can_target(actor: discord.Member, target: discord.Member):
    """
    حماية التسلسل الهرمي - تُستخدم بأوامر الباند والتايم.
    بترجع (True, "") إذا مسموح، أو (False, "سبب الرفض") إذا ممنوع.
    """
    if target.id == actor.id:
        return False, "ما فيك تستهدف نفسك."
    if target.bot:
        return False, "ما فيك تستهدف بوت."
    if is_owner(target):
        return False, "ما فيك تستهدف صاحب السيرفر."
    if actor.id == actor.guild.owner_id:
        return True, ""
    if target.top_role.position >= actor.top_role.position:
        return False, "هاد الشخص رتبته أعلى منك أو تساويك، ما فيك تستهدفه."
    return True, ""


# أي رتبة فيها واحدة من هاي الصلاحيات تُستثنى دايماً من $رتب، بغض النظر عن ترتيبها
DANGEROUS_PERMISSIONS = (
    "administrator",
    "ban_members",
    "kick_members",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
)


def _is_dangerous(role: discord.Role) -> bool:
    perms = role.permissions
    return any(getattr(perms, p, False) for p in DANGEROUS_PERMISSIONS)


def assignable_roles(actor: discord.Member, guild: discord.Guild):
    """
    الرتب يلي actor يقدر يتحكم فيها بأمر $رتب:
    - لازم تكون تحت أعلى رتبة عند actor (إلا إذا كان actor هو الأونر)
    - تُستثنى رتب البوتات (managed)
    - تُستثنى أي رتبة فيها صلاحية خطيرة (شوف DANGEROUS_PERMISSIONS)
    - تُستثنى الرتب يلي البوت نفسه ما يقدر يتحكم فيها (أعلى أو تساوي رتبة البوت)
    """
    bot_top_position = guild.me.top_role.position
    actor_is_owner = actor.id == guild.owner_id
    actor_position = actor.top_role.position

    roles = []
    for role in guild.roles:
        if role.is_default():
            continue
        if role.managed:
            # هاي رتب البوتات (الرتبة التلقائية يلي ديسكورد بيعملها لكل بوت) - مخفية دايماً
            continue
        if _is_dangerous(role):
            continue
        if not actor_is_owner and role.position >= actor_position:
            continue
        if role.position >= bot_top_position:
            continue
        roles.append(role)

    roles.sort(key=lambda r: r.position, reverse=True)
    return roles


def full_role_ladder(guild: discord.Guild):
    """
    كل الرتب "العادية" بالسيرفر مرتبة تصاعدياً (سلّم الترقية/التخفيض).
    نفس منطق استثناء assignable_roles (بدون تقييد بموقع شخص معين):
    - تُستثنى @everyone
    - تُستثنى رتب البوتات (managed)
    - تُستثنى أي رتبة فيها صلاحية خطيرة
    - تُستثنى الرتب يلي البوت نفسه ما يقدر يتحكم فيها
    """
    bot_top_position = guild.me.top_role.position
    roles = []
    for role in guild.roles:
        if role.is_default():
            continue
        if role.managed:
            continue
        if _is_dangerous(role):
            continue
        if role.position >= bot_top_position:
            continue
        roles.append(role)
    roles.sort(key=lambda r: r.position)
    return roles


def member_rank(member: discord.Member, ladder) -> int:
    """رقم رتبة الشخص الحالي بالسلّم (0 لو ما عنده أي رتبة من السلّم)."""
    ladder_index = {r.id: i + 1 for i, r in enumerate(ladder)}
    ranks = [ladder_index[r.id] for r in member.roles if r.id in ladder_index]
    return max(ranks) if ranks else 0


def actor_max_rank(actor: discord.Member, ladder) -> int:
    """أقصى رتبة يقدر actor يوصل غيره إلها بأمري الترقية/التخفيض."""
    if actor.id == actor.guild.owner_id:
        return len(ladder)
    rank = member_rank(actor, ladder)
    if rank > 0:
        return rank
    if not ladder:
        return 0
    # actor فوق السلم بالكامل (رتبة خطيرة/إدارية أعلى من كل السلّم)
    if actor.top_role.position > ladder[-1].position:
        return len(ladder)
    return 0


def bot_missing_permissions(guild: discord.Guild, *perms: str):
    """
    بيرجع لستة بأسماء الصلاحيات (زي 'manage_roles') يلي البوت ناقصها بالسيرفر.
    لو اللستة رجعت فاضية معناها البوت معه كل الصلاحيات المطلوبة.
    """
    bot_perms = guild.me.guild_permissions
    return [p for p in perms if not getattr(bot_perms, p, False)]
