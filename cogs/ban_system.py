import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import (
    can_target,
    has_role,
    has_any_role,
    collect_roles,
    bot_missing_permissions,
    setup_permission_check,
)
from utils.embeds import branded_embed


class BanSystem(commands.Cog):
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

    # ---------------- /set-up-ban ----------------

    @app_commands.command(name="set-up-ban", description="إعداد نظام الباند")
    @app_commands.describe(
        allowed_role_1="أول رتبة تقدر تستخدم أمر الباند",
        daily_limit="أقصى عدد باندات يومياً لهاي الرتبة",
        unlimited_role="رتبة باند لا نهائي (بدون حد يومي)",
        log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية",
        allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_ban(
        self,
        interaction: discord.Interaction,
        allowed_role_1: discord.Role,
        daily_limit: int,
        unlimited_role: discord.Role,
        log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "ban", {
            "allowed_role_ids": role_ids,
            "daily_limit": daily_limit,
            "unlimited_role_id": unlimited_role.id,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام الباند", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="الحد اليومي", value=str(daily_limit))
        embed.add_field(name="رتبة باند لا نهائي", value=unlimited_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_ban.error
    async def set_up_ban_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- باند ----------------
    # فيك تستهدف الشخص بالمنشن أو بالآيدي (حتى لو مو موجود بالسيرفر أصلاً).
    # لو كتبت السبب بنفس الرسالة (باند @شخص السبب هون) بيتنفذ فوراً.
    # لو ما كتبتوش، البوت بيطلب منك تكتبه برسالة جديدة وبينفذ فوراً أول ما توصل.

    @commands.command(name="باند", aliases=["بانكاي", "لف", "تفو", "زحلق"])
    @commands.check(setup_permission_check("ban", "unlimited_role_id"))
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)  # كولداون 10 ثواني بين كل باند
    async def ban_cmd(self, ctx: commands.Context, target: discord.User = None, *, reason: str = None):
        if target is None:
            await ctx.reply("استخدم الأمر هيك: `باند @شخص` أو `باند آيدي_الشخص` (تقدر تضيف السبب بنفس الرسالة)")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        b = conf["ban"]
        if not b["allowed_role_ids"]:
            return

        is_unlimited = has_role(ctx.author, b["unlimited_role_id"])
        is_allowed = has_any_role(ctx.author, b["allowed_role_ids"])
        if not (is_unlimited or is_allowed):
            return

        if target.id == ctx.author.id:
            await ctx.reply("❌ ما فيك تستهدف نفسك.")
            return
        if target.id == self.bot.user.id:
            await ctx.reply("❌ ما فيك تستهدفني.")
            return

        # لو الشخص موجود بالسيرفر فعلياً، منطبق حماية التسلسل الهرمي العادية.
        # لو مو موجود (باند بالآيدي لشخص مو بالسيرفر)، منتحقق بس إنه مو صاحب السيرفر.
        member = ctx.guild.get_member(target.id)
        if member is not None:
            ok, msg = can_target(ctx.author, member)
            if not ok:
                await ctx.reply(f"❌ {msg}")
                return
        elif target.id == ctx.guild.owner_id:
            await ctx.reply("❌ ما فيك تستهدف صاحب السيرفر.")
            return

        if not is_unlimited and b["daily_limit"]:
            used = await Storage.get_usage(ctx.guild.id, "ban", ctx.author.id)
            if used >= b["daily_limit"]:
                await ctx.reply(f"❌ وصلت للحد الأقصى من الباند اليوم ({b['daily_limit']}).")
                return

        if reason is None:
            await ctx.reply(
                f"✍️ طيب، اكتب سبب باند {target.mention} برسالة جديدة (عندك 90 ثانية).",
                allowed_mentions=discord.AllowedMentions.none(),
            )

            def check(m: discord.Message):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            try:
                reason_msg = await self.bot.wait_for("message", check=check, timeout=90)
            except asyncio.TimeoutError:
                await ctx.reply("⌛ خلصت المهلة، أعد الأمر من جديد.")
                return

            reason = reason_msg.content.strip()
            if not reason:
                await ctx.reply("❌ لازم تكتب سبب فعلي (نص).")
                return

        missing = bot_missing_permissions(ctx.guild, "ban_members")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        # الرسالة الخاصة أولاً (لو الشخص موجود بالسيرفر وفاتح الخاص)، وبعدها الباند فعلياً
        try:
            dm_embed = branded_embed(title="🔨 تم تبنيدك", color=discord.Color.red())
            dm_embed.add_field(name="السبب", value=reason, inline=False)
            await target.send(embed=dm_embed)
        except discord.HTTPException:
            pass

        try:
            await ctx.guild.ban(target, reason=reason, delete_message_seconds=0)
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أبند الشخص، تأكد إنه رتبة البوت أعلى من رتبته.")
            return
        except discord.HTTPException:
            await ctx.reply("❌ صار خطأ من ديسكورد وأنا عم أبند الشخص. جرب مرة ثانية.")
            return

        if not is_unlimited:
            await Storage.increment_usage(ctx.guild.id, "ban", ctx.author.id)

        await ctx.reply(
            f"✅ تم باند {target.mention}\nالسبب: {reason}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

        await self.send_log(ctx.guild, "ban", {
            "العملية": "🔨 باند",
            "بواسطة": ctx.author.mention,
            "الهدف": f"{target} ({target.id})",
            "السبب": reason,
        })

    @ban_cmd.error
    async def ban_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى شوي، فيك تعمل باند تاني بعد {error.retry_after:.0f} ثانية.")
        elif isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن أو الآيدي.")


async def setup(bot: commands.Bot):
    await bot.add_cog(BanSystem(bot))
