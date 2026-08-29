import re
from datetime import timedelta, datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.storage import Storage
from utils.checks import has_role, has_any_role, collect_roles, bot_missing_permissions
from utils.embeds import branded_embed

# تصنيف -> (اسم قسم التخزين، اسم الأمر النصي، الاسم المعروض)
TIERS = {
    "staff": {"section": "quest_staff", "command_name": "صغرى", "label": "صغرى"},
    "highstaff": {"section": "quest_highstaff", "command_name": "عليا", "label": "عليا"},
    "owner": {"section": "quest_owner", "command_name": "اونر", "label": "اونر"},
}
LABEL_TO_TIER = {v["label"]: k for k, v in TIERS.items()}

ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")


class QuestSystem(commands.Cog):
    """
    نظام مهام تلقائي:
    - 3 تصنيفات (صغرى / عليا / اونر) كل وحدة إلها سيت اب مستقل.
    - مهمة وحدة بس فعّالة بنفس الوقت لكل تصنيف.
    - تلقائياً بتنتهي بعد 24 ساعة من وقت نشرها.
    - تقدّم كل شخص بيتحسب من نفس XP يلي عم ياخده من رسائله العادية (نظام xp_system.py).
    - نوعين: ترقية (بتعطي رتبة تلقائياً عند الوصول للهدف) أو نقاط (بتطلب توثيق يدوي بثريد الشخص).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.expire_check.start()

    def cog_unload(self):
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
    def _extract_role(guild: discord.Guild, text: str):
        if not text:
            return None
        match = ROLE_MENTION_RE.search(text)
        if match:
            return guild.get_role(int(match.group(1)))
        if text.strip().isdigit():
            return guild.get_role(int(text.strip()))
        return None

    # ==================== إعداد مشترك ====================

    async def _run_quest_setup(
        self,
        interaction: discord.Interaction,
        tier: str,
        allowed_role_1: discord.Role,
        room: discord.TextChannel,
        xp_amount: int,
        reward: str,
        log_channel: discord.TextChannel,
        stopper_role: discord.Role = None,
        rank_1: discord.Role = None,
        rank_2: discord.Role = None,
        rank_3: discord.Role = None,
        rank_4: discord.Role = None,
        rank_5: discord.Role = None,
        allowed_role_2: discord.Role = None,
        allowed_role_3: discord.Role = None,
        allowed_role_4: discord.Role = None,
    ):
        label = TIERS[tier]["label"]
        section = TIERS[tier]["section"]
        cmd_name = TIERS[tier]["command_name"]

        if xp_amount <= 0:
            await interaction.response.send_message("❌ كمية الـ XP لازم تكون أكبر من صفر.", ephemeral=True)
            return

        ladder_roles = [r for r in [rank_1, rank_2, rank_3, rank_4, rank_5] if r is not None]
        if len(ladder_roles) == 1:
            await interaction.response.send_message(
                "❌ لازم رتبتين ع الأقل بسلّم الرتب (رتبة حالية + رتبة بعدها) حتى يشتغل، أو سيبهم كلهم فاضيين.",
                ephemeral=True,
            )
            return
        ladder_role_ids = [r.id for r in ladder_roles]

        role_ids = collect_roles(allowed_role_1, allowed_role_2, allowed_role_3, allowed_role_4)
        await Storage.update_guild(interaction.guild.id, section, {
            "allowed_role_ids": role_ids,
            "room_channel_id": room.id,
            "xp_amount": xp_amount,
            "reward": reward,
            "log_channel_id": log_channel.id,
            "stopper_role_id": stopper_role.id if stopper_role else None,
            "rank_ladder_role_ids": ladder_role_ids,
        })

        embed = branded_embed(title=f"✅ تم إعداد نظام مهام {label}", color=discord.Color.green())
        embed.add_field(name="الرتب المسموحة تستخدم الأمر", value=", ".join(f"<@&{i}>" for i in role_ids), inline=False)
        embed.add_field(name="روم المهمات", value=room.mention, inline=True)
        embed.add_field(name="كمية XP (الهدف)", value=str(xp_amount), inline=True)
        embed.add_field(name="الجائزة", value=reward, inline=True)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=True)
        if stopper_role:
            embed.add_field(name="رتبة توقيف المهمة", value=stopper_role.mention, inline=True)
        if ladder_roles:
            embed.add_field(
                name="🪜 سلّم الرتب (من الأقل للأعلى)",
                value=" ← ".join(r.mention for r in ladder_roles),
                inline=False,
            )
        embed.add_field(
            name="ℹ️ طريقة الشغل",
            value=(
                f"`مهام {cmd_name} ترقية` أو `مهام {cmd_name} نقاط` لنشر مهمة.\n"
                f"`مهام وقف {label}` لإيقافها (يلي كتبها أو رتبة التوقيف بس فيهم).\n"
                f"`مهام تقدم {label}` لمعرفة كم صرت متقدم.\n"
                + (
                    "بما إنه في سلّم رتب مُعد: بس أصحاب رتبة موجودة بالسلم (ومش أعلى رتبة فيه) تُحسب مشاركتهم، "
                    "ولما يخلصوا المهمة بينشال منهم رتبتهم الحالية وينحطلهم يلي بعدها بالسلم تلقائياً - "
                    "بغض النظر وين هما واصلين بالضبط."
                    if ladder_roles else
                    "ما في سلّم رتب مُعد، فلو النوع «ترقية» لازم حقل الجائزة يكون منشن رتبة صحيح (@رتبة) وبتنضاف بس (بدون ما تنشال أي رتبة)."
                )
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== set-up-quest-staff ====================

    @app_commands.command(name="set-up-quest-staff", description="إعداد نظام مهام صغرى")
    @app_commands.describe(
        allowed_role_1="أول رتبة تقدر تستخدم أمر نشر المهمة",
        room="روم المهمات (وين بتنشر المهمة)",
        xp_amount="كمية الـ XP (هدف المهمة)",
        reward="الجائزة - نص عادي، أو منشن رتبة لو النوع رح يكون ترقية",
        log_channel="قناة اللوق",
        stopper_role="رتبة إضافية (متل ستريتر) فيها توقف المهمة برضو - اختياري",
        rank_1="أول رتبة بسلّم الترقية (الأقل) - اختياري، بس لو حطيت وحدة لازم تحط رتبتين ع الأقل",
        rank_2="ثاني رتبة بالسلم (يلي بعد rank_1)",
        rank_3="ثالث رتبة بالسلم - اختياري", rank_4="رابع رتبة بالسلم - اختياري", rank_5="خامس رتبة بالسلم - اختياري",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_quest_staff(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, room: discord.TextChannel,
        xp_amount: int, reward: str, log_channel: discord.TextChannel, stopper_role: discord.Role = None,
        rank_1: discord.Role = None, rank_2: discord.Role = None, rank_3: discord.Role = None,
        rank_4: discord.Role = None, rank_5: discord.Role = None,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_quest_setup(
            interaction, "staff", allowed_role_1, room, xp_amount, reward, log_channel, stopper_role,
            rank_1, rank_2, rank_3, rank_4, rank_5, allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_quest_staff.error
    async def set_up_quest_staff_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ==================== set-up-quest-highstaff ====================

    @app_commands.command(name="set-up-quest-highstaff", description="إعداد نظام مهام عليا")
    @app_commands.describe(
        allowed_role_1="أول رتبة تقدر تستخدم أمر نشر المهمة",
        room="روم المهمات (وين بتنشر المهمة)",
        xp_amount="كمية الـ XP (هدف المهمة)",
        reward="الجائزة - نص عادي، أو منشن رتبة لو النوع رح يكون ترقية",
        log_channel="قناة اللوق",
        stopper_role="رتبة إضافية (متل ستريتر) فيها توقف المهمة برضو - اختياري",
        rank_1="أول رتبة بسلّم الترقية (الأقل) - اختياري، بس لو حطيت وحدة لازم تحط رتبتين ع الأقل",
        rank_2="ثاني رتبة بالسلم (يلي بعد rank_1)",
        rank_3="ثالث رتبة بالسلم - اختياري", rank_4="رابع رتبة بالسلم - اختياري", rank_5="خامس رتبة بالسلم - اختياري",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_quest_highstaff(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, room: discord.TextChannel,
        xp_amount: int, reward: str, log_channel: discord.TextChannel, stopper_role: discord.Role = None,
        rank_1: discord.Role = None, rank_2: discord.Role = None, rank_3: discord.Role = None,
        rank_4: discord.Role = None, rank_5: discord.Role = None,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_quest_setup(
            interaction, "highstaff", allowed_role_1, room, xp_amount, reward, log_channel, stopper_role,
            rank_1, rank_2, rank_3, rank_4, rank_5, allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_quest_highstaff.error
    async def set_up_quest_highstaff_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ==================== set-up-quest-owner ====================

    @app_commands.command(name="set-up-quest-owner", description="إعداد نظام مهام اونر")
    @app_commands.describe(
        allowed_role_1="أول رتبة تقدر تستخدم أمر نشر المهمة",
        room="روم المهمات (وين بتنشر المهمة)",
        xp_amount="كمية الـ XP (هدف المهمة)",
        reward="الجائزة - نص عادي، أو منشن رتبة لو النوع رح يكون ترقية",
        log_channel="قناة اللوق",
        stopper_role="رتبة إضافية (متل ستريتر) فيها توقف المهمة برضو - اختياري",
        rank_1="أول رتبة بسلّم الترقية (الأقل) - اختياري، بس لو حطيت وحدة لازم تحط رتبتين ع الأقل",
        rank_2="ثاني رتبة بالسلم (يلي بعد rank_1)",
        rank_3="ثالث رتبة بالسلم - اختياري", rank_4="رابع رتبة بالسلم - اختياري", rank_5="خامس رتبة بالسلم - اختياري",
        allowed_role_2="رتبة ثانية اختيارية", allowed_role_3="رتبة ثالثة اختيارية", allowed_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_quest_owner(
        self, interaction: discord.Interaction, allowed_role_1: discord.Role, room: discord.TextChannel,
        xp_amount: int, reward: str, log_channel: discord.TextChannel, stopper_role: discord.Role = None,
        rank_1: discord.Role = None, rank_2: discord.Role = None, rank_3: discord.Role = None,
        rank_4: discord.Role = None, rank_5: discord.Role = None,
        allowed_role_2: discord.Role = None, allowed_role_3: discord.Role = None, allowed_role_4: discord.Role = None,
    ):
        await self._run_quest_setup(
            interaction, "owner", allowed_role_1, room, xp_amount, reward, log_channel, stopper_role,
            rank_1, rank_2, rank_3, rank_4, rank_5, allowed_role_2, allowed_role_3, allowed_role_4,
        )

    @set_up_quest_owner.error
    async def set_up_quest_owner_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ==================== مهام (نشر / وقف) ====================

    @commands.group(name="مهام", invoke_without_command=True)
    @commands.guild_only()
    async def quest_group(self, ctx: commands.Context):
        await ctx.reply(
            "استخدم الأمر هيك:\n"
            "`مهام صغرى ترقية` أو `مهام صغرى نقاط`\n"
            "`مهام عليا ترقية` أو `مهام عليا نقاط`\n"
            "`مهام اونر ترقية` أو `مهام اونر نقاط`\n"
            "`مهام وقف صغرى` / `مهام وقف عليا` / `مهام وقف اونر`\n"
            "`مهام تقدم صغرى` (أو أي تصنيف تاني، وفيك تضيف منشن شخص)"
        )

    async def _post_quest(self, ctx: commands.Context, tier: str, quest_type: str):
        label = TIERS[tier]["label"]
        section = TIERS[tier]["section"]

        if quest_type not in ("ترقية", "نقاط"):
            await ctx.reply(f"استخدم الأمر هيك: `مهام {label} ترقية` أو `مهام {label} نقاط`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        cfg = conf[section]
        if not cfg["allowed_role_ids"] or not cfg["room_channel_id"] or not cfg["xp_amount"] or not cfg["reward"]:
            await ctx.reply(f"❌ نظام مهام {label} ما تم إعداده لسا. استخدم `/set-up-quest-{tier}` أول.")
            return
        if not has_any_role(ctx.author, cfg["allowed_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        existing = await Storage.get_active_quest(ctx.guild.id, tier)
        if existing:
            await ctx.reply(f"❌ في مهمة {label} شغالة أصلاً هلق. لازم توقفها الأول: `مهام وقف {label}`")
            return

        room = ctx.guild.get_channel(cfg["room_channel_id"])
        if not room:
            await ctx.reply(f"❌ روم المهمات المُعد انشال من السيرفر. أعد الإعداد بـ `/set-up-quest-{tier}`.")
            return

        reward_text = cfg["reward"]
        ladder_ids = cfg.get("rank_ladder_role_ids") or []
        reward_role = None
        if quest_type == "ترقية" and not ladder_ids:
            reward_role = self._extract_role(ctx.guild, reward_text)
            if reward_role is None:
                await ctx.reply(
                    "❌ نوع المهمة «ترقية» بس ما في سلّم رتب مُعد وحقل الجائزة بالسيت اب مو منشن رتبة صحيح.\n"
                    f"أعد الإعداد بـ `/set-up-quest-{tier}` وحط بحقل الجائزة منشن الرتبة (@اسم-الرتبة)، أو أعد الإعداد بسلّم رتب."
                )
                return

        now = discord.utils.utcnow()
        ends_at = now + timedelta(hours=24)

        embed = branded_embed(title=f"📜 مهمة جديدة - {label}", color=discord.Color.purple())
        embed.description = f"مين ما وصل الهدف بيتكرم تلقائياً! 🎯 نزّلها {ctx.author.mention}"
        embed.add_field(name="🎯 الهدف", value=f"{cfg['xp_amount']} XP", inline=True)
        embed.add_field(name="🏷️ النوع", value="🔼 ترقية" if quest_type == "ترقية" else "🎯 نقاط", inline=True)
        embed.add_field(name="🎁 الجائزة", value=reward_text, inline=True)
        embed.add_field(name="⏰ تنتهي", value=discord.utils.format_dt(ends_at, style="R"), inline=False)
        ladder_roles_display = [ctx.guild.get_role(rid) for rid in ladder_ids]
        ladder_roles_display = [r for r in ladder_roles_display if r]
        if ladder_roles_display:
            embed.add_field(
                name="🪜 سلّم الترقية", value=" ← ".join(r.mention for r in ladder_roles_display), inline=False
            )
        if quest_type == "نقاط":
            embed.add_field(
                name="📸 طريقة التوثيق",
                value="أول ما توصل للهدف، خذ دليل وابعته بثريدك.",
                inline=False,
            )
        else:
            embed.add_field(name="ℹ️ ملاحظة", value="أول ما توصل الهدف بتترقى تلقائياً، بدون أي شي إضافي منك.", inline=False)

        try:
            msg = await room.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أنشر بروم المهمات، تأكد من صلاحياتي فيه.")
            return

        quest_data = {
            "type": quest_type,
            "goal": cfg["xp_amount"],
            "reward": reward_text,
            "reward_role_id": reward_role.id if reward_role else None,
            "rank_ladder_role_ids": ladder_ids,
            "started_by": ctx.author.id,
            "channel_id": room.id,
            "message_id": msg.id,
            "started_at": now.isoformat(),
            "ends_at": ends_at.isoformat(),
            "progress": {},
            "completed_users": [],
        }
        await Storage.set_active_quest(ctx.guild.id, tier, quest_data)

        await ctx.reply(f"✅ تم نشر مهمة {label} بروم {room.mention}. بتنتهي خلال 24 ساعة.")
        await self.send_log(ctx.guild, tier, {
            "العملية": "📜 نشر مهمة",
            "بواسطة": ctx.author.mention,
            "النوع": quest_type,
            "الهدف": str(cfg["xp_amount"]),
            "الجائزة": reward_text,
        })

    @quest_group.command(name="صغرى")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_staff_post(self, ctx: commands.Context, quest_type: str = None):
        await self._post_quest(ctx, "staff", quest_type)

    @quest_group.command(name="عليا")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_highstaff_post(self, ctx: commands.Context, quest_type: str = None):
        await self._post_quest(ctx, "highstaff", quest_type)

    @quest_group.command(name="اونر")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def quest_owner_post(self, ctx: commands.Context, quest_type: str = None):
        await self._post_quest(ctx, "owner", quest_type)

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
        is_starter = ctx.author.id == quest.get("started_by")
        is_stopper = bool(cfg.get("stopper_role_id")) and has_role(ctx.author, cfg["stopper_role_id"])
        is_owner = ctx.author.id == ctx.guild.owner_id
        if not (is_starter or is_stopper or is_owner):
            await ctx.reply("❌ بس يلي كتب المهمة، أو صاحب رتبة التوقيف المُعدة، فيه يوقفها.")
            return

        await Storage.clear_active_quest(ctx.guild.id, tier)
        await ctx.reply(f"🛑 تم إيقاف مهمة {label}.")

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

        # توب 5 متصدرين بهاي المهمة (لو في أكتر من مشارك)
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
    async def quest_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    # ==================== حدث كسب XP -> تحديث تقدّم المهمات ====================

    @staticmethod
    def _ladder_position(member: discord.Member, ladder_role_ids: list) -> int:
        """بترجع أعلى index موجود عند العضو بسلّم الرتب (من الأقل=0 للأعلى)، أو -1 لو ما عنده ولا وحدة من السلّم."""
        member_role_ids = {r.id for r in member.roles}
        highest = -1
        for i, rid in enumerate(ladder_role_ids):
            if rid in member_role_ids:
                highest = i
        return highest

    @commands.Cog.listener()
    async def on_xp_awarded(self, guild: discord.Guild, member: discord.Member, amount: int, bucket: str):
        # تقدّم المهمات مربوط بخبرة الكتابة بس (متل ما هو مطلوب: "لما الشخص يكتب رسالة")
        if bucket != "xp" or amount <= 0:
            return
        for tier in TIERS:
            quest = await Storage.get_active_quest(guild.id, tier)
            if not quest:
                continue

            ladder = quest.get("rank_ladder_role_ids") or []
            if ladder:
                # بس أصحاب رتبة موجودة بالسلم تُحسب مشاركتهم (حتى لو كانوا بآخر رتبة)
                pos = self._ladder_position(member, ladder)
                if pos == -1:
                    continue

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

            if ladder:
                pos = self._ladder_position(member, ladder)
                if pos == -1 or pos >= len(ladder) - 1:
                    # وصل آخر رتبة بالسلم (أو مو موجود عليه أصلاً) - ما في رتبة أعلى نرقّيه لها
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
                # ما في سلّم مُعد - الوضع القديم: إضافة رتبة الجائزة بس (بدون شيل شي)
                role = guild.get_role(quest.get("reward_role_id")) if quest.get("reward_role_id") else None
                assigned = False
                if role:
                    missing = bot_missing_permissions(guild, "manage_roles")
                    if not missing and role not in member.roles:
                        try:
                            await member.add_roles(role, reason=f"إكمال مهمة {label}")
                            assigned = True
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                embed.description = f"مبروك {member.mention}! خلصت مهمة {label} ووصلت {quest['goal']} XP، وترقيت 🎊"
                if assigned:
                    embed.add_field(name="🎁 الرتبة الجديدة", value=role.mention, inline=True)
                elif role is None:
                    embed.add_field(name="⚠️ ملاحظة", value="ما قدرت ألاقي رتبة الجائزة المُعدة، بلغ الأدمن.", inline=False)
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

    # ==================== إنهاء تلقائي بعد 24 ساعة ====================

    @tasks.loop(minutes=1)
    async def expire_check(self):
        try:
            quests = await Storage.get_all_active_quests()
        except Exception:
            return

        now = datetime.now(timezone.utc)
        for guild_id, tier, quest in quests:
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

    @expire_check.before_loop
    async def before_expire_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(QuestSystem(bot))
