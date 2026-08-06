import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.embeds import branded_embed
from utils.checks import has_role


class SecuritySystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._known_webhooks: dict[int, set[int]] = {}

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
        allowed_role_id = conf["security"][subsection].get("allowed_role_id")
        member = guild.get_member(executor.id)
        if member is None:
            return False
        return has_role(member, allowed_role_id)

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
        # ما نعاقب البوت نفسه على تعديلاته العادية (زي $رتب)
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

    # ---------------- نقطة استقبال موحّدة لكل أحداث الـ Audit Log ----------------

    @commands.Cog.listener("on_audit_log_entry_create")
    async def on_any_audit_log_entry(self, entry: discord.AuditLogEntry):
        if entry.action == discord.AuditLogAction.member_prune:
            await self._handle_prune_audit(entry)
        elif entry.action in (discord.AuditLogAction.channel_create, discord.AuditLogAction.channel_delete):
            await self._handle_channel_audit(entry)
        elif entry.action in (discord.AuditLogAction.role_delete, discord.AuditLogAction.role_update):
            await self._handle_role_audit(entry)

    # ---------------- 3) حماية Webhook ----------------

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
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
        allowed_role="مين يقدر يضيف بوتات بدون ما ينطرد البوت",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_bot_add(
        self,
        interaction: discord.Interaction,
        allowed_role: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
    ):
        await Storage.update_security(interaction.guild.id, "bot_add", {
            "allowed_role_id": allowed_role.id,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية إضافة البوتات", color=discord.Color.green())
        embed.add_field(name="مين مسموح", value=allowed_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="prune", description="إعداد حماية Prune")
    @app_commands.describe(
        allowed_role="مين يقدر يسوي Prune بدون عقاب",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_prune(
        self,
        interaction: discord.Interaction,
        allowed_role: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
    ):
        await Storage.update_security(interaction.guild.id, "prune", {
            "allowed_role_id": allowed_role.id,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية Prune", color=discord.Color.green())
        embed.add_field(name="مين مسموح", value=allowed_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="webhook", description="إعداد حماية الويب هوك")
    @app_commands.describe(
        allowed_role="مين يقدر يسوي ويب هوك بدون ما ينحذف",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_webhook(
        self,
        interaction: discord.Interaction,
        allowed_role: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
    ):
        await Storage.update_security(interaction.guild.id, "webhook", {
            "allowed_role_id": allowed_role.id,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية الويب هوك", color=discord.Color.green())
        embed.add_field(name="مين مسموح", value=allowed_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="channels", description="إعداد حماية إنشاء/حذف القنوات")
    @app_commands.describe(
        allowed_role="مين يقدر ينشئ/يحذف قنوات بدون عقاب",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_channels(
        self,
        interaction: discord.Interaction,
        allowed_role: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
    ):
        await Storage.update_security(interaction.guild.id, "channels", {
            "allowed_role_id": allowed_role.id,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية القنوات", color=discord.Color.green())
        embed.add_field(name="مين مسموح", value=allowed_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security_group.command(name="roles", description="إعداد حماية حذف/تعديل الرتب")
    @app_commands.describe(
        allowed_role="مين يقدر يحذف/يعدل رتب بدون عقاب",
        log_channel="قناة اللوق",
        notify_role="رتبة تتلقى إشعار خاص عند إحباط محاولة",
        jail_role="رتبة السجن",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_roles(
        self,
        interaction: discord.Interaction,
        allowed_role: discord.Role,
        log_channel: discord.TextChannel,
        notify_role: discord.Role,
        jail_role: discord.Role,
    ):
        await Storage.update_security(interaction.guild.id, "roles", {
            "allowed_role_id": allowed_role.id,
            "log_channel_id": log_channel.id,
            "notify_role_id": notify_role.id,
            "jail_role_id": jail_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد حماية الرتب", color=discord.Color.green())
        embed.add_field(name="مين مسموح", value=allowed_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="رتبة الإشعار", value=notify_role.mention)
        embed.add_field(name="رتبة السجن", value=jail_role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SecuritySystem(bot))
