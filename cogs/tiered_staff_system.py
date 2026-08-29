import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, build_ladder, bot_missing_permissions, member_rank, setup_permission_check
from utils.embeds import branded_embed

# اسم الأمر النصي لكل نظام + اسمه المعروض بالرسائل
TIERS = {
    "staff": {"command_name": "صغرى", "label": "صغرى"},
    "highstaff": {"command_name": "عليا", "label": "عليا"},
    "owner": {"command_name": "اونر", "label": "اونر"},
}


class TieredStaffSystem(commands.Cog):
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
        embed = branded_embed(
            title=f"📋 سجل {TIERS[section]['label']}", color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    # ---------------- منطق مشترك للسيت أب ----------------

    async def _run_tiered_setup(
        self, interaction: discord.Interaction, section: str,
        allowed_role_1: discord.Role, first_role: discord.Role, last_role: discord.Role,
        tickets_role: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        label = TIERS[section]["label"]
        cmd_name = TIERS[section]["command_name"]
        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)

        await Storage.update_guild(interaction.guild.id, section, {
            "allowed_role_ids": role_ids,
            "first_role_id": first_role.id,
            "last_role_id": last_role.id,
            "tickets_role_id": tickets_role.id,
            "log_channel_id": log_channel.id,
        })

        ladder = build_ladder(interaction.guild, first_role, last_role, exclude_role_ids={tickets_role.id})

        embed = branded_embed(title=f"✅ تم إعداد نظام {label}", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة تستخدم الأمر", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="أول رتبة بالسلسلة", value=first_role.mention, inline=True)
        embed.add_field(name="آخر رتبة بالسلسلة", value=last_role.mention, inline=True)
        embed.add_field(name="عدد الرتب بالسلسلة", value=str(len(ladder)), inline=True)
        embed.add_field(name="رتبة التكتات (بتنعطى مع أي استخدام)", value=tickets_role.mention, inline=True)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=True)
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value=(
                f"`{cmd_name} @شخص [رقم]`\n"
                f"من غير رقم → بيعطيه بس أول رتبة (رتبة 1) + رتبة التكتات.\n"
                f"مع رقم (مثلاً `{cmd_name} @شخص 5`) → بيعطيه كل الرتب من 1 لحد 5 + رتبة التكتات.\n"
                f"الرقم لازم يكون بين 1 و {len(ladder)}."
            ),
            inline=False,
        )
        if len(ladder) == 0:
            embed.add_field(
                name="⚠️ تنبيه",
                value="ما لقيت أي رتبة بين الرتبة الأولى والأخيرة يلي اخترتهم. تأكد من ترتيب الرتب بالسيرفر.",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- منطق مشترك لتنفيذ الأمر ----------------

    async def _run_tiered_command(self, ctx: commands.Context, section: str, member: discord.Member, rank: int):
        label = TIERS[section]["label"]
        cmd_name = TIERS[section]["command_name"]

        if member is None:
            await ctx.reply(f"استخدم الأمر هيك: `{cmd_name} @شخص [رقم]`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        s = conf[section]
        if not s["allowed_role_ids"] or not s["first_role_id"] or not s["last_role_id"] or not s["tickets_role_id"]:
            await ctx.reply(f"❌ النظام ما تم إعداده لسا. استخدم `/set-up-{cmd_name}` أول.")
            return

        if not has_any_role(ctx.author, s["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        if ctx.guild.me is None:
            await ctx.reply("❌ صار خطأ وأنا عم أتحقق من صلاحياتي، جرب مرة ثانية.")
            return

        first_role = ctx.guild.get_role(s["first_role_id"])
        last_role = ctx.guild.get_role(s["last_role_id"])
        tickets_role = ctx.guild.get_role(s["tickets_role_id"])
        if not first_role or not last_role or not tickets_role:
            await ctx.reply(f"❌ حدى الرتب المُعدة انشالت من السيرفر. أعد الإعداد بـ `/set-up-{cmd_name}`.")
            return

        ladder = build_ladder(ctx.guild, first_role, last_role, exclude_role_ids={tickets_role.id})
        if not ladder:
            await ctx.reply("❌ ما في أي رتب بين الرتبة الأولى والأخيرة المُعدتين.")
            return

        # مستشعر تلقائي: إذا الشخص أصلاً معه رتبة من هاي الفئة (أي رتبة من السلّم)، منعلم المستخدم بهيك
        current_rank = member_rank(member, ladder)

        if rank is None:
            rank = 1
        if rank < 1 or rank > len(ladder):
            await ctx.reply(f"❌ الرقم لازم يكون بين 1 و {len(ladder)} (عدد رتب {label}).")
            return

        if member.id == ctx.guild.owner_id and ctx.author.id != ctx.guild.owner_id:
            await ctx.reply("❌ ما فيك تستهدف صاحب السيرفر.")
            return

        is_owner = ctx.author.id == ctx.guild.owner_id
        target_roles = ladder[:rank] + [tickets_role]

        # حماية التسلسل الهرمي: ما فيك تعطي رتبة هي أصلاً فوق أعلى رتبة عندك انت
        if not is_owner:
            actor_position = ctx.author.top_role.position
            blocked = [r for r in target_roles if r.position >= actor_position]
            if blocked:
                await ctx.reply("❌ في رتبة (أو أكتر) بهاد المدى هي فوق رتبتك أو تساويها، ما فيك تعطيها.")
                return

        bot_top_position = ctx.guild.me.top_role.position
        roles_to_add = [r for r in target_roles if r not in member.roles and r.position < bot_top_position]

        sensor_note = ""
        if current_rank > 0:
            sensor_note = f"\nℹ️ ملاحظة: {member.display_name} أصلاً معه رتبة {label} (رتبة {current_rank}/{len(ladder)}) من قبل."

        if not roles_to_add:
            await ctx.reply(
                f"ℹ️ {member.display_name} أصلاً معه كل الرتب المطلوبة.{sensor_note}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        missing = bot_missing_permissions(ctx.guild, "manage_roles")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        try:
            await member.add_roles(*roles_to_add, reason=f"{label} بواسطة {ctx.author}")
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أعطي الرتب، تأكد إنه رتبة البوت أعلى من هاي الرتب.")
            return
        except discord.HTTPException:
            await ctx.reply("❌ صار خطأ من ديسكورد وأنا عم أعطي الرتب. جرب مرة ثانية.")
            return

        await ctx.reply(
            f"✅ تم تعيين {member.display_name} كـ {label} برتبة {rank} (من أصل {len(ladder)}) + رتبة التكتات{sensor_note}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self.send_log(ctx.guild, section, {
            "العملية": f"⭐ {label}",
            "بواسطة": ctx.author.mention,
            "الهدف": member.mention,
            "الرتبة": f"{rank}/{len(ladder)}",
        })

    # ==================== staff ====================

    @app_commands.command(name="set-up-staff", description="إعداد نظام الستاف (سلسلة رتب)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم الأمر", first_role="أول رتبة بسلسلة الستاف (الأوطى)",
        last_role="آخر رتبة بسلسلة الستاف (الأعلى)", tickets_role="رتبة التكتات - بتنعطى تلقائياً مع أي استخدام للأمر",
        log_channel="قناة اللوق", allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_staff(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, first_role: discord.Role,
        last_role: discord.Role, tickets_role: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_tiered_setup(
            interaction, "staff", allowed_role_1, first_role, last_role, tickets_role, log_channel,
            allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_staff.error
    async def set_up_staff_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    @commands.command(name="صغرى")
    @commands.check(setup_permission_check("staff"))
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def staff_cmd(self, ctx: commands.Context, member: discord.Member = None, rank: int = None):
        await self._run_tiered_command(ctx, "staff", member, rank)

    @staff_cmd.error
    async def staff_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    # ==================== highstaff ====================

    @app_commands.command(name="set-up-highstaff", description="إعداد نظام الهاي ستاف (سلسلة رتب)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم الأمر", first_role="أول رتبة بسلسلة الهاي ستاف (الأوطى)",
        last_role="آخر رتبة بسلسلة الهاي ستاف (الأعلى)", tickets_role="رتبة التكتات - بتنعطى تلقائياً مع أي استخدام للأمر",
        log_channel="قناة اللوق", allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_highstaff(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, first_role: discord.Role,
        last_role: discord.Role, tickets_role: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_tiered_setup(
            interaction, "highstaff", allowed_role_1, first_role, last_role, tickets_role, log_channel,
            allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_highstaff.error
    async def set_up_highstaff_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    @commands.command(name="عليا")
    @commands.check(setup_permission_check("highstaff"))
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def highstaff_cmd(self, ctx: commands.Context, member: discord.Member = None, rank: int = None):
        await self._run_tiered_command(ctx, "highstaff", member, rank)

    @highstaff_cmd.error
    async def highstaff_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    # ==================== owner ====================

    @app_commands.command(name="set-up-owner", description="إعداد نظام الأونر (سلسلة رتب)")
    @app_commands.describe(
        allowed_role_1="أول رتبة مسموحلها تستخدم الأمر", first_role="أول رتبة بسلسلة الأونر (الأوطى)",
        last_role="آخر رتبة بسلسلة الأونر (الأعلى)", tickets_role="رتبة التكتات - بتنعطى تلقائياً مع أي استخدام للأمر",
        log_channel="قناة اللوق", allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية",
        allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_owner(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, first_role: discord.Role,
        last_role: discord.Role, tickets_role: discord.Role, log_channel: discord.TextChannel,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_tiered_setup(
            interaction, "owner", allowed_role_1, first_role, last_role, tickets_role, log_channel,
            allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_owner.error
    async def set_up_owner_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    @commands.command(name="اونر")
    @commands.check(setup_permission_check("owner"))
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def owner_cmd(self, ctx: commands.Context, member: discord.Member = None, rank: int = None):
        await self._run_tiered_command(ctx, "owner", member, rank)

    @owner_cmd.error
    async def owner_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")


async def setup(bot: commands.Bot):
    await bot.add_cog(TieredStaffSystem(bot))
