import discord
from discord import app_commands
from discord.ext import commands, tasks
from typing import Union

from utils.storage import Storage, xp_needed_for_level
from utils.checks import has_any_role, bot_missing_permissions
from utils.embeds import branded_embed
from utils.xp_logic import compute_message_xp, clamp_xp

PAGE_SIZE = 10
BUCKET_LABEL = {"xp": "الكتابة", "voice_xp": "الفويس"}
PERIOD_LABEL = {"all": "الكل", "day": "اليوم", "week": "الأسبوع"}


class LeaderboardView(discord.ui.View):
    """أزرار تنقل بين صفحات الليدربورد (10 أشخاص بالصفحة، متل توب بوتات نوفا)."""

    def __init__(self, board: list, guild: discord.Guild, bucket: str, period: str, author_id: int):
        super().__init__(timeout=120)
        self.board = board
        self.guild = guild
        self.bucket = bucket
        self.period = period
        self.author_id = author_id
        self.page = 0
        self.total_pages = max(1, (len(board) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    def make_embed(self) -> discord.Embed:
        start = self.page * PAGE_SIZE
        chunk = self.board[start:start + PAGE_SIZE]
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}

        lines = []
        for i, (uid, entry) in enumerate(chunk):
            rank = start + i
            member = self.guild.get_member(uid)
            name = member.mention if member else f"<@{uid}> (غادر)"
            prefix = medals.get(rank, f"#{rank + 1}")
            xp_value = entry.get({"all": "xp", "day": "xp_day", "week": "xp_week"}[self.period], 0)
            lines.append(f"🔶 **{prefix}** {name} - مستوى: {entry.get('level', 0)} | خبرة: {xp_value}")

        title = f"🏅 أفضل نقاط {BUCKET_LABEL[self.bucket]} ({PERIOD_LABEL[self.period]})"
        embed = branded_embed(title=title, color=discord.Color.gold())
        embed.description = "\n".join(lines) if lines else "ما في بيانات بهاي الصفحة."
        embed.set_footer(text=f"{embed.footer.text} • صفحة {self.page + 1}/{self.total_pages}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ بس يلي طلب الليدربورد فيه يتصفح الصفحات.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


class XPSystem(commands.Cog):
    """
    نظام XP مستقل بالكامل جوا البوت (مو مربوط بأي بوت خارجي) - نفس فكرة نوفا:
    - كل رسالة = XP محسوب بشكل منطقي (شوف utils/xp_logic.py) مع كولداون.
    - كل دقيقة متصل بالفويس = XP ثابت لكل دقيقة.
    - مستويات تلقائية + رتب مكافآت عند مستوى معين.
    - ليدربورد بصفحات (يوم / أسبوع / كل الوقت) لكل من الكتابة والفويس.
    - نظام المهام (quest_system.py) بيسمع حدث "xp_awarded" عشان يحسب تقدّم المهمات (كتابة بس).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_xp_task.start()
        self.period_reset_task.start()

    def cog_unload(self):
        self.voice_xp_task.cancel()
        self.period_reset_task.cancel()

    async def send_log(self, guild: discord.Guild, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["xp"].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل XP", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    # ---------------- الاستماع للرسائل وإعطاء XP كتابة ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not message.content and not message.attachments:
            return

        conf = await Storage.get_guild(message.guild.id)
        cfg = conf["xp"]

        if cfg["no_xp_channel_ids"] and message.channel.id in cfg["no_xp_channel_ids"]:
            return
        member = message.author
        if cfg["no_xp_role_ids"] and any(r.id in cfg["no_xp_role_ids"] for r in getattr(member, "roles", [])):
            return

        amount = clamp_xp(compute_message_xp(message.content, len(message.attachments)), cfg["xp_min"], cfg["xp_max"])
        result = await Storage.add_xp(message.guild.id, member.id, "xp", amount, cfg["cooldown_seconds"])

        # نبعت حدث لنظام المهام عشان يحسب تقدّم أي مهمة فعّالة (كتابة بس - مو فويس)
        if result["gained"] > 0:
            self.bot.dispatch("xp_awarded", message.guild, member, result["gained"], "xp")

        if result["gained"] == 0 or result["new_level"] <= result["old_level"]:
            return

        await self._announce_levelup(message.guild, member, result, cfg, fallback_channel=message.channel)

    async def _announce_levelup(self, guild: discord.Guild, member: discord.Member, result: dict, cfg: dict, fallback_channel=None):
        new_level = result["new_level"]
        target_channel = fallback_channel
        if cfg.get("levelup_channel_id"):
            ch = guild.get_channel(cfg["levelup_channel_id"])
            if ch:
                target_channel = ch
        if target_channel is None:
            return

        embed = branded_embed(title="🎉 لفل أب!", color=discord.Color.gold())
        embed.description = f"مبروك {member.mention}! وصلت للمستوى **{new_level}** 🚀"
        embed.add_field(name="XP الحالي", value=str(result["total_xp"]), inline=True)

        role_id = cfg["role_rewards"].get(str(new_level))
        awarded_role = None
        if role_id:
            role = guild.get_role(role_id)
            if role and role not in member.roles:
                missing = bot_missing_permissions(guild, "manage_roles")
                if not missing:
                    try:
                        await member.add_roles(role, reason=f"مكافأة الوصول للمستوى {new_level}")
                        awarded_role = role
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        if awarded_role:
            embed.add_field(name="🎁 رتبة جديدة", value=awarded_role.mention, inline=True)

        try:
            await target_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.Forbidden:
            pass

        await self.send_log(guild, {
            "العملية": "🎉 لفل أب",
            "الشخص": member.mention,
            "المستوى الجديد": str(new_level),
            "XP الحالي": str(result["total_xp"]),
        })

    # ---------------- XP الفويس: تاسك كل دقيقة ----------------

    @tasks.loop(minutes=1)
    async def voice_xp_task(self):
        for guild in self.bot.guilds:
            conf = await Storage.get_guild(guild.id)
            xp_cfg = conf["xp"]
            voice_cfg = conf["voice_xp"]
            per_minute = voice_cfg.get("xp_per_minute", 0)
            if per_minute <= 0:
                continue

            no_xp_channels = set(xp_cfg.get("no_xp_channel_ids", []))
            no_xp_roles = set(xp_cfg.get("no_xp_role_ids", []))
            afk_channel_id = guild.afk_channel.id if guild.afk_channel else None

            for vc in guild.voice_channels:
                if vc.id == afk_channel_id or vc.id in no_xp_channels:
                    continue
                # لازم أكتر من شخص متصل حتى يستاهل XP (حتى ما حد ياخد XP وهو لحاله بروم فاضي)
                real_members = [m for m in vc.members if not m.bot]
                if len(real_members) < 2:
                    continue
                for member in real_members:
                    if member.voice and (member.voice.self_deaf or member.voice.deaf):
                        continue
                    if no_xp_roles and any(r.id in no_xp_roles for r in member.roles):
                        continue
                    await Storage.add_xp(guild.id, member.id, "voice_xp", per_minute)

    @voice_xp_task.before_loop
    async def before_voice_xp_task(self):
        await self.bot.wait_until_ready()

    # ---------------- تصفير عدّادات اليوم/الأسبوع ----------------

    @tasks.loop(minutes=5)
    async def period_reset_task(self):
        for guild in self.bot.guilds:
            await Storage.reset_period_counters_if_needed(guild.id)

    @period_reset_task.before_loop
    async def before_period_reset_task(self):
        await self.bot.wait_until_ready()

    # ---------------- /set-up-xp ----------------

    @app_commands.command(name="set-up-xp", description="إعداد نظام الـ XP والمستويات")
    @app_commands.describe(
        xp_min="أقل XP ممكن ياخده الشخص من رسالة فيها محتوى حقيقي (الحساب ذكي مو عشوائي)",
        xp_max="أكتر XP ممكن ياخده الشخص من رسالة واحدة (حتى لو كانت طويلة كتير)",
        cooldown_seconds="كم ثانية لازم تعدي قبل ما ياخد XP تاني (حماية من السبام)",
        voice_xp_per_minute="كم XP ياخد الشخص كل دقيقة متصل بالفويس (0 = تعطيل XP الفويس)",
        levelup_channel="روم إشعارات اللفل أب (اختياري - إذا تركته فاضي بيرد بنفس الروم)",
        log_channel="قناة اللوق (اختياري)",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_xp(
        self,
        interaction: discord.Interaction,
        xp_min: int,
        xp_max: int,
        cooldown_seconds: int,
        voice_xp_per_minute: int = 2,
        levelup_channel: discord.TextChannel = None,
        log_channel: discord.TextChannel = None,
    ):
        if xp_min <= 0 or xp_max <= 0 or xp_min > xp_max:
            await interaction.response.send_message("❌ تأكد إنه xp_min أقل من أو يساوي xp_max وأكبر من صفر.", ephemeral=True)
            return
        if cooldown_seconds < 0 or voice_xp_per_minute < 0:
            await interaction.response.send_message("❌ ما فيه أي رقم يكون سالب.", ephemeral=True)
            return

        await Storage.update_guild(interaction.guild.id, "xp", {
            "xp_min": xp_min,
            "xp_max": xp_max,
            "cooldown_seconds": cooldown_seconds,
            "levelup_channel_id": levelup_channel.id if levelup_channel else None,
            "log_channel_id": log_channel.id if log_channel else None,
        })
        await Storage.update_guild(interaction.guild.id, "voice_xp", {"xp_per_minute": voice_xp_per_minute})

        embed = branded_embed(title="✅ تم إعداد نظام الـ XP", color=discord.Color.green())
        embed.add_field(name="حدود XP بالرسالة", value=f"{xp_min} - {xp_max} (محسوبة ذكياً حسب طول ومحتوى الرسالة)", inline=True)
        embed.add_field(name="الكولداون", value=f"{cooldown_seconds} ثانية", inline=True)
        embed.add_field(name="XP الفويس", value=f"{voice_xp_per_minute} / دقيقة" if voice_xp_per_minute else "معطّل", inline=True)
        embed.add_field(name="روم اللفل أب", value=levelup_channel.mention if levelup_channel else "نفس روم الرسالة", inline=True)
        embed.add_field(name="قناة اللوق", value=log_channel.mention if log_channel else "—", inline=True)
        embed.add_field(
            name="ℹ️ ملاحظة",
            value="لإضافة رتبة مكافأة عند مستوى معين، استخدم `/set-xp-role-reward`.\nلاستثناء رومات من الاحتساب، استخدم `/channel-dont-add-xp`.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_xp.error
    async def set_up_xp_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- /set-xp-role-reward ----------------

    @app_commands.command(name="set-xp-role-reward", description="ربط رتبة معينة بمستوى XP (تُعطى تلقائياً عند الوصول)")
    @app_commands.describe(level="رقم المستوى", role="الرتبة يلي بدك تنعطى تلقائياً عند هاد المستوى")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_xp_role_reward(self, interaction: discord.Interaction, level: int, role: discord.Role):
        if level <= 0:
            await interaction.response.send_message("❌ رقم المستوى لازم يكون أكبر من صفر.", ephemeral=True)
            return
        conf = await Storage.get_guild(interaction.guild.id)
        rewards = dict(conf["xp"]["role_rewards"])
        rewards[str(level)] = role.id
        await Storage.update_guild(interaction.guild.id, "xp", {"role_rewards": rewards})
        await interaction.response.send_message(
            f"✅ تم ربط رتبة {role.mention} بالمستوى {level}.", ephemeral=True
        )

    @set_xp_role_reward.error
    async def set_xp_role_reward_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- /channel-dont-add-xp ----------------

    @app_commands.command(name="channel-dont-add-xp", description="حدد رومات ما بينحسب فيها XP (كتابة ولا فويس) - حتى 10 رومات")
    @app_commands.describe(
        channel_1="أول روم", channel_2="روم 2", channel_3="روم 3", channel_4="روم 4", channel_5="روم 5",
        channel_6="روم 6", channel_7="روم 7", channel_8="روم 8", channel_9="روم 9", channel_10="روم 10",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def channel_dont_add_xp(
        self,
        interaction: discord.Interaction,
        channel_1: Union[discord.TextChannel, discord.VoiceChannel],
        channel_2: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_3: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_4: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_5: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_6: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_7: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_8: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_9: Union[discord.TextChannel, discord.VoiceChannel] = None,
        channel_10: Union[discord.TextChannel, discord.VoiceChannel] = None,
    ):
        channels = [c for c in [
            channel_1, channel_2, channel_3, channel_4, channel_5,
            channel_6, channel_7, channel_8, channel_9, channel_10,
        ] if c is not None]
        channel_ids = [c.id for c in channels]

        await Storage.update_guild(interaction.guild.id, "xp", {"no_xp_channel_ids": channel_ids})

        embed = branded_embed(title="✅ تم تحديث رومات استثناء الـ XP", color=discord.Color.green())
        embed.description = "ما رح ينحسب أي XP (كتابة أو فويس) بهاي الرومات:\n" + "\n".join(c.mention for c in channels)
        embed.add_field(
            name="ℹ️ ملاحظة",
            value="هاد الأمر بيستبدل القائمة القديمة بالكامل - لو بدك تضيف روم جديد، أعد كتابة كل الرومات مع بعض.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @channel_dont_add_xp.error
    async def channel_dont_add_xp_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- /add-xp ----------------

    @app_commands.command(name="add-xp", description="أضف (أو اسحب برقم سالب) XP كتابة لشخص يدوياً")
    @app_commands.describe(member="الشخص", amount="كمية الـ XP (فيك تحط رقم سالب حتى تسحب)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def add_xp_slash(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        entry = await Storage.get_xp_user(interaction.guild.id, member.id)
        new_total = max(0, entry.get("xp", 0) + amount)
        result = await Storage.set_xp_user(interaction.guild.id, member.id, new_total)

        await interaction.response.send_message(
            f"✅ تم تعديل XP تبع {member.mention}: صار عنده {new_total} XP (مستوى {result['level']}).",
            allowed_mentions=discord.AllowedMentions.none(),
        )

        # لو في مهمة فعّالة، هاد بيغذي تقدّمها وبيخلي البوت يعرف تلقائياً لو المهمة ترقية أو نقاط
        # (نفس المنطق الذكي المستخدم مع الرسائل العادية - شوف quest_system.py)
        if amount > 0:
            self.bot.dispatch("xp_awarded", interaction.guild, member, amount, "xp")

    @add_xp_slash.error
    async def add_xp_slash_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- رانك ----------------

    @commands.command(name="رانك", aliases=["مستوى", "لفل"])
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def rank_cmd(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        entry = await Storage.get_xp_user(ctx.guild.id, member.id)
        xp = entry.get("xp", 0)
        level = entry.get("level", 0)
        current_floor = xp_needed_for_level(level)
        next_floor = xp_needed_for_level(level + 1)
        into_level = xp - current_floor
        needed = next_floor - current_floor

        board = await Storage.get_leaderboard(ctx.guild.id, "xp", "all")
        position = next((i + 1 for i, (uid, _) in enumerate(board) if uid == member.id), None)

        embed = branded_embed(title=f"📊 رانك {member.display_name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="المستوى", value=str(level), inline=True)
        embed.add_field(name="XP الكلي", value=str(xp), inline=True)
        embed.add_field(name="الترتيب", value=f"#{position}" if position else "—", inline=True)
        embed.add_field(name="التقدم للمستوى الجاي", value=f"{into_level} / {needed}", inline=False)
        await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @rank_cmd.error
    async def rank_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    # ---------------- $top (ليدربورد بصفحات: يوم/أسبوع/الكل × كتابة/فويس) ----------------

    @commands.command(name="$top")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def top_cmd(self, ctx: commands.Context, arg1: str = None, arg2: str = None):
        usage = (
            "استخدم الأمر هيك:\n"
            "`$top text` / `$top day text` / `$top week text`\n"
            "`$top voice` / `$top day voice` / `$top week voice`"
        )
        period, ttype = self._parse_top_args(arg1, arg2)
        if period is None:
            await ctx.reply(usage)
            return

        bucket = "xp" if ttype == "text" else "voice_xp"
        board = await Storage.get_leaderboard(ctx.guild.id, bucket, period)
        if not board:
            await ctx.reply("ℹ️ ما في بيانات كفاية لعرض هاي القائمة لسا.")
            return

        view = LeaderboardView(board, ctx.guild, bucket, period, ctx.author.id)
        await ctx.reply(embed=view.make_embed(), view=view)

    @staticmethod
    def _parse_top_args(arg1: str, arg2: str):
        """بترجع (period, type) أو (None, None) لو الصيغة غلط."""
        periods = {"day": "day", "week": "week"}
        types = {"text": "text", "voice": "voice"}

        if arg1 in periods and arg2 in types:
            return periods[arg1], types[arg2]
        if arg1 in types and arg2 is None:
            return "all", types[arg1]
        return None, None

    @top_cmd.error
    async def top_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    # ---------------- توب / ليدربورد (نص قديم مبسّط) ----------------

    @commands.command(name="توب", aliases=["ليدربورد"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def leaderboard_cmd(self, ctx: commands.Context):
        board = await Storage.get_leaderboard(ctx.guild.id, "xp", "all")
        if not board:
            await ctx.reply("ℹ️ ما في حدا كسب XP لسا بهاد السيرفر.")
            return
        view = LeaderboardView(board, ctx.guild, "xp", "all", ctx.author.id)
        await ctx.reply(embed=view.make_embed(), view=view)

    @leaderboard_cmd.error
    async def leaderboard_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")

    # ---------------- أوامر إدارية: اعطي-اكسبي (نصي) ----------------

    @commands.command(name="اعطي-اكسبي")
    @commands.guild_only()
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def give_xp_cmd(self, ctx: commands.Context, member: discord.Member = None, amount: int = None):
        if member is None or amount is None:
            await ctx.reply("استخدم الأمر هيك: `اعطي-اكسبي @شخص 100` (أو استخدم `/add-xp`)")
            return
        if not ctx.author.guild_permissions.administrator and ctx.author.id != ctx.guild.owner_id:
            return
        entry = await Storage.get_xp_user(ctx.guild.id, member.id)
        new_total = max(0, entry.get("xp", 0) + amount)
        result = await Storage.set_xp_user(ctx.guild.id, member.id, new_total)
        await ctx.reply(
            f"✅ تم تعديل XP تبع {member.display_name}: {new_total} XP (مستوى {result['level']})",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if amount > 0:
            self.bot.dispatch("xp_awarded", ctx.guild, member, amount, "xp")

    @give_xp_cmd.error
    async def give_xp_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")


async def setup(bot: commands.Bot):
    await bot.add_cog(XPSystem(bot))
