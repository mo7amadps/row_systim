from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, bot_missing_permissions
from utils.embeds import branded_embed


class ChannelUtils(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, guild: discord.Guild, section: str, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf[section].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    async def _check_permission(self, ctx: commands.Context, section: str, setup_cmd: str) -> bool:
        conf = await Storage.get_guild(ctx.guild.id)
        s = conf[section]
        if not s["allowed_role_ids"]:
            await ctx.reply(f"❌ النظام ما تم إعداده لسا. استخدم `/{setup_cmd}` أول.")
            return False
        if not has_any_role(ctx.author, s["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return False
        return True

    @staticmethod
    async def _run_setup(interaction: discord.Interaction, section: str, title: str, command_label: str,
                          role_1: discord.Role, log_channel: discord.TextChannel,
                          role_2: discord.Role = None, role_3: discord.Role = None, role_4: discord.Role = None):
        role_ids = collect_roles(role_1, role_2, role_3, role_4)
        await Storage.update_guild(interaction.guild.id, section, {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title=f"✅ تم إعداد {title}", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="الأمر", value=f"`{command_label}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- /set-up-lock ----------------

    @app_commands.command(name="set-up-lock", description="إعداد أمر قفل القناة (ق)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم ق", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_lock(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_setup(interaction, "lock", "نظام ق", "ق",
                               allowed_role_1, log_channel, allowed_role_2, allowed_role_3, allowed_role_4)

    @set_up_lock.error
    async def set_up_lock_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return

    # ---------------- /set-up-unlock ----------------

    @app_commands.command(name="set-up-unlock", description="إعداد أمر فتح القناة (ف)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم ف", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_unlock(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_setup(interaction, "unlock", "نظام ف", "ف",
                               allowed_role_1, log_channel, allowed_role_2, allowed_role_3, allowed_role_4)

    @set_up_unlock.error
    async def set_up_unlock_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return

    # ---------------- /set-up-clear ----------------

    @app_commands.command(name="set-up-clear", description="إعداد أمر مسح الرسائل (مسح)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم مسح", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_clear(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_setup(interaction, "clear", "نظام مسح", "مسح",
                               allowed_role_1, log_channel, allowed_role_2, allowed_role_3, allowed_role_4)

    @set_up_clear.error
    async def set_up_clear_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return

    # ---------------- /set-up-clear-v2 (مسح شخص محدد) ----------------

    @app_commands.command(name="set-up-clear-v2", description="إعداد أمر مسح رسائل شخص محدد (مسح @شخص عدد)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم مسح شخص محدد",
        log_channel="قناة اللوق",
        max_amount="أقصى عدد رسائل يقدر يمسحها بالمرة الوحدة",
        protected_role="أي حدا رتبته بنفس موقع هاي الرتبة أو أعلى منها، رسائله محمية ما تنمسح",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_clear_v2(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        max_amount: app_commands.Range[int, 1, 100], protected_role: discord.Role,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "clear_v2", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "max_amount": max_amount,
            "protected_role_id": protected_role.id,
        })
        embed = branded_embed(title="✅ تم إعداد مسح شخص محدد", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=True)
        embed.add_field(name="أقصى عدد بالمرة", value=str(max_amount), inline=True)
        embed.add_field(name="الرتبة المحمية", value=protected_role.mention, inline=True)
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value=(
                "اكتب `مسح @الشخص 20` عشان تمسح آخر 20 رسالة لهاد الشخص بهاد الروم (بس يلي عمرها أقل من يوم).\n"
                f"أي شخص رتبته بنفس موقع {protected_role.mention} أو أعلى منها بالسيرفر، رسائله محمية ما تنمسح "
                "حتى لو ما معه هاي الرتبة بالضبط."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_clear_v2.error
    async def set_up_clear_v2_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return

    # ---------------- ق (قفل) ----------------

    @commands.command(name="ق")
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def lock_cmd(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if not await self._check_permission(ctx, "lock", "set-up-lock"):
            return
        channel = channel or ctx.channel

        missing = bot_missing_permissions(ctx.guild, "manage_channels")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            default_role = ctx.guild.default_role
            overwrite = channel.overwrites_for(default_role)
            # احتفظ بحالة الإخفاء الحالية. إذا كان الروم مخفياً فعلياً
            # بسبب صلاحيات الكاتيجوري، ثبّت الإخفاء على الروم أيضاً حتى
            # لا يظهر عند تعديل send_messages.
            was_hidden = not channel.permissions_for(default_role).view_channel
            overwrite.send_messages = False
            if was_hidden:
                overwrite.view_channel = False
            await channel.set_permissions(
                default_role,
                overwrite=overwrite,
                reason=f"قفل بواسطة {ctx.author}",
            )
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أقفل القناة، تأكد من صلاحيات البوت فيها.")
            return

        await ctx.reply("🔒 تم تسكير الروم.")
        await self.send_log(ctx.guild, "lock", {
            "العملية": "🔒 قفل قناة",
            "بواسطة": ctx.author.mention,
            "القناة": channel.mention,
        })

    @lock_cmd.error
    async def lock_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    # ---------------- ف (فتح) ----------------

    @commands.command(name="ف")
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def unlock_cmd(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if not await self._check_permission(ctx, "unlock", "set-up-unlock"):
            return
        channel = channel or ctx.channel

        missing = bot_missing_permissions(ctx.guild, "manage_channels")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            default_role = ctx.guild.default_role
            overwrite = channel.overwrites_for(default_role)
            # افتح الكتابة فقط. لا نغيّر view_channel، لذلك الروم المخفي
            # يبقى مخفياً بعد استخدام أمر الفتح.
            overwrite.send_messages = None
            await channel.set_permissions(
                default_role,
                overwrite=overwrite,
                reason=f"فتح بواسطة {ctx.author}",
            )
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أفتح القناة، تأكد من صلاحيات البوت فيها.")
            return

        await ctx.reply("🔓 تم فتح الروم.")
        await self.send_log(ctx.guild, "unlock", {
            "العملية": "🔓 فتح قناة",
            "بواسطة": ctx.author.mention,
            "القناة": channel.mention,
        })

    @unlock_cmd.error
    async def unlock_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    # ---------------- مسح (مسح رسائل) ----------------

    @commands.command(name="مسح")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def clear_cmd(self, ctx: commands.Context, target: Optional[discord.Member] = None, amount: int = None):
        if target is not None:
            await self._clear_v2(ctx, target, amount)
            return

        if not await self._check_permission(ctx, "clear", "set-up-clear"):
            return
        if amount is None:
            await ctx.reply("استخدم الأمر هيك: `مسح 20` (أقصى شي 100 رسالة بالمرة، حد ديسكورد)\n"
                             "أو `مسح @الشخص 20` لمسح رسائل شخص محدد بس.")
            return
        if amount <= 0:
            await ctx.reply("❌ لازم تكتب رقم أكبر من صفر.")
            return
        amount = min(amount, 100)

        missing = bot_missing_permissions(ctx.guild, "manage_messages")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            # +1 حتى نحذف رسالة الأمر نفسها كمان
            deleted = await ctx.channel.purge(limit=amount + 1)
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أمسح، تأكد من صلاحيات البوت.")
            return
        except discord.HTTPException:
            await ctx.reply("❌ في رسائل أقدم من 14 يوم ما فيني أمسحها بالجملة (حد ديسكورد).")
            return

        await self.send_log(ctx.guild, "clear", {
            "العملية": "🧹 مسح رسائل",
            "بواسطة": ctx.author.mention,
            "القناة": ctx.channel.mention,
            "العدد": len(deleted) - 1,
        })

    async def _clear_v2(self, ctx: commands.Context, target: discord.Member, amount: int):
        if not await self._check_permission(ctx, "clear_v2", "set-up-clear-v2"):
            return

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf["clear_v2"]
        max_amount = cfg.get("max_amount") or 50

        if amount is None:
            await ctx.reply(f"استخدم الأمر هيك: `مسح @الشخص 20` (أقصى شي {max_amount} رسالة بالمرة)")
            return
        if amount <= 0:
            await ctx.reply("❌ لازم تكتب رقم أكبر من صفر.")
            return
        if amount > max_amount:
            await ctx.reply(f"❌ أقصى عدد مسموح تمسحه بالمرة هون هو {max_amount} رسالة.")
            return

        protected_role_id = cfg.get("protected_role_id")
        protected_role = ctx.guild.get_role(protected_role_id) if protected_role_id else None
        if protected_role and any(r.position >= protected_role.position for r in target.roles):
            await ctx.reply("❌ ما فيك تمسح رسائل هاد الشخص، رتبته محمية.")
            return

        missing = bot_missing_permissions(ctx.guild, "manage_messages")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        cutoff = discord.utils.utcnow() - timedelta(days=1)
        collected = []
        try:
            async for msg in ctx.channel.history(limit=1000):
                if msg.created_at < cutoff:
                    break  # الرسائل بعدها كلها أقدم من يوم، ما في داعي نكمل نفتش
                if msg.author.id == target.id:
                    collected.append(msg)
                    if len(collected) >= amount:
                        break
        except discord.Forbidden:
            await ctx.send("❌ ما قدرت أقرأ رسائل الروم، تأكد من صلاحيات البوت.", delete_after=8)
            return

        if not collected:
            await ctx.send(f"ما لقيت رسائل لـ{target.mention} بآخر يوم بهاد الروم.", delete_after=6)
            return

        try:
            await ctx.channel.delete_messages(collected)
        except discord.Forbidden:
            await ctx.send("❌ ما قدرت أمسح، تأكد من صلاحيات البوت.", delete_after=8)
            return
        except discord.HTTPException:
            await ctx.send("❌ صار خطأ أثناء المسح، جرب مرة ثانية.", delete_after=8)
            return

        await ctx.send(f"🧹 تم مسح {len(collected)} رسالة لـ{target.mention}.", delete_after=6)
        await self.send_log(ctx.guild, "clear_v2", {
            "العملية": "🧹 مسح رسائل شخص محدد",
            "بواسطة": ctx.author.mention,
            "الهدف": target.mention,
            "القناة": ctx.channel.mention,
            "العدد": len(collected),
        })

    @clear_cmd.error
    async def clear_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ تأكد من كتابة الأمر صح: `مسح 20` أو `مسح @الشخص 20`")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelUtils(bot))
