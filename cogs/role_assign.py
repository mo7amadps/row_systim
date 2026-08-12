import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, bot_missing_permissions, is_dangerous_role
from utils.embeds import branded_embed


def _resolve_role(guild: discord.Guild, query: str):
    query = query.strip()
    if query.startswith("<@&") and query.endswith(">"):
        query = query[3:-1]
    if query.isdigit():
        role = guild.get_role(int(query))
        if role:
            return role
    query_l = query.lower()
    exact = [r for r in guild.roles if r.name.lower() == query_l]
    if exact:
        return exact[0]
    return None


class RoleAssignSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, guild: discord.Guild, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["role_assign"].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل رول", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    @app_commands.command(name="set-up-roles", description="إعداد أمر رول")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم رول", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_roles(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "role_assign", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام رول", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value=(
                "`رول @شخص id_الرتبة` — لو الرتبة مش معه بتنعطاله، ولو معه بتنشال منه.\n"
                "أي حد يقدر يستخدمها حتى على رتب شخص فوقه، بس الرتبة يلي عم يعدلها لازم تكون تحت رتبته هو نفسه "
                "(ما فيه يعطي أو يشيل رتبة أعلى من أو تساوي أعلى رتبة معه)."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_roles.error
    async def set_up_roles_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- رول ----------------

    @commands.command(name="رول")
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def role_cmd(self, ctx: commands.Context, member: discord.Member = None, *, role_query: str = None):
        if member is None or not role_query:
            await ctx.reply("استخدم الأمر هيك: `رول @شخص id_الرتبة`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        r = conf["role_assign"]
        if not r["allowed_role_ids"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-roles` أول.")
            return
        if not has_any_role(ctx.author, r["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        role = _resolve_role(ctx.guild, role_query)
        if role is None:
            await ctx.reply("❌ ما لقيت رتبة بهاد الآيدي/الاسم.")
            return

        # سقف الصلاحية: نفس منطق رتب - الرتبة يلي عم تتلمس لازم تكون تحت أعلى رتبة عند actor
        # (إلا إذا كان actor هو الأونر)، بغض النظر مين هو الهدف أو شو رتبته
        is_owner = ctx.author.id == ctx.guild.owner_id
        if not is_owner and role.position >= ctx.author.top_role.position:
            await ctx.reply("❌ ما فيك تتحكم بهاي الرتبة، هي أعلى من رتبتك أو تساويها.")
            return

        if role.managed:
            await ctx.reply("❌ هاي رتبة تلقائية تابعة لبوت، ما فيك تتحكم فيها.")
            return
        if is_dangerous_role(role):
            await ctx.reply("❌ هاي رتبة فيها صلاحيات حساسة (إدارية)، ما فيك تعطيها/تشيلها بهاد الأمر.")
            return

        missing = bot_missing_permissions(ctx.guild, "manage_roles")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return
        if role.position >= ctx.guild.me.top_role.position:
            await ctx.reply("❌ رتبة البوت لازم تكون أعلى من هاي الرتبة حتى يقدر يتحكم فيها.")
            return

        try:
            if role in member.roles:
                await member.remove_roles(role, reason=f"رول بواسطة {ctx.author}")
                action = "🔻 تم شيل"
            else:
                await member.add_roles(role, reason=f"رول بواسطة {ctx.author}")
                action = "✅ تم إعطاء"
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أعدّل الرتبة، تأكد من صلاحيات البوت.")
            return

        await ctx.reply(f"{action} رتبة `{role.name}` {'من' if 'شيل' in action else 'لـ'} {member.mention}")
        await self.send_log(ctx.guild, {
            "العملية": f"🏷️ رول - {action}",
            "بواسطة": ctx.author.mention,
            "الهدف": member.mention,
            "الرتبة": role.name,
        })

    @role_cmd.error
    async def role_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleAssignSystem(bot))
