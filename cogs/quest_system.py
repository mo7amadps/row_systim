from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.storage import Storage
from utils.checks import has_role, has_any_role, collect_roles, bot_missing_permissions
from utils.embeds import branded_embed
from utils.time_parsing import parse_quest_start_time, PALESTINE_TZ

# تصنيف -> (اسم قسم التخزين، اسم الأمر النصي، الاسم المعروض)
TIERS = {
    "staff": {"section": "quest_staff", "command_name": "صغرى", "label": "صغرى"},
    "highstaff": {"section": "quest_highstaff", "command_name": "عليا", "label": "عليا"},
    "owner": {"section": "quest_owner", "command_name": "اونر", "label": "اونر"},
}
LABEL_TO_TIER = {v["label"]: k for k, v in TIERS.items()}


class QuestSystem(commands.Cog):
    """
    نظام مهام تلقائي:
    - 3 تصنيفات (صغرى / عليا / اونر) كل وحدة إلها سيت اب مستقل (4 خيارات بس: مين يستخدم الأمر، اللوق، أول رتبة، آخر رتبة).
    - سلّم الترقية بيتحسب تلقائياً من ترتيب الرتب الفعلي بالسيرفر بين أول وآخر رتبة (البوت "ذكي" - ما تحتاج تدخل كل رتبة يدوي).
    - نشر المهمة تفاعلي: تكتب `مهام صغرى`، بتطلعلك قائمة تختار نوعها، وبعدها نافذة تكتب فيها وقت النشر وكمية الـXP.
    - وقت النشر بتوقيت فلسطين (Asia/Hebron) - فيك تكتب "الآن" أو وقت متل "3 عصر" أو "بعد ساعة".
    - المهمة بتنتهي تلقائياً بعد 24 ساعة من وقت نشرها الفعلي.
    - تقدّم كل شخص بيتحسب من نفس XP يلي عم ياخده من رسائله العادية (نظام xp_system.py).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scheduled_publish_task.start()
        self.expire_check.start()

    def cog_unload(self):
        self.scheduled_publish_task.cancel()
        self.expire_check.cancel()

    async def send_log(self, guild: discord.Guild, tier: str, fields: dict):
        conf = await Storage.get_guild(guild.id)
        section = TIERS[tier]["section"]
        channel_id = conf[section].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(
            title=f"📋 سجل مهام {TIERS[tier]['label']}", color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    @staticmethod
    def _build_ladder_from_hierarchy(guild: discord.Guild, first_role: discord.Role, last_role: discord.Role) -> list:
        """بترجع لستة آيديات الرتب المرتبة من الأقل للأعلى، حسب ترتيب الرتب الفعلي بالسيرفر بين أول وآخر رتبة."""
        lo, hi = sorted([first_role.position, last_role.position])
        roles_in_range = [r for r in guild.roles if lo <= r.position <= hi and not r.is_default()]
        roles_in_range.sort(key=lambda r: r.position)
        return [r.id for r in roles_in_range]

    @staticmethod
    def _ladder_position(member: discord.Member, ladder_role_ids: list) -> int:
        """بترجع أعلى index موجود عند العضو بسلّم الرتب (من الأقل=0 للأعلى)، أو -1 لو ما عنده ولا وحدة من السلّم."""
        member_role_ids = {r.id for r in member.roles}
        highest = -1
        for i, rid in enumerate(ladder_role_ids):
            if rid in member_role_ids:
                highest = i
        return highest

    # ==================== إعداد مشترك (staff / highstaff / owner) ====================

    async def _run_quest_setup(
        self,
        interaction: discord.Interaction,
        tier: str,
        allowed_role_1: discord.Role,
        log_channel: discord.TextChannel,
        first_role: discord.Role,
        last_role: discord.Role,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        label = TIERS[tier]["label"]
        section = TIERS[tier]["section"]
        cmd_name = TIERS[tier]["command_name"]

        if first_role.id == last_role.id:
            await interaction.response.send_message("❌ أول وآخر رتبة لازم يكونوا مختلفين.", ephemeral=True)
            return

        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, section, {
            "allowed_role_ids": role_ids,
            "log_channel_id": log_channel.id,
            "first_role_id": first_role.id,
            "last_role_id": last_role.id,
        })

        ladder_ids = self._build_ladder_from_hierarchy(interaction.guild, first_role, last_role)
        ladder_roles = [interaction.guild.get_role(rid) for rid in ladder_ids]
        ladder_roles = [r for r in ladder_roles if r]

        embed = branded_embed(title=f"✅ تم إعداد نظام مهام {label}", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة تستخدم الأمر", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=True)
        embed.add_field(
            name="🪜 سلّم الترقية المكتشف حالياً",
            value=" ← ".join(r.mention for r in ladder_roles) if len(ladder_roles) > 1 else "⚠️ ما لقيت رتب كفاية بينهم",
            inline=False,
        )
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value=(
                f"اكتب `مهام {cmd_name}` وبتطلعلك قائمة تختار منها نوع المهمة (ترقية/نقاط)، "
                "وبعدها نافذة تحدد فيها وقت النشر وكمية الـXP.\n"
                "سلّم الترقية بيتحدث تلقائياً لو ضفت/شلت رتب من السيرفر بين أول وآخر رتبة - ما تحتاج تعيد الإعداد."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set-up-quest-staff", description="إعداد نظام مهام صغرى")
    @app_commands.describe(
        allowed_role_1="أول رتبة تقدر تستخدم أمر نشر المهمة",
        log_channel="قناة اللوق",
        first_role="أقل رتبة بسلّم الترقية (البداية)",
        last_role="أعلى رتبة بسلّم الترقية (النهاية) - البوت بياخد كل الرتب بينهم تلقائياً حسب ترتيبهم بالسيرفر",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_quest_staff(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        first_role: discord.Role, last_role: discord.Role,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_quest_setup(
            interaction, "staff", allowed_role_1, log_channel, first_role, last_role,
            allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_quest_staff.error
    async def set_up_quest_staff_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    @app_commands.command(name="set-up-quest-highstaff", description="إعداد نظام مهام عليا")
    @app_commands.describe(
        allowed_role_1="أول رتبة تقدر تستخدم أمر نشر المهمة",
        log_channel="قناة اللوق",
        first_role="أقل رتبة بسلّم الترقية (البداية)",
        last_role="أعلى رتبة بسلّم الترقية (النهاية) - البوت بياخد كل الرتب بينهم تلقائياً حسب ترتيبهم بالسيرفر",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_quest_highstaff(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        first_role: discord.Role, last_role: discord.Role,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_quest_setup(
            interaction, "highstaff", allowed_role_1, log_channel, first_role, last_role,
            allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_quest_highstaff.error
    async def set_up_quest_highstaff_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    @app_commands.command(name="set-up-quest-owner", description="إعداد نظام مهام اونر")
    @app_commands.describe(
        allowed_role_1="أول رتبة تقدر تستخدم أمر نشر المهمة",
        log_channel="قناة اللوق",
        first_role="أقل رتبة بسلّم الترقية (البداية)",
        last_role="أعلى رتبة بسلّم الترقية (النهاية) - البوت بياخد كل الرتب بينهم تلقائياً حسب ترتيبهم بالسيرفر",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_quest_owner(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, log_channel: discord.TextChannel,
        first_role: discord.Role, last_role: discord.Role,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_quest_setup(
            interaction, "owner", allowed_role_1, log_channel, first_role, last_role,
            allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_quest_owner.error
    async def set_up_quest_owner_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ==================== نشر مهمة (تفاعلي: قائمة + نافذة) ====================

    @commands.group(name="مهام", invoke_without_command=True)
    @commands.guild_only()
    async def quest_group(self, ctx: commands.Context):
        await ctx.reply(
            "استخدم الأمر هيك:\n"
            "`مهام صغرى` / `مهام عليا` / `مهام اونر` - لنشر مهمة جديدة (رح تطلعلك قائمة واختيارات)\n"
            "`مهام الكل` - تشوف حالة كل التصنيفات دفعة وحدة\n"
            "`مهام وقف صغرى` / `مهام وقف عليا` / `مهام وقف اونر`\n"
            "`مهام عدل صغرى` (أو أي تصنيف) - تعديل مهمة شغالة/مجدولة\n"
            "`مهام تقدم صغرى` (أو أي تصنيف تاني، وفيك تضيف منشن شخص)\n"
            "`مهام تاريخ صغرى` (أو أي تصنيف) - آخر المهمات المكتملة/المنتهية"
        )

    @quest_group.command(name="الكل")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_all_cmd(self, ctx: commands.Context):
        embed = branded_embed(title="📋 حالة كل تصنيفات المهام", color=discord.Color.blurple())
        for tier in TIERS:
            label = TIERS[tier]["label"]
            quest = await Storage.get_active_quest(ctx.guild.id, tier)
            if not quest:
                embed.add_field(name=f"🔹 {label}", value="ما في مهمة حالياً.", inline=False)
                continue

            if quest.get("status") == "scheduled":
                try:
                    starts_local = datetime.fromisoformat(quest["starts_at"]).astimezone(PALESTINE_TZ).strftime("%Y-%m-%d %H:%M")
                except (KeyError, ValueError):
                    starts_local = "?"
                value = f"🗓️ مجدولة - رح تُنشر الساعة {starts_local} (توقيت فلسطين)\n🎯 الهدف: {quest.get('goal')} XP"
            else:
                try:
                    ends_at = datetime.fromisoformat(quest["ends_at"])
                    ends_text = discord.utils.format_dt(ends_at, style="R")
                except (KeyError, ValueError):
                    ends_text = "؟"
                participants = len(quest.get("progress", {}))
                completed = len(quest.get("completed_users", []))
                value = (
                    f"🟢 شغالة الآن - النوع: {quest.get('type')}\n"
                    f"🎯 الهدف: {quest.get('goal')} XP | تنتهي: {ends_text}\n"
                    f"👥 مشاركين: {participants} | ✅ خلصوا: {completed}"
                )
            embed.add_field(name=f"🔹 {label}", value=value, inline=False)

        await ctx.reply(embed=embed)

    @quest_all_cmd.error
    async def quest_all_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    async def _start_quest_flow(self, ctx: commands.Context, tier: str):
        label = TIERS[tier]["label"]
        section = TIERS[tier]["section"]

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf[section]
        if not cfg["allowed_role_ids"] or not cfg["first_role_id"] or not cfg["last_role_id"] or not cfg["log_channel_id"]:
            await ctx.reply(f"❌ نظام مهام {label} ما تم إعداده لسا. استخدم `/set-up-quest-{tier}` أول.")
            return
        if not has_any_role(ctx.author, cfg["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        existing = await Storage.get_active_quest(ctx.guild.id, tier)
        if existing:
            status_txt = "شغالة هلق" if existing.get("status") == "live" else "مجدولة"
            await ctx.reply(f"❌ في مهمة {label} {status_txt} أصلاً. لازم توقفها الأول: `مهام وقف {label}`")
            return

        first_role = ctx.guild.get_role(cfg["first_role_id"])
        last_role = ctx.guild.get_role(cfg["last_role_id"])
        if not first_role or not last_role:
            await ctx.reply(f"❌ أول أو آخر رتبة المُعدة انشالت من السيرفر. أعد الإعداد بـ `/set-up-quest-{tier}`.")
            return

        view = QuestTypeSelectView(self, ctx, tier)
        await ctx.reply(f"📜 نشر مهمة {label} - اختار نوعها:", view=view)

    @quest_group.command(name="صغرى")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_staff_post(self, ctx: commands.Context):
        await self._start_quest_flow(ctx, "staff")

    @quest_group.command(name="عليا")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_highstaff_post(self, ctx: commands.Context):
        await self._start_quest_flow(ctx, "highstaff")

    @quest_group.command(name="اونر")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_owner_post(self, ctx: commands.Context):
        await self._start_quest_flow(ctx, "owner")

    async def finalize_quest(self, ctx: commands.Context, tier: str, quest_type: str, start_time_text: str, xp_text: str, interaction: discord.Interaction):
        label = TIERS[tier]["label"]
        section = TIERS[tier]["section"]

        try:
            goal = int(xp_text.strip())
            if goal <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ كمية الـXP لازم تكون رقم صحيح أكبر من صفر.", ephemeral=True)
            return

        ok, when_utc, err = parse_quest_start_time(start_time_text)
        if not ok:
            await interaction.response.send_message(f"❌ {err}", ephemeral=True)
            return

        # نتأكد ما حدا سبقنا وأنشأ مهمة بنفس اللحظة (تسابق نادر بس ممكن)
        existing = await Storage.get_active_quest(ctx.guild.id, tier)
        if existing:
            await interaction.response.send_message(f"❌ في مهمة {label} أصلاً موجودة، ما قدرت أنشئ وحدة جديدة.", ephemeral=True)
            return

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf[section]
        first_role = ctx.guild.get_role(cfg["first_role_id"])
        last_role = ctx.guild.get_role(cfg["last_role_id"])
        ladder_ids = self._build_ladder_from_hierarchy(ctx.guild, first_role, last_role) if (first_role and last_role) else []

        now_utc = datetime.now(timezone.utc)
        starts_at = when_utc if when_utc else now_utc
        ends_at = starts_at + timedelta(hours=24)
        is_immediate = when_utc is None

        quest_data = {
            "type": quest_type,
            "goal": goal,
            "rank_ladder_role_ids": ladder_ids,
            "started_by": ctx.author.id,
            "channel_id": ctx.channel.id,
            "message_id": None,
            "status": "live" if is_immediate else "scheduled",
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "progress": {},
            "completed_users": [],
        }
        await Storage.set_active_quest(ctx.guild.id, tier, quest_data)

        if is_immediate:
            await interaction.response.send_message(f"✅ جاري نشر مهمة {label} الآن...", ephemeral=True)
            await self._publish_quest(ctx.guild, tier, quest_data)
        else:
            local_str = starts_at.astimezone(PALESTINE_TZ).strftime("%Y-%m-%d %H:%M") if PALESTINE_TZ else starts_at.isoformat()
            await interaction.response.send_message(
                f"✅ تم جدولة مهمة {label} — رح تُنشر الساعة **{local_str}** (توقيت فلسطين) وتنتهي بعدها بـ24 ساعة.",
                ephemeral=True,
            )
            await self.send_log(ctx.guild, tier, {
                "العملية": "🗓️ جدولة مهمة",
                "بواسطة": ctx.author.mention,
                "النوع": quest_type,
                "الهدف": str(goal),
                "وقت النشر": local_str,
            })

    async def _publish_quest(self, guild: discord.Guild, tier: str, quest_data: dict):
        label = TIERS[tier]["label"]
        channel = guild.get_channel(quest_data["channel_id"])
        if not channel:
            await Storage.clear_active_quest(guild.id, tier)
            return

        ends_at = datetime.fromisoformat(quest_data["ends_at"])
        ladder_roles = [guild.get_role(rid) for rid in quest_data.get("rank_ladder_role_ids", [])]
        ladder_roles = [r for r in ladder_roles if r]

        embed = branded_embed(title=f"📜 مهمة جديدة - {label}", color=discord.Color.purple())
        embed.description = "مين ما وصل الهدف بيتكرم تلقائياً! 🎯"
        embed.add_field(name="🎯 الهدف", value=f"{quest_data['goal']} XP", inline=True)
        embed.add_field(name="🏷️ النوع", value="🔼 ترقية" if quest_data["type"] == "ترقية" else "🎯 نقاط", inline=True)
        embed.add_field(name="⏰ تنتهي", value=discord.utils.format_dt(ends_at, style="R"), inline=False)
        if ladder_roles:
            embed.add_field(name="🪜 سلّم الترقية", value=" ← ".join(r.mention for r in ladder_roles), inline=False)
        if quest_data["type"] == "نقاط":
            embed.add_field(name="📸 طريقة التوثيق", value="أول ما توصل للهدف، خذ دليل وابعته بثريدك.", inline=False)

        try:
            msg = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await Storage.clear_active_quest(guild.id, tier)
            return

        quest_data["message_id"] = msg.id
        quest_data["status"] = "live"
        await Storage.set_active_quest(guild.id, tier, quest_data)

        await self.send_log(guild, tier, {
            "العملية": "📜 نشر مهمة",
            "النوع": quest_data["type"],
            "الهدف": str(quest_data["goal"]),
        })

    # ==================== إيقاف مهمة ====================

    @quest_group.command(name="وقف")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_stop(self, ctx: commands.Context, tier_label: str = None):
        if tier_label not in LABEL_TO_TIER:
            await ctx.reply("استخدم الأمر هيك: `مهام وقف صغرى` أو `مهام وقف عليا` أو `مهام وقف اونر`")
            return

        tier = LABEL_TO_TIER[tier_label]
        label = TIERS[tier]["label"]
        section = TIERS[tier]["section"]

        quest = await Storage.get_active_quest(ctx.guild.id, tier)
        if not quest:
            await ctx.reply(f"ℹ️ ما في مهمة {label} شغالة حالياً.")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf[section]
        if not self._can_manage_quest(ctx, cfg, quest):
            await ctx.reply("❌ بس يلي كتب المهمة، أو حدا من الرتب المسموحة تستخدم الأمر، فيه يوقفها.")
            return

        await Storage.clear_active_quest(ctx.guild.id, tier)
        await ctx.reply(f"🛑 تم إيقاف مهمة {label}.")

        if quest.get("status") == "live":
            channel = ctx.guild.get_channel(quest.get("channel_id"))
            if channel:
                try:
                    await channel.send(embed=branded_embed(
                        title=f"🛑 توقفت مهمة {label}",
                        description=f"أوقفها {ctx.author.mention}",
                        color=discord.Color.red(),
                    ), allowed_mentions=discord.AllowedMentions.none())
                except discord.Forbidden:
                    pass

        await self.send_log(ctx.guild, tier, {"العملية": "🛑 إيقاف مهمة", "بواسطة": ctx.author.mention})

        await Storage.add_quest_history_entry(ctx.guild.id, tier, {
            "event": "stopped",
            "by": ctx.author.id,
            "by_name": str(ctx.author),
            "goal": quest.get("goal"),
            "participants": len(quest.get("progress", {})),
            "completed": len(quest.get("completed_users", [])),
            "at": datetime.now(timezone.utc).isoformat(),
        })

    # ==================== تعديل مهمة ====================

    def _can_manage_quest(self, ctx: commands.Context, cfg: dict, quest: dict) -> bool:
        is_starter = ctx.author.id == quest.get("started_by")
        is_allowed_staff = has_any_role(ctx.author, cfg.get("allowed_role_ids", []))
        is_owner = ctx.author.id == ctx.guild.owner_id
        return is_starter or is_allowed_staff or is_owner

    @quest_group.command(name="عدل")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_edit_cmd(self, ctx: commands.Context, tier_label: str = None):
        if tier_label not in LABEL_TO_TIER:
            await ctx.reply("استخدم الأمر هيك: `مهام عدل صغرى` (أو `عليا`/`اونر`)")
            return

        tier = LABEL_TO_TIER[tier_label]
        label = TIERS[tier]["label"]
        section = TIERS[tier]["section"]

        quest = await Storage.get_active_quest(ctx.guild.id, tier)
        if not quest:
            await ctx.reply(f"ℹ️ ما في مهمة {label} شغالة حالياً حتى تعدلها.")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf[section]
        if not self._can_manage_quest(ctx, cfg, quest):
            await ctx.reply("❌ بس يلي كتب المهمة، أو حدا من الرتب المسموحة تستخدم الأمر، فيه يعدلها.")
            return

        view = QuestEditButtonView(self, ctx, tier, quest)
        status_txt = "مجدولة (فيك تعدل الوقت والـXP)" if quest.get("status") == "scheduled" else "شغالة (فيك تعدل الـXP بس - الوقت ثابت لأنها نُشرت أصلاً)"
        await ctx.reply(f"✏️ مهمة {label} حالياً {status_txt}. اضغط الزر تحت حتى تعدل:", view=view)

    async def apply_quest_edit(self, ctx: commands.Context, tier: str, new_goal_text: str, new_time_text: str, interaction: discord.Interaction):
        label = TIERS[tier]["label"]

        try:
            new_goal = int(new_goal_text.strip())
            if new_goal <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ كمية الـXP لازم تكون رقم صحيح أكبر من صفر.", ephemeral=True)
            return

        quest = await Storage.get_active_quest(ctx.guild.id, tier)
        if not quest:
            await interaction.response.send_message(f"❌ مهمة {label} ما عادت موجودة (تم إيقافها أو انتهت).", ephemeral=True)
            return

        quest["goal"] = new_goal

        if quest.get("status") == "scheduled" and new_time_text is not None:
            ok, when_utc, err = parse_quest_start_time(new_time_text)
            if not ok:
                await interaction.response.send_message(f"❌ {err}", ephemeral=True)
                return
            now_utc = datetime.now(timezone.utc)
            starts_at = when_utc if when_utc else now_utc
            quest["starts_at"] = starts_at.isoformat()
            quest["ends_at"] = (starts_at + timedelta(hours=24)).isoformat()

        await Storage.set_active_quest(ctx.guild.id, tier, quest)

        # لو المهمة شغالة أصلاً وليها رسالة منشورة، نحاول نعدل الإيمبد الأصلي كمان
        if quest.get("status") == "live" and quest.get("message_id") and quest.get("channel_id"):
            channel = ctx.guild.get_channel(quest["channel_id"])
            if channel:
                try:
                    msg = await channel.fetch_message(quest["message_id"])
                    if msg.embeds:
                        embed = msg.embeds[0]
                        for i, field in enumerate(embed.fields):
                            if field.name == "🎯 الهدف":
                                embed.set_field_at(i, name="🎯 الهدف", value=f"{new_goal} XP", inline=field.inline)
                                break
                        await msg.edit(embed=embed)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        await interaction.response.send_message(f"✅ تم تعديل مهمة {label}: الهدف الجديد {new_goal} XP.", ephemeral=True)
        await self.send_log(ctx.guild, tier, {"العملية": "✏️ تعديل مهمة", "بواسطة": ctx.author.mention, "الهدف الجديد": str(new_goal)})

    # ==================== تقدّم مهمة ====================

    @staticmethod
    def _progress_bar(pct: int, length: int = 12) -> str:
        filled = round(length * min(max(pct, 0), 100) / 100)
        return "🟩" * filled + "⬜" * (length - filled)

    @quest_group.command(name="تقدم")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_progress_cmd(self, ctx: commands.Context, tier_label: str = None, member: discord.Member = None):
        if tier_label not in LABEL_TO_TIER:
            await ctx.reply(
                "استخدم الأمر هيك: `مهام تقدم صغرى` (أو `عليا`/`اونر`)، وفيك تضيف منشن شخص تاني تشوف تقدمه."
            )
            return

        tier = LABEL_TO_TIER[tier_label]
        label = TIERS[tier]["label"]

        quest = await Storage.get_active_quest(ctx.guild.id, tier)
        if not quest:
            await ctx.reply(f"ℹ️ ما في مهمة {label} شغالة حالياً.")
            return

        if quest.get("status") != "live":
            local_str = datetime.fromisoformat(quest["starts_at"]).astimezone(PALESTINE_TZ).strftime("%Y-%m-%d %H:%M") if PALESTINE_TZ else quest["starts_at"]
            await ctx.reply(f"ℹ️ مهمة {label} لسا مجدولة، رح تُنشر الساعة {local_str} (توقيت فلسطين).")
            return

        target = member or ctx.author
        goal = quest.get("goal", 0)
        progress = quest.get("progress", {}).get(str(target.id), 0)
        completed = str(target.id) in quest.get("completed_users", [])
        pct = int(min(progress, goal) / goal * 100) if goal else 0

        embed = branded_embed(title=f"📊 تقدّم مهمة {label}", color=discord.Color.blurple())
        embed.description = (
            f"{target.mention}\n"
            f"{self._progress_bar(pct)}  **{pct}%**\n"
            f"**{progress} / {goal}** XP"
        )
        embed.add_field(name="الحالة", value="✅ خلصها" if completed else "🔄 لسا عم يشتغل عليها", inline=True)
        try:
            ends_at = datetime.fromisoformat(quest["ends_at"])
            embed.add_field(name="⏰ تنتهي", value=discord.utils.format_dt(ends_at, style="R"), inline=True)
        except (KeyError, ValueError):
            pass

        ranked = sorted(quest.get("progress", {}).items(), key=lambda kv: kv[1], reverse=True)[:5]
        if len(ranked) > 1:
            lines = []
            for i, (uid, amt) in enumerate(ranked):
                m = ctx.guild.get_member(int(uid))
                name = m.mention if m else f"<@{uid}>"
                lines.append(f"{i + 1}. {name} — {amt} XP")
            embed.add_field(name="🏅 المتصدرين بالمهمة", value="\n".join(lines), inline=False)

        await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @quest_group.error
    @quest_staff_post.error
    @quest_highstaff_post.error
    @quest_owner_post.error
    @quest_stop.error
    @quest_progress_cmd.error
    @quest_edit_cmd.error
    async def quest_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    # ==================== تاريخ المهمات ====================

    @quest_group.command(name="تاريخ")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def quest_history_cmd(self, ctx: commands.Context, tier_label: str = None):
        if tier_label not in LABEL_TO_TIER:
            await ctx.reply("استخدم الأمر هيك: `مهام تاريخ صغرى` (أو `عليا`/`اونر`)")
            return

        tier = LABEL_TO_TIER[tier_label]
        label = TIERS[tier]["label"]
        history = await Storage.get_quest_history(ctx.guild.id, tier, limit=10)

        if not history:
            await ctx.reply(f"ℹ️ ما في سجل مهمات {label} لسا.")
            return

        lines = []
        for entry in history:
            try:
                at_local = datetime.fromisoformat(entry["at"]).astimezone(PALESTINE_TZ).strftime("%Y-%m-%d %H:%M")
            except (KeyError, ValueError):
                at_local = "؟"

            event = entry.get("event")
            if event == "completed":
                member = ctx.guild.get_member(entry.get("user_id"))
                name = member.mention if member else entry.get("user_name", "؟")
                lines.append(f"✅ **{at_local}** — {name} خلص المهمة ({entry.get('type')}, هدف {entry.get('goal')})")
            elif event == "stopped":
                by_member = ctx.guild.get_member(entry.get("by"))
                by_name = by_member.mention if by_member else entry.get("by_name", "؟")
                lines.append(
                    f"🛑 **{at_local}** — أوقفها {by_name} "
                    f"(مشاركين: {entry.get('participants', 0)}, خلصوا: {entry.get('completed', 0)})"
                )
            elif event == "expired":
                lines.append(
                    f"⌛ **{at_local}** — انتهت تلقائياً "
                    f"(مشاركين: {entry.get('participants', 0)}, خلصوا: {entry.get('completed', 0)})"
                )

        embed = branded_embed(title=f"📜 تاريخ مهمات {label} (آخر {len(history)})", color=discord.Color.dark_gold())
        embed.description = "\n".join(lines)
        await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @quest_history_cmd.error
    async def quest_history_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    # ==================== حدث كسب XP -> تحديث تقدّم المهمات ====================

    @commands.Cog.listener()
    async def on_xp_awarded(self, guild: discord.Guild, member: discord.Member, amount: int, bucket: str):
        # تقدّم المهمات مربوط بخبرة الكتابة بس (متل ما هو مطلوب: "لما الشخص يكتب رسالة")
        if bucket != "xp" or amount <= 0:
            return
        for tier in TIERS:
            quest = await Storage.get_active_quest(guild.id, tier)
            if not quest or quest.get("status") != "live":
                continue

            ladder = quest.get("rank_ladder_role_ids") or []
            if ladder:
                pos = self._ladder_position(member, ladder)
                if pos == -1:
                    continue  # مو موجود عالسلم إطلاقاً - ما تُحسب مشاركته

            result = await Storage.add_quest_progress(guild.id, tier, member.id, amount)
            if result and result["just_completed"]:
                await self._handle_completion(guild, tier, member, result)

    async def _handle_completion(self, guild: discord.Guild, tier: str, member: discord.Member, result: dict):
        quest = result["quest"]
        label = TIERS[tier]["label"]
        channel = guild.get_channel(quest.get("channel_id"))

        embed = branded_embed(title="🎉 مبروك خلصت المهمة!", color=discord.Color.green())

        if quest["type"] == "ترقية":
            ladder = quest.get("rank_ladder_role_ids") or []
            pos = self._ladder_position(member, ladder) if ladder else -1

            if not ladder or pos == -1 or pos >= len(ladder) - 1:
                embed.description = (
                    f"مبروك {member.mention}! خلصت مهمة {label} ووصلت {quest['goal']} XP 🎊\n"
                    "إنت أصلاً بآخر رتبة بسلّم الترقية، فما في رتبة أعلى نرفعك لها تلقائياً.\n"
                    "خذ دليل وكلم مسؤولك مباشرة."
                )
            else:
                current_role = guild.get_role(ladder[pos])
                next_role = guild.get_role(ladder[pos + 1])
                assigned = False
                removed = False
                if next_role:
                    missing = bot_missing_permissions(guild, "manage_roles")
                    if not missing:
                        try:
                            if next_role not in member.roles:
                                await member.add_roles(next_role, reason=f"إكمال مهمة {label}")
                                assigned = True
                            if current_role and current_role in member.roles:
                                await member.remove_roles(current_role, reason=f"ترقية بعد إكمال مهمة {label}")
                                removed = True
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                embed.description = f"مبروك {member.mention}! خلصت مهمة {label} ووصلت {quest['goal']} XP، وترقيت 🎊"
                if assigned:
                    embed.add_field(name="🎁 الرتبة الجديدة", value=next_role.mention, inline=True)
                elif next_role is None:
                    embed.add_field(name="⚠️ ملاحظة", value="الرتبة الجاية بالسلم انشالت من السيرفر، بلغ الأدمن.", inline=False)
                if removed:
                    embed.add_field(name="↩️ انشالت منك", value=current_role.mention, inline=True)
        else:
            embed.description = (
                f"مبروك {member.mention}! خلصت مهمة {label} يلي فيها {quest['goal']} نقطة.\n"
                "خذ دليل وابعته بثريدك."
            )

        if channel:
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[member]))
            except discord.Forbidden:
                pass

        await self.send_log(guild, tier, {
            "العملية": "🎉 إكمال مهمة",
            "الشخص": member.mention,
            "النوع": quest["type"],
            "الهدف": str(quest["goal"]),
        })

        await Storage.add_quest_history_entry(guild.id, tier, {
            "event": "completed",
            "user_id": member.id,
            "user_name": str(member),
            "type": quest["type"],
            "goal": quest["goal"],
            "at": datetime.now(timezone.utc).isoformat(),
        })

    # ==================== نشر المهمات المجدولة + الإنهاء التلقائي ====================

    @tasks.loop(seconds=30)
    async def scheduled_publish_task(self):
        try:
            quests = await Storage.get_all_active_quests()
        except Exception:
            return

        now = datetime.now(timezone.utc)
        for guild_id, tier, quest in quests:
            if quest.get("status") != "scheduled":
                continue
            try:
                starts_at = datetime.fromisoformat(quest["starts_at"])
            except (KeyError, ValueError):
                continue
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            if now < starts_at:
                continue

            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            await self._publish_quest(guild, tier, quest)

    @scheduled_publish_task.before_loop
    async def before_scheduled_publish_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def expire_check(self):
        try:
            quests = await Storage.get_all_active_quests()
        except Exception:
            return

        now = datetime.now(timezone.utc)
        for guild_id, tier, quest in quests:
            if quest.get("status") != "live":
                continue
            ends_at_raw = quest.get("ends_at")
            if not ends_at_raw:
                continue
            try:
                ends_at = datetime.fromisoformat(ends_at_raw)
            except ValueError:
                continue
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)

            if now < ends_at:
                continue

            await Storage.clear_active_quest(guild_id, tier)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            channel = guild.get_channel(quest.get("channel_id"))
            label = TIERS[tier]["label"]
            if channel:
                try:
                    await channel.send(embed=branded_embed(
                        title=f"⌛ انتهت مهمة {label}",
                        description="خلصت مدتها (24 ساعة). حد بدو ينزل وحدة جديدة يقدر هلق.",
                        color=discord.Color.orange(),
                    ))
                except discord.Forbidden:
                    pass
            await self.send_log(guild, tier, {"العملية": "⌛ انتهاء تلقائي للمهمة"})

            await Storage.add_quest_history_entry(guild_id, tier, {
                "event": "expired",
                "goal": quest.get("goal"),
                "participants": len(quest.get("progress", {})),
                "completed": len(quest.get("completed_users", [])),
                "at": datetime.now(timezone.utc).isoformat(),
            })

    @expire_check.before_loop
    async def before_expire_check(self):
        await self.bot.wait_until_ready()


class QuestEditButtonView(discord.ui.View):
    def __init__(self, cog: QuestSystem, ctx: commands.Context, tier: str, quest: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.tier = tier
        self.quest = quest

    @discord.ui.button(label="✏️ عدل المهمة", style=discord.ButtonStyle.primary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ بس يلي طلب التعديل فيه يعدل.", ephemeral=True)
            return
        await interaction.response.send_modal(QuestEditModal(self.cog, self.ctx, self.tier, self.quest))


class QuestEditModal(discord.ui.Modal):
    def __init__(self, cog: QuestSystem, ctx: commands.Context, tier: str, quest: dict):
        super().__init__(title=f"تعديل مهمة {TIERS[tier]['label']}")
        self.cog = cog
        self.ctx = ctx
        self.tier = tier
        self.is_scheduled = quest.get("status") == "scheduled"

        self.xp_input = discord.ui.TextInput(
            label="كمية الـXP الجديدة (الهدف)",
            default=str(quest.get("goal", "")),
            required=True,
            max_length=10,
        )
        self.add_item(self.xp_input)

        self.time_input = None
        if self.is_scheduled:
            try:
                current_local = datetime.fromisoformat(quest["starts_at"]).astimezone(PALESTINE_TZ).strftime("%H:%M")
            except (KeyError, ValueError):
                current_local = ""
            self.time_input = discord.ui.TextInput(
                label="وقت النشر الجديد (فاضي = خليه متل ما هو)",
                placeholder=f"مثلاً: 3 عصر / بعد ساعة (حالياً: {current_local})",
                required=False,
                max_length=30,
            )
            self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_time_text = str(self.time_input) if (self.time_input and str(self.time_input).strip()) else None
        await self.cog.apply_quest_edit(self.ctx, self.tier, str(self.xp_input), new_time_text, interaction)


class QuestTypeSelect(discord.ui.Select):
    def __init__(self, cog: QuestSystem, ctx: commands.Context, tier: str):
        self.cog = cog
        self.ctx = ctx
        self.tier = tier
        options = [
            discord.SelectOption(label="ترقية", emoji="🔼", description="بترقي الشخص لرتبة أعلى بسلّم الترقية"),
            discord.SelectOption(label="نقاط", emoji="🎯", description="بتطلب من الشخص يوثق إكماله بدليل بثريده"),
        ]
        super().__init__(placeholder="اختار نوع المهمة...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ بس يلي طلب نشر المهمة فيه يختار.", ephemeral=True)
            return
        quest_type = self.values[0]
        await interaction.response.send_modal(QuestDetailsModal(self.cog, self.ctx, self.tier, quest_type))


class QuestTypeSelectView(discord.ui.View):
    def __init__(self, cog: QuestSystem, ctx: commands.Context, tier: str):
        super().__init__(timeout=120)
        self.add_item(QuestTypeSelect(cog, ctx, tier))


class QuestDetailsModal(discord.ui.Modal):
    def __init__(self, cog: QuestSystem, ctx: commands.Context, tier: str, quest_type: str):
        super().__init__(title=f"تفاصيل مهمة {TIERS[tier]['label']}")
        self.cog = cog
        self.ctx = ctx
        self.tier = tier
        self.quest_type = quest_type

        self.start_time_input = discord.ui.TextInput(
            label="متى تنزل المهمة؟",
            placeholder="الآن / 3 عصر / 10 صباحا / بعد 2 ساعة (بتوقيت فلسطين)",
            required=True,
            max_length=30,
        )
        self.xp_input = discord.ui.TextInput(
            label="كمية الـXP (الهدف)",
            placeholder="مثلاً: 1500",
            required=True,
            max_length=10,
        )
        self.add_item(self.start_time_input)
        self.add_item(self.xp_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.finalize_quest(
            self.ctx, self.tier, self.quest_type, str(self.start_time_input), str(self.xp_input), interaction
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(QuestSystem(bot))
