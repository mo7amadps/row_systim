import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, bot_missing_permissions
from utils.embeds import branded_embed


class UnmuteSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, guild: discord.Guild, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["unmute"].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل $ان", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    @app_commands.command(name="set-up-unmute", description="إعداد أمر فك التايم ($ان)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم $ان", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_unmute(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "unmute", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام $ان", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_unmute.error
    async def set_up_unmute_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- $ان ----------------

    @commands.command(name="ان")
    @commands.guild_only()
    async def untimeout_cmd(self, ctx: commands.Context, member: discord.Member = None):
        if member is None:
            await ctx.reply("استخدم الأمر هيك: `$ان @شخص`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        u = conf["unmute"]
        if not u["allowed_role_ids"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-unmute` أول.")
            return
        if not has_any_role(ctx.author, u["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            await ctx.reply("❌ ما معك صلاحية.")
            return

        if member.timed_out_until is None:
            await ctx.reply("ℹ️ هاد الشخص ما معه تايم أوت أصلاً.")
            return

        missing = bot_missing_permissions(ctx.guild, "moderate_members")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            await member.timeout(None, reason=f"فك تايم بواسطة {ctx.author}")
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أفك التايم، تأكد من رتبة البوت.")
            return

        try:
            dm_embed = branded_embed(title="✅ تم فك التايم عنك", color=discord.Color.green())
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        await Storage.clear_timeout_giver(ctx.guild.id, member.id)

        await ctx.reply(f"✅ تم فك التايم عن {member.mention}")

        await self.send_log(ctx.guild, {
            "العملية": "✅ إلغاء تايم",
            "بواسطة": ctx.author.mention,
            "الهدف": member.mention,
        })


async def setup(bot: commands.Bot):
    await bot.add_cog(UnmuteSystem(bot))
