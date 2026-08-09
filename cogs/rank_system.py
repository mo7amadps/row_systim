import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, full_role_ladder, member_rank, actor_max_rank, bot_missing_permissions
from utils.embeds import branded_embed

PROMOTE_BLOCKED_MSG = "❌ ما تقدر تعطي هاي الرتبة، انتظر يجي زهايمر أو روي 😄"


class RankSystem(commands.Cog):
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

    # ---------------- /set-up-add-role ----------------

    @app_commands.command(name="set-up-add-role", description="إعداد نظام الترقية")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم أمر الترقية", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_add_role(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "add_role", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام الترقية", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_add_role.error
    async def set_up_add_role_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- /set-up-remove-role ----------------

    @app_commands.command(name="set-up-remove-role", description="إعداد نظام التخفيض")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم أمر التخفيض", log_channel="قناة اللوق",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_remove_role(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, "remove_role", {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام التخفيض", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_remove_role.error
    async def set_up_remove_role_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- $ترقية ----------------

    @commands.command(name="ترقية")
    @commands.guild_only()
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def promote_cmd(self, ctx: commands.Context, member: discord.Member = None, amount: int = None):
        if member is None or amount is None:
            await ctx.reply("استخدم الأمر هيك: `$ترقية @شخص 3`")
            return
        if amount <= 0:
            await ctx.reply("❌ لازم تكتب رقم أكبر من صفر.")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf["add_role"]
        if not cfg["allowed_role_ids"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-add-role` أول.")
            return
        if not has_any_role(ctx.author, cfg["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        if member.id == ctx.author.id:
            await ctx.reply("❌ ما فيك ترقي حالك.")
            return
        if member.bot:
            await ctx.reply("❌ ما فيك تستهدف بوت.")
            return
        if member.id == ctx.guild.owner_id:
            await ctx.reply("❌ ما فيك تستهدف صاحب السيرفر.")
            return

        ladder = full_role_ladder(ctx.guild)
        if not ladder:
            await ctx.reply("❌ ما في أي رتب متاحة بسلّم الترقية حالياً.")
            return

        current_rank = member_rank(member, ladder)
        max_rank_for_actor = actor_max_rank(ctx.author, ladder)
        new_rank = current_rank + amount

        if new_rank >= max_rank_for_actor and ctx.author.id != ctx.guild.owner_id:
            await ctx.reply(PROMOTE_BLOCKED_MSG)
            return
        if new_rank > len(ladder):
            await ctx.reply(f"❌ ما في رتب كفاية، أقصى رتبة متاحة هي {len(ladder)}.")
            return

        missing = bot_missing_permissions(ctx.guild, "manage_roles")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        # نظام تراكمي: نضيف بس الرتب الجديدة اللي بين رتبته الحالية والرتبة الجديدة،
        # من غير ما نلمس أي رتبة عنده أصلاً (تحت أو فوق)
        roles_to_add = [r for r in ladder[current_rank:new_rank] if r not in member.roles]
        new_role = ladder[new_rank - 1]

        try:
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason=f"ترقية بواسطة {ctx.author}")
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أرقي الشخص، تأكد إنه رتبة البوت أعلى من هاي الرتب.")
            return

        await ctx.reply(f"✅ تم ترقية {member.mention} من رتبة {current_rank} إلى رتبة {new_rank} ({new_role.mention})")

        await self.send_log(ctx.guild, "add_role", {
            "العملية": "⬆️ ترقية",
            "بواسطة": ctx.author.mention,
            "الهدف": member.mention,
            "من رتبة": current_rank,
            "إلى رتبة": f"{new_rank} ({new_role.mention})",
        })

    @promote_cmd.error
    async def promote_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ تأكد من كتابة الأمر صح: `$ترقية @شخص 3`")

    # ---------------- $تخفيض ----------------

    @commands.command(name="تخفيض")
    @commands.guild_only()
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def demote_cmd(self, ctx: commands.Context, member: discord.Member = None, amount: int = None):
        if member is None or amount is None:
            await ctx.reply("استخدم الأمر هيك: `$تخفيض @شخص 2`")
            return
        if amount <= 0:
            await ctx.reply("❌ لازم تكتب رقم أكبر من صفر.")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf["remove_role"]
        if not cfg["allowed_role_ids"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-remove-role` أول.")
            return
        if not has_any_role(ctx.author, cfg["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        if member.id == ctx.author.id:
            await ctx.reply("❌ ما فيك تخفض حالك.")
            return
        if member.bot:
            await ctx.reply("❌ ما فيك تستهدف بوت.")
            return
        if member.id == ctx.guild.owner_id:
            await ctx.reply("❌ ما فيك تستهدف صاحب السيرفر.")
            return

        ladder = full_role_ladder(ctx.guild)
        if not ladder:
            await ctx.reply("❌ ما في أي رتب متاحة بسلّم التخفيض حالياً.")
            return

        current_rank = member_rank(member, ladder)
        actor_rank = actor_max_rank(ctx.author, ladder)

        # الشرط: رتبة الهدف الحالية لازم تكون أوطى من رتبة الفاعل (مو الرتبة الناتجة)
        if current_rank >= actor_rank and ctx.author.id != ctx.guild.owner_id:
            await ctx.reply("❌ ما تقدر تخفض هاد الشخص، رتبته أعلى أو تساوي رتبتك.")
            return

        if current_rank == 0:
            await ctx.reply("ℹ️ هاد الشخص أصلاً ما عنده أي رتبة من السلّم.")
            return

        new_rank = current_rank - amount
        if new_rank < 0:
            await ctx.reply(f"❌ ما تقدر تخفضه هيك كتير، أقصى تخفيض ممكن هو {current_rank}.")
            return

        missing = bot_missing_permissions(ctx.guild, "manage_roles")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        # نظام تراكمي: نشيل بس الرتب اللي من فوق (بين الرتبة الجديدة والرتبة الحالية)،
        # ونسيب الرتب اللي تحت الرتبة الجديدة زي ما هي من غير ما نلمسها
        roles_to_remove = [r for r in ladder[new_rank:current_rank] if r in member.roles]
        new_role = ladder[new_rank - 1] if new_rank > 0 else None

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=f"تخفيض بواسطة {ctx.author}")
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أخفض الشخص، تأكد إنه رتبة البوت أعلى من هاي الرتب.")
            return

        result_text = f"رتبة {new_rank} ({new_role.mention})" if new_role else "بدون رتبة"
        await ctx.reply(f"✅ تم تخفيض {member.mention} من رتبة {current_rank} إلى {result_text}")

        await self.send_log(ctx.guild, "remove_role", {
            "العملية": "⬇️ تخفيض",
            "بواسطة": ctx.author.mention,
            "الهدف": member.mention,
            "من رتبة": current_rank,
            "إلى": result_text,
        })

    @demote_cmd.error
    async def demote_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ تأكد من كتابة الأمر صح: `$تخفيض @شخص 2`")


async def setup(bot: commands.Bot):
    await bot.add_cog(RankSystem(bot))
