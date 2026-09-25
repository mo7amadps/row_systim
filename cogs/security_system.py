import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.embeds import branded_embed
from utils.checks import has_any_role, collect_roles

# الصلاحيات الخطيرة يلي أي رتبة توضافلها بدون تصريح بتعتبر محاولة تصعيد
DANGEROUS_PERMS = ("administrator", "manage_guild", "manage_roles")
PERM_LABELS = {
    "administrator": "أدمن (Administrator)",
    "manage_guild": "إدارة السيرفر (Manage Server)",
    "manage_roles": "إدارة الرتب (Manage Roles)",
}

# الإجراءات الخطيرة يلي بتنحسب بنظام العتبة (Rate Limit)
RATE_LIMIT_ACTIONS = {
    discord.AuditLogAction.ban,
    discord.AuditLogAction.kick,
    discord.AuditLogAction.channel_delete,
    discord.AuditLogAction.role_delete,
}


class SecuritySystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._known_webhooks: dict[int, set[int]] = {}
        self._known_webhooks_ready = False
        self._action_timestamps: dict[tuple, list] = {}  # (guild_id, executor_id) -> [monotonic timestamps]

    async def _populate_known_webhooks(self, guild: discord.Guild):
        """يعمل بيسلاين لكل الويب هوكس الموجودة أصلاً بالسيرفر، حتى ما ينعتبروا 'جداد' غلط."""
        for channel in guild.text_channels:
            try:
                webhooks = await channel.webhooks()
            except discord.Forbidden:
                continue
            self._known_webhooks[channel.id] = {w.id for w in webhooks}

    @commands.Cog.listener()
    async def on_ready(self):
        if self._known_webhooks_ready:
            return
        for guild in self.bot.guilds:
            await self._populate_known_webhooks(guild)
        self._known_webhooks_ready = True

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._populate_known_webhooks(guild)

    # ---------------- أدوات مساعدة مشتركة ----------------

    async def send_log(self, guild: discord.Guild, subsection: str, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["security"][subsection].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="🛡️ سجل حماية", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    async def notify_role(self, guild: discord.Guild, subsection: str, text: str):
        conf = await Storage.get_guild(guild.id)
        role_id = conf["security"][subsection].get("notify_role_id")
        if not role_id:
            return
        role = guild.get_role(role_id)
        if not role:
            return
        embed = branded_embed(title="🚨 تنبيه حماية", description=text, color=discord.Color.red())
        for member in role.members:
            try:
                await member.send(embed=embed)
            except discord.Forbidden:
                pass

    async def punish(self, guild: discord.Guild, member: discord.Member, subsection: str):
        """يشيل كل رتب الشخص ويعطيه رتبة السجن"""
        conf = await Storage.get_guild(guild.id)
        jail_role_id = conf["security"][subsection].get("jail_role_id")
        jail_role = guild.get_role(jail_role_id) if jail_role_id else None

        roles_to_remove = [r for r in member.roles if not r.is_default() and not r.managed]
        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="حماية: إجراء غير مصرح فيه")
            if jail_role:
                await member.add_roles(jail_role, reason="حماية: تفعيل رتبة السجن")
        except discord.Forbidden:
            pass

    def _is_exempt(self, guild: discord.Guild, executor, subsection: str, conf: dict) -> bool:
        if executor is None:
            return False
        if executor.id == guild.owner_id:
            return True
        if executor.id == guild.me.id:
            return True
        allowed_role_ids = conf["security"][subsection].get("allowed_role_ids")
        member = guild.get_member(executor.id)
        if member is None:
            return False
        return has_any_role(member, allowed_role_ids)

    # ---------------- 1) حماية إضافة البوتات ----------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            return
        guild = member.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["bot_add"]
        if not any(sec.values()):
            return  # النظام ما تم إعداده لهاد السيرفر

        await asyncio.sleep(2)  # نعطي وقت لديسكورد يسجل حدث الـ Audit Log

        executor = None
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                if entry.target and entry.target.id == member.id:
                    executor = entry.user
                    break
        except discord.Forbidden:
            pass

        if self._is_exempt(guild, executor, "bot_add", conf):
            return

        try:
            await guild.kick(member, reason="حماية: بوت غير مصرح بإضافته")
        except discord.Forbidden:
            pass

        if executor:
            executor_member = guild.get_member(executor.id)
            if executor_member:
                await self.punish(guild, executor_member, "bot_add")

        await self.send_log(guild, "bot_add", {
            "العملية": "🤖 إضافة بوت غير مصرح",
            "البوت": f"{member} ({member.id})",
            "بواسطة": executor.mention if executor else "غير معروف",
        })
        await self.notify_role(
            guild, "bot_add",
            f"تم إحباط محاولة إضافة بوت غير مصرح: **{member}**"
            + (f" بواسطة {executor.mention}" if executor else ""),
        )

    # ---------------- 2) حماية Prune ----------------

    async def _handle_prune_audit(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["prune"]
        if not any(sec.values()):
            return

        executor = entry.user
        if self._is_exempt(guild, executor, "prune", conf):
            return

        if executor:
            executor_member = guild.get_member(executor.id)
            if executor_member:
                await self.punish(guild, executor_member, "prune")

        await self.send_log(guild, "prune", {
            "العملية": "🧹 محاولة Prune غير مصرح",
            "بواسطة": executor.mention if executor else "غير معروف",
        })
        await self.notify_role(
            guild, "prune",
            "تم إحباط محاولة Prune" + (f" من طرف {executor.mention}" if executor else ""),
        )

    # ---------------- 4) حماية القنوات (إنشاء / حذف) ----------------

    async def _handle_channel_audit(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["channels"]
        if not any(sec.values()):
            return

        executor = entry.user
        if executor and executor.id == guild.me.id:
            return
        if self._is_exempt(guild, executor, "channels", conf):
            return

        action_name = "➕ إنشاء قناة" if entry.action == discord.AuditLogAction.channel_create else "🗑️ حذف قناة"

        if entry.action == discord.AuditLogAction.channel_create:
            channel = guild.get_channel(entry.target.id) if entry.target else None
            if channel:
                try:
                    await channel.delete(reason="حماية: إنشاء قناة غير مصرح")
                except discord.Forbidden:
                    pass

        if executor:
            executor_member = guild.get_member(executor.id)
            if executor_member:
                await self.punish(guild, executor_member, "channels")

        await self.send_log(guild, "channels", {
            "العملية": f"{action_name} غير مصرح",
            "القناة": str(entry.target) if entry.target else "غير معروفة",
            "بواسطة": executor.mention if executor else "غير معروف",
        })
        await self.notify_role(
            guild, "channels",
            f"تم إحباط محاولة {action_name}" + (f" من طرف {executor.mention}" if executor else ""),
        )

    # ---------------- 5) حماية الرتب (حذف / تعديل) ----------------

    async def _handle_role_audit(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["roles"]
        if not any(sec.values()):
            return

        executor = entry.user
        # ما نعاقب البوت نفسه على تعديلاته العادية (زي رتب)
        if executor and executor.id == guild.me.id:
            return
        if self._is_exempt(guild, executor, "roles", conf):
            return

        action_name = "🗑️ حذف رتبة" if entry.action == discord.AuditLogAction.role_delete else "✏️ تعديل رتبة"

        if executor:
            executor_member = guild.get_member(executor.id)
            if executor_member:
                await self.punish(guild, executor_member, "roles")

        await self.send_log(guild, "roles", {
            "العملية": f"{action_name} غير مصرح",
            "الرتبة": str(entry.target) if entry.target else "غير معروفة",
            "بواسطة": executor.mention if executor else "غير معروف",
        })
        await self.notify_role(
            guild, "roles",
            f"تم إحباط محاولة {action_name}" + (f" من طرف {executor.mention}" if executor else ""),
        )

    # ---------------- 6) حماية تصعيد الصلاحيات ----------------

    async def _handle_permission_escalation_update(self, entry: discord.AuditLogEntry):
        """حالة: رتبة موجودة أصلاً واتعدّلت وضافولها صلاحية خطيرة."""
        guild = entry.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["permission_escalation"]
        if not sec.get("log_channel_id") and not sec.get("notify_role_id") and not sec.get("allowed_role_ids"):
            return  # النظام ما تم إعداده لهاد السيرفر

        before_perms = getattr(entry.before, "permissions", None)
        after_perms = getattr(entry.after, "permissions", None)
        if before_perms is None or after_perms is None:
            return  # التعديل ما لمس الصلاحيات إطلاقاً (لون، اسم، ترتيب...)

        newly_dangerous = [
            p for p in DANGEROUS_PERMS
            if getattr(after_perms, p, False) and not getattr(before_perms, p, False)
        ]
        if not newly_dangerous:
            return

        executor = entry.user
        if executor and executor.id == guild.me.id:
            return
        if self._is_exempt(guild, executor, "permission_escalation", conf):
            return

        role = guild.get_role(entry.target.id) if entry.target else None

        # رجوع فوري: نرجّع صلاحيات الرتبة متل ما كانت قبل التعديل
        if role:
            try:
                await role.edit(permissions=before_perms, reason="حماية: تراجع فوري عن تصعيد صلاحيات غير مصرح")
            except (discord.Forbidden, discord.HTTPException):
                pass

        await self._punish_permission_escalation(
            guild, executor, role, newly_dangerous,
            log_action="🚨 محاولة تصعيد صلاحيات (تعديل رتبة موجودة)",
            revert_note="رجوع الصلاحيات",
        )

    async def _handle_permission_escalation_create(self, entry: discord.AuditLogEntry):
        """حالة: رتبة جديدة اتنشأت وفيها صلاحية خطيرة من أول لحظة."""
        guild = entry.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["permission_escalation"]
        if not sec.get("log_channel_id") and not sec.get("notify_role_id") and not sec.get("allowed_role_ids"):
            return

        role = guild.get_role(entry.target.id) if entry.target else None
        if not role:
            return

        dangerous = [p for p in DANGEROUS_PERMS if getattr(role.permissions, p, False)]
        if not dangerous:
            return

        executor = entry.user
        if executor and executor.id == guild.me.id:
            return
        if self._is_exempt(guild, executor, "permission_escalation", conf):
            return

        # رجوع فوري: منخلي الرتبة موجودة بس منشيل منها الصلاحيات الخطيرة بس (منسيبها لباقي صلاحياتها متل ما هي)
        safe_perms = role.permissions
        for p in dangerous:
            setattr(safe_perms, p, False)
        try:
            await role.edit(permissions=safe_perms, reason="حماية: تراجع فوري عن إنشاء رتبة بصلاحيات خطيرة")
        except (discord.Forbidden, discord.HTTPException):
            pass

        await self._punish_permission_escalation(
            guild, executor, role, dangerous,
            log_action="🚨 إنشاء رتبة جديدة بصلاحيات خطيرة",
            revert_note="شيل الصلاحيات من الرتبة (الرتبة نفسها بقيت)",
        )

    async def _punish_permission_escalation(self, guild, executor, role, perms_list, log_action, revert_note):
        """عقاب موحّد لحالتي التعديل والإنشاء: بان مباشر بسبب واضح."""
        if executor:
            executor_member = guild.get_member(executor.id)
            if executor_member:
                try:
                    await guild.ban(
                        executor_member,
                        reason="🚫 محاولة غدر - تصعيد صلاحيات غير مصرح",
                        delete_message_seconds=0,
                    )
                except discord.Forbidden:
                    pass

        perms_txt = "، ".join(PERM_LABELS.get(p, p) for p in perms_list)
        await self.send_log(guild, "permission_escalation", {
            "العملية": log_action,
            "الرتبة": role.mention if role else "؟",
            "الصلاحيات": perms_txt,
            "بواسطة": executor.mention if executor else "غير معروف",
            "الإجراء": f"🔨 تم بان الفاعل + {revert_note}" if executor else f"🔨 {revert_note} (الفاعل غير معروف)",
        })
        await self.notify_role(
            guild, "permission_escalation",
            f"🚨 محاولة غدر: صلاحيات ({perms_txt}) على رتبة {role.mention if role else '؟'}"
            + (f" - تم بان {executor.mention}" if executor else ""),
        )

    # ---------------- 7) حماية إعدادات السيرفر ----------------

    async def _handle_guild_update_audit(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["guild_update"]
        if not sec.get("log_channel_id") and not sec.get("notify_role_id") and not sec.get("allowed_role_ids"):
            return

        changes = []
        revert_kwargs = {}

        before_name = getattr(entry.before, "name", None)
        after_name = getattr(entry.after, "name", None)
        if before_name is not None and after_name is not None and before_name != after_name:
            changes.append(f"📛 الاسم: `{before_name}` ← `{after_name}`")
            revert_kwargs["name"] = before_name

        before_icon = getattr(entry.before, "icon", None)
        after_icon = getattr(entry.after, "icon", None)
        if before_icon != after_icon:
            if before_icon is not None:
                try:
                    revert_kwargs["icon"] = await before_icon.read()
                    changes.append("🖼️ الأيقونة اتغيّرت")
                except (discord.HTTPException, discord.NotFound):
                    pass
            elif after_icon is not None:
                revert_kwargs["icon"] = None
                changes.append("🖼️ الأيقونة اتضافت")

        before_vanity = getattr(entry.before, "vanity_url_code", None)
        after_vanity = getattr(entry.after, "vanity_url_code", None)
        if before_vanity is not None and after_vanity is not None and before_vanity != after_vanity:
            changes.append(f"🔗 رابط Vanity: `{before_vanity}` ← `{after_vanity}`")
            # ما منقدر نرجع الفانيتي أوتوماتيك عبر الـ API، بس منلوق ونعاقب

        before_verif = getattr(entry.before, "verification_level", None)
        after_verif = getattr(entry.after, "verification_level", None)
        if before_verif is not None and after_verif is not None and after_verif.value < before_verif.value:
            changes.append(f"🔓 مستوى التحقق نزل: {before_verif} ← {after_verif}")
            revert_kwargs["verification_level"] = before_verif

        before_filter = getattr(entry.before, "explicit_content_filter", None)
        after_filter = getattr(entry.after, "explicit_content_filter", None)
        if before_filter is not None and after_filter is not None and after_filter.value < before_filter.value:
            changes.append(f"🔓 فلتر المحتوى الإباحي نزل: {before_filter} ← {after_filter}")
            revert_kwargs["explicit_content_filter"] = before_filter

        if not changes:
            return

        executor = entry.user
        if executor and executor.id == guild.me.id:
            return
        if self._is_exempt(guild, executor, "guild_update", conf):
            return

        if revert_kwargs:
            try:
                await guild.edit(reason="حماية: تراجع عن تعديل إعدادات سيرفر غير مصرح", **revert_kwargs)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if executor:
            executor_member = guild.get_member(executor.id)
            if executor_member:
                try:
                    await executor_member.kick(reason="⚠️ تعديل إعدادات السيرفر بدون تصريح")
                except discord.Forbidden:
                    pass

        changes_txt = "\n".join(changes)
        await self.send_log(guild, "guild_update", {
            "العملية": "🚨 تعديل إعدادات سيرفر غير مصرح",
            "التغييرات": changes_txt,
            "بواسطة": executor.mention if executor else "غير معروف",
            "الإجراء": "🔨 تم طرده + رجوع الإعدادات (لو أمكن)" if executor else "رجوع الإعدادات (لو أمكن)",
        })
        await self.notify_role(
            guild, "guild_update",
            f"🚨 تم إحباط تعديل إعدادات سيرفر غير مصرح:\n{changes_txt}"
            + (f"\n- تم طرد {executor.mention}" if executor else ""),
        )

    # ---------------- 8) نظام العتبة (Rate Limit) للإجراءات الخطيرة ----------------

    async def _handle_rate_limit_audit(self, entry: discord.AuditLogEntry):
        if entry.action not in RATE_LIMIT_ACTIONS:
            return

        guild = entry.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["rate_limit"]
        if not sec.get("log_channel_id") and not sec.get("jail_role_id"):
            return  # النظام ما تم إعداده

        executor = entry.user
        if executor is None:
            return
        if executor.id == guild.owner_id or executor.id == guild.me.id:
            return
        if self._is_exempt(guild, executor, "rate_limit", conf):
            return

        key = (guild.id, executor.id)
        now = time.monotonic()
        timestamps = self._action_timestamps.setdefault(key, [])
        timestamps.append(now)

        threshold_seconds = sec.get("threshold_seconds") or 15
        threshold_count = sec.get("threshold_count") or 5
        cutoff = now - threshold_seconds
        timestamps[:] = [t for t in timestamps if t >= cutoff]

        if len(timestamps) < threshold_count:
            return

        timestamps.clear()  # نصفّرها حتى ما يتكرر العقاب مع كل إجراء جاي بعد الحجر

        executor_member = guild.get_member(executor.id)
        if executor_member:
            await self.punish(guild, executor_member, "rate_limit")

        await self.send_log(guild, "rate_limit", {
            "العملية": "🚨 تجاوز حد الإجراءات الخطيرة (احتمال اختراق حساب)",
            "الحساب": executor.mention,
            "آخر إجراء": str(entry.action),
            "العتبة": f"{threshold_count} إجراءات خلال {threshold_seconds} ثانية",
        })
        await self.notify_role(
            guild, "rate_limit",
            f"🚨 تم حجر {executor.mention} تلقائياً - سوى إجراءات خطيرة كتيرة (باند/كيك/حذف) بوقت قصير جداً، "
            "احتمال كبير حسابه مخترق.",
        )

    # ---------------- نقطة استقبال موحّدة لكل أحداث الـ Audit Log ----------------

    @commands.Cog.listener("on_audit_log_entry_create")
    async def on_any_audit_log_entry(self, entry: discord.AuditLogEntry):
        await self._handle_rate_limit_audit(entry)

        if entry.action == discord.AuditLogAction.member_prune:
            await self._handle_prune_audit(entry)
        elif entry.action in (discord.AuditLogAction.channel_create, discord.AuditLogAction.channel_delete):
            await self._handle_channel_audit(entry)
        elif entry.action == discord.AuditLogAction.role_update:
            await self._handle_role_audit(entry)
            await self._handle_permission_escalation_update(entry)
        elif entry.action == discord.AuditLogAction.role_create:
            await self._handle_permission_escalation_create(entry)
        elif entry.action == discord.AuditLogAction.role_delete:
            await self._handle_role_audit(entry)
        elif entry.action == discord.AuditLogAction.guild_update:
            await self._handle_guild_update_audit(entry)

    # ---------------- 3) حماية Webhook ----------------

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        if not self._known_webhooks_ready:
            return  # لسا ما اخدنا بيسلاين البداية، تجنباً لبلاغ كاذب عن ويب هوكس موجودة أصلاً
        guild = channel.guild
        conf = await Storage.get_guild(guild.id)
        sec = conf["security"]["webhook"]
        if not any(sec.values()):
            return

        try:
            current_webhooks = await channel.webhooks()
        except discord.Forbidden:
            return

        known = self._known_webhooks.get(channel.id, set())
        current_ids = {w.id for w in current_webhooks}
        new_ids = current_ids - known
        self._known_webhooks[channel.id] = current_ids

        if not new_ids:
            return  # ما في ويب هوك جديد (ممكن انحذف واحد، أو أول تحميل للبوت)

        executor = None
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.webhook_create):
                if entry.target and entry.target.id in new_ids:
                    executor = entry.user
                    break
        except discord.Forbidden:
            pass

        if self._is_exempt(guild, executor, "webhook", conf):
            return

        for w in current_webhooks:
            if w.id in new_ids:
                try:
                    await w.delete(reason="حماية: ويب هوك غير مصرح")
                except discord.Forbidden:
                    pass

        if executor:
            executor_member = guild.get_member(executor.id)
            if executor_member:
                await self.punish(guild, executor_member, "webhook")

        await self.send_log(guild, "webhook", {
            "العملية": "🔗 إنشاء ويب هوك غير مصرح",
            "بواسطة": executor.mention if executor else "غير معروف",
        })
        await self.notify_role(
            guild, "webhook",
            "تم إحباط محاولة إنشاء ويب هوك" + (f" من طرف {executor.mention}" if executor else ""),
        )

    # ---------------- /set-up-security (Group) ----------------

    security_group = app_commands.Group(name="set-up-security", description="إعداد نظام الحماية")

    @security_group.command(name="bot-add", description="إعداد حماية إضافة البوتات")
    @app_commands.describe(
        allowed_role_1="مين يقدر يضيف بوتات بدون ما ينطرد البوت (أول رتبة)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_bot_add(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "bot_add", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية إضافة البوتات", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="prune", description="إعداد حماية Prune")
    @app_commands.describe(
        allowed_role_1="مين يقدر يسوي Prune بدون عقاب (أول رتبة)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_prune(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "prune", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية Prune", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="webhook", description="إعداد حماية الويب هوك")
    @app_commands.describe(
        allowed_role_1="مين يقدر يسوي ويب هوك بدون ما ينحذف (أول رتبة)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_webhook(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "webhook", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية الويب هوك", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="channels", description="إعداد حماية إنشاء/حذف القنوات")
    @app_commands.describe(
        allowed_role_1="مين يقدر ينشئ/يحذف قنوات بدون عقاب (أول رتبة)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_channels(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "channels", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية القنوات", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="roles", description="إعداد حماية حذف/تعديل الرتب")
    @app_commands.describe(
        allowed_role_1="مين يقدر يحذف/يعدل رتب بدون عقاب (أول رتبة)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_roles(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "roles", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية الرتب", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="perm-escalation", description="إعداد حماية تصعيد الصلاحيات (Administrator/Manage Server/Manage Roles)")
    @app_commands.describe(
        allowed_role_1="مين يقدر يضيف صلاحيات خطيرة لرتبة بدون ما ينبان (أول رتبة موثوقة)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_perm_escalation(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "permission_escalation", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية تصعيد الصلاحيات", color=discord.Color.green())
        embed.add_field(name="الرتب المستثناة", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=True)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention, inline=True)
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value="أي رتبة (موجودة اتعدلت، أو جديدة اتنشأت) صار فيها Administrator أو Manage Server أو Manage Roles "
                  "من حدا مو من الرتب المستثناة: بترجع الصلاحيات فوراً (أو تنشال بس من الرتبة لو كانت جديدة)، "
                  "وينبان الفاعل تلقائياً.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="guild-update", description="إعداد حماية إعدادات السيرفر (الاسم/الأيقونة/الفانيتي/التحقق/فلتر المحتوى)")
    @app_commands.describe(
        allowed_role_1="مين يقدر يغير إعدادات السيرفر بدون ما ينطرد (أول رتبة موثوقة)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_guild_update(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "guild_update", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية إعدادات السيرفر", color=discord.Color.green())
        embed.add_field(name="الرتب المستثناة", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=True)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention, inline=True)
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value="أي تغيير باسم/أيقونة/فانيتي السيرفر، أو تنزيل بمستوى التحقق أو فلتر المحتوى الإباحي، من حدا مو مستثنى، "
                  "رح يترجع (لو ممكن تقنياً) ويتطرد الفاعل تلقائياً.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="rate-limit", description="إعداد حد الإجراءات الخطيرة (باند/كيك/حذف) بوقت قصير")
    @app_commands.describe(
        allowed_role_1="رتبة مستثناة تماماً من هاد الحد (أول رتبة، متل الأونر)",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن يلي بتنحط للحساب المشتبه فيه",
        threshold_count="كم إجراء خطير (باند/كيك/حذف روم/حذف رتبة) يفعّل الحماية (افتراضي 5)",
        threshold_seconds="خلال كم ثانية (افتراضي 15)",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_rate_limit(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
        threshold_count: app_commands.Range[int, 2, 50] = 5,
        threshold_seconds: app_commands.Range[int, 5, 300] = 15,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_security(interaction.guild.id, "rate_limit", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
            "threshold_count": threshold_count,
            "threshold_seconds": threshold_seconds,
        })
        embed = branded_embed(title="✅ تم إعداد حد الإجراءات الخطيرة", color=discord.Color.green())
        embed.add_field(name="الرتب المستثناة تماماً", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=True)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention, inline=True)
        embed.add_field(name="رتبة السجن", value=jail_role.mention, inline=True)
        embed.add_field(name="العتبة", value=f"{threshold_count} إجراءات خلال {threshold_seconds} ثانية", inline=False)
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value="بيراقب الباند/الكيك/حذف الرومات/حذف الرتب لكل شخص. حتى لو كان من رتبة مسموحة تستخدم "
                  "هاي الأوامر أصلاً، لو تجاوز العتبة بوقت قصير بينحجر تلقائياً (احتياط من حساب مخترق).",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(SecuritySystem(bot))
