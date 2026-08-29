import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, bot_missing_permissions, setup_permission_check
from utils.embeds import branded_embed


class UnbanSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, guild: discord.Guild, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["unban"].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل فك الباند", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    # ---------------- /set-up-unban ----------------

    @app_commands.command(name="set-up-unban", description="إعداد أمر فك الباند")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تفك باند", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_unban(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "unban", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام فك الباند", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة تفك باند", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(name="ℹ️ طريقة الشغل", value="`فك-الباند آيدي_الشخص` أو `فك-الباند @الشخص` (لو لسا بالسيرفر بالغلط).", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_unban.error
    async def set_up_unban_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- فك-الباند ----------------

    @commands.command(name="فك-الباند")
    @commands.check(setup_permission_check("unban"))
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def unban_cmd(self, ctx: commands.Context, user: discord.User = None):
        if user is None:
            await ctx.reply("استخدم الأمر هيك: `فك-الباند آيدي_الشخص`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        u = conf["unban"]
        if not u["allowed_role_ids"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-unban` أول.")
            return
        if not has_any_role(ctx.author, u["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        missing = bot_missing_permissions(ctx.guild, "ban_members")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            await ctx.guild.fetch_ban(user)
        except discord.NotFound:
            await ctx.reply("ℹ️ هاد الشخص مو مبندود أصلاً.")
            return
        except discord.HTTPException:
            await ctx.reply("❌ صار خطأ وأنا عم أتأكد من الباند، جرب مرة ثانية.")
            return

        try:
            await ctx.guild.unban(user, reason=f"فك باند بواسطة {ctx.author}")
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أفك الباند، تأكد من صلاحيات البوت.")
            return

        await ctx.reply(f"✅ تم فك الباند عن `{user}` ({user.id})")

        await self.send_log(ctx.guild, {
            "العملية": "🔓 فك باند",
            "بواسطة": ctx.author.mention,
            "الهدف": f"{user} ({user.id})",
        })

    @unban_cmd.error
    async def unban_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.UserNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من الآيدي أو المنشن.")


async def setup(bot: commands.Bot):
    await bot.add_cog(UnbanSystem(bot))
