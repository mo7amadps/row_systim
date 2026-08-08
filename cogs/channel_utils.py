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

    @app_commands.command(name="set-up-lock", description="إعداد أمر قفل القناة ($ق)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم $ق", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_lock(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_setup(interaction, "lock", "نظام $ق", "$ق",
                               allowed_role_1, log_channel, allowed_role_2, allowed_role_3, allowed_role_4)

    @set_up_lock.error
    async def set_up_lock_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- /set-up-unlock ----------------

    @app_commands.command(name="set-up-unlock", description="إعداد أمر فتح القناة ($ف)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم $ف", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_unlock(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_setup(interaction, "unlock", "نظام $ف", "$ف",
                               allowed_role_1, log_channel, allowed_role_2, allowed_role_3, allowed_role_4)

    @set_up_unlock.error
    async def set_up_unlock_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- /set-up-clear ----------------

    @app_commands.command(name="set-up-clear", description="إعداد أمر مسح الرسائل ($مسح)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم $مسح", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_clear(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_setup(interaction, "clear", "نظام $مسح", "$مسح",
                               allowed_role_1, log_channel, allowed_role_2, allowed_role_3, allowed_role_4)

    @set_up_clear.error
    async def set_up_clear_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- $ق (قفل) ----------------

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
            await channel.set_permissions(
                ctx.guild.default_role, send_messages=False, reason=f"قفل بواسطة {ctx.author}"
            )
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أقفل القناة، تأكد من صلاحيات البوت فيها.")
            return

        await self.send_log(ctx.guild, "lock", {
            "العملية": "🔒 قفل قناة",
            "بواسطة": ctx.author.mention,
            "القناة": channel.mention,
        })

    @lock_cmd.error
    async def lock_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    # ---------------- $ف (فتح) ----------------

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
            await channel.set_permissions(
                ctx.guild.default_role, send_messages=None, reason=f"فتح بواسطة {ctx.author}"
            )
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أفتح القناة، تأكد من صلاحيات البوت فيها.")
            return

        await self.send_log(ctx.guild, "unlock", {
            "العملية": "🔓 فتح قناة",
            "بواسطة": ctx.author.mention,
            "القناة": channel.mention,
        })

    @unlock_cmd.error
    async def unlock_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    # ---------------- $مسح (مسح رسائل) ----------------

    @commands.command(name="مسح")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def clear_cmd(self, ctx: commands.Context, amount: int = None):
        if not await self._check_permission(ctx, "clear", "set-up-clear"):
            return
        if amount is None:
            await ctx.reply("استخدم الأمر هيك: `$مسح 20` (أقصى شي 100 رسالة بالمرة، حد ديسكورد)")
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

    @clear_cmd.error
    async def clear_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ تأكد من كتابة رقم صحيح: `$مسح 20`")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelUtils(bot))
