import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, bot_missing_permissions
from utils.embeds import branded_embed


class DismissSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, guild: discord.Guild, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["dismiss"].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل مفصول", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    # ---------------- /set-up-مفصول ----------------

    @app_commands.command(name="set-up-مفصول", description="إعداد أمر مفصول")
    @app_commands.describe(
        protect_from_role="الرتب يلي تحت (أو تساوي) هاي الرتبة ما بتنشال - بس يلي فوقها بتنشال",
        log_channel="قناة اللوق",
        allowed_role_1="أول رتبة مسموحلها تستخدم الأمر",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_dismiss(
        self, interaction: discord.Interaction, protect_from_role: discord.Role, log_channel: discord.TextChannel,
        allowed_role_1: discord.Role, allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "dismiss", {
            "allowed_role_ids": role_ids,
            "protect_role_id": protect_from_role.id,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام مفصول", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة تستخدم الأمر", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="الرتب المحمية (ما بتنشال)", value=f"{protect_from_role.mention} وكل يلي تحتها", inline=False)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=False)
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value=(
                "`مفصول @شخص` — بتشيل منه كل رتبة هي فوق "
                f"{protect_from_role.mention}، وبتخلي كل رتبة تحتها أو تساويها زي ما هي."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_dismiss.error
    async def set_up_dismiss_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- مفصول ----------------

    @commands.command(name="مفصول")
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def dismiss_cmd(self, ctx: commands.Context, member: discord.Member = None):
        if member is None:
            await ctx.reply("استخدم الأمر هيك: `مفصول @شخص`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        d = conf["dismiss"]
        if not d["allowed_role_ids"] or not d["protect_role_id"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-مفصول` أول.")
            return

        if not has_any_role(ctx.author, d["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        if ctx.guild.me is None:
            await ctx.reply("❌ صار خطأ وأنا عم أتحقق من صلاحياتي، جرب مرة ثانية.")
            return

        protect_role = ctx.guild.get_role(d["protect_role_id"])
        if not protect_role:
            await ctx.reply("❌ الرتبة المحمية المُعدة انشالت من السيرفر. أعد الإعداد بـ `/set-up-مفصول`.")
            return

        if member.id == ctx.author.id:
            await ctx.reply("❌ ما فيك تفصل حالك.")
            return
        if member.bot:
            await ctx.reply("❌ ما فيك تستهدف بوت.")
            return
        if member.id == ctx.guild.owner_id:
            await ctx.reply("❌ ما فيك تستهدف صاحب السيرفر.")
            return

        is_owner = ctx.author.id == ctx.guild.owner_id
        if not is_owner and member.top_role.position >= ctx.author.top_role.position:
            await ctx.reply("❌ هاد الشخص رتبته أعلى منك أو تساويك، ما فيك تستهدفه.")
            return

        bot_top_position = ctx.guild.me.top_role.position
        threshold = protect_role.position

        # منشيل كل رتبة فوق الرتبة المحمية (وما البوت أصلاً يقدر يتحكم فيها)
        roles_to_remove = [
            r for r in member.roles
            if not r.is_default() and not r.managed and r.position > threshold and r.position < bot_top_position
        ]

        if not roles_to_remove:
            await ctx.reply(
                f"ℹ️ {member.display_name} ما معه أي رتبة فوق {protect_role.mention} أصلاً.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        missing = bot_missing_permissions(ctx.guild, "manage_roles")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            await member.remove_roles(*roles_to_remove, reason=f"مفصول بواسطة {ctx.author}")
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أشيل الرتب، تأكد إنه رتبة البوت أعلى منها.")
            return
        except discord.HTTPException:
            await ctx.reply("❌ صار خطأ من ديسكورد وأنا عم أشيل الرتب. جرب مرة ثانية.")
            return

        removed_names = "، ".join(r.name for r in roles_to_remove)
        await ctx.reply(
            f"✅ تم فصل {member.display_name} - انشالت منه {len(roles_to_remove)} رتبة",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self.send_log(ctx.guild, {
            "العملية": "🚫 مفصول",
            "بواسطة": ctx.author.mention,
            "الهدف": member.mention,
            "الرتب يلي انشالت": removed_names,
        })

    @dismiss_cmd.error
    async def dismiss_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")


async def setup(bot: commands.Bot):
    await bot.add_cog(DismissSystem(bot))
