import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta

from utils.storage import Storage
from utils.checks import (
    SilentPermissionCheck,
    can_target,
    has_role,
    has_any_role,
    collect_roles,
    bot_missing_permissions,
)
from utils.embeds import branded_embed

DURATIONS = [
    ("5 دقائق", "5m", 5 * 60),
    ("10 دقائق", "10m", 10 * 60),
    ("30 دقيقة", "30m", 30 * 60),
    ("ساعة", "1h", 60 * 60),
    ("ساعتين", "2h", 2 * 60 * 60),
    ("3 ساعات", "3h", 3 * 60 * 60),
    ("4 ساعات", "4h", 4 * 60 * 60),
    ("5 ساعات", "5h", 5 * 60 * 60),
    ("6 ساعات", "6h", 6 * 60 * 60),
    ("10 ساعات", "10h", 10 * 60 * 60),
    ("12 ساعة", "12h", 12 * 60 * 60),
    ("يوم", "1d", 24 * 60 * 60),
    ("يومين", "2d", 2 * 24 * 60 * 60),
    ("3 أيام", "3d", 3 * 24 * 60 * 60),
    ("4 أيام", "4d", 4 * 24 * 60 * 60),
    ("5 أيام", "5d", 5 * 24 * 60 * 60),
    ("6 أيام", "6d", 6 * 24 * 60 * 60),
    ("7 أيام", "7d", 7 * 24 * 60 * 60),
]


async def check_timeout_permission(ctx: commands.Context) -> bool:
    """Check access before discord.py parses any command arguments."""
    if ctx.guild is None:
        return True

    conf = await Storage.get_guild(ctx.guild.id)
    time_config = conf["time"]
    is_admin = has_role(ctx.author, time_config["admin_role_id"])
    is_giver = has_any_role(ctx.author, time_config["giver_role_ids"])

    if not time_config["giver_role_ids"] or not (is_admin or is_giver):
        raise SilentPermissionCheck()

    return True


class ReasonModal(discord.ui.Modal, title="سبب التايم أوت"):
    reason = discord.ui.TextInput(
        label="ليش بدك تعطي هاد الشخص تايم أوت؟",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True,
    )

    def __init__(self, flow: "TimeoutFlow"):
        super().__init__()
        self.flow = flow

    async def on_submit(self, interaction: discord.Interaction):
        self.flow.reason = str(self.reason)
        # ما عاد في خطوة تأكيد/إلغاء - أول ما يكتب السبب بينفذ التايم أوت فوراً
        await self.flow.execute(interaction)


class DurationSelect(discord.ui.Select):
    def __init__(self, flow: "TimeoutFlow"):
        options = [discord.SelectOption(label=label, value=code) for label, code, _ in DURATIONS]
        super().__init__(placeholder="اختر مدة التايم أوت", options=options, min_values=1, max_values=1)
        self.flow = flow

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        code = self.values[0]
        seconds = next(s for _, c, s in DURATIONS if c == code)
        self.flow.duration_code = code
        self.flow.duration_seconds = seconds
        await interaction.response.send_modal(ReasonModal(self.flow))


class DurationView(discord.ui.View):
    def __init__(self, flow: "TimeoutFlow"):
        super().__init__(timeout=120)
        self.flow = flow
        self.add_item(DurationSelect(flow))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        try:
            await self.flow.message.edit(content="⌛ انتهت مهلة الأمر.", embed=None, view=None)
        except Exception:
            pass


class TimeoutFlow:
    def __init__(self, cog: "TimeSystem", ctx: commands.Context, target: discord.Member, is_unlimited: bool):
        self.cog = cog
        self.ctx = ctx
        self.invoker = ctx.author
        self.target = target
        self.is_unlimited = is_unlimited
        self.duration_code = None
        self.duration_seconds = None
        self.reason = None
        self.message = None

    async def start(self):
        embed = branded_embed(
            title="⏱️ إعطاء تايم أوت",
            description=f"الهدف: {self.target.mention}\nاختر المدة من القائمة تحت 👇",
            color=discord.Color.blurple(),
        )
        self.message = await self.ctx.reply(embed=embed, view=DurationView(self))

    async def execute(self, interaction: discord.Interaction):
        guild = self.ctx.guild

        # إعادة فحص الصلاحية والتسلسل الهرمي وقت التنفيذ (مو بس وقت بداية الأمر)
        fresh_invoker = guild.get_member(self.invoker.id)
        fresh_target = guild.get_member(self.target.id)
        if fresh_invoker is None or fresh_target is None:
            await interaction.response.edit_message(content="❌ أحد الطرفين ما عاد موجود بالسيرفر.", embed=None, view=None)
            return

        conf = await Storage.get_guild(guild.id)
        t = conf["time"]
        is_admin = has_role(fresh_invoker, t["admin_role_id"])
        is_giver = has_any_role(fresh_invoker, t["giver_role_ids"])
        if not (is_admin or is_giver):
            # ما عاد معه صلاحية - ما منرد عليه بأي رسالة
            await interaction.response.defer()
            return

        ok, msg = can_target(fresh_invoker, fresh_target)
        if not ok:
            await interaction.response.edit_message(content=f"❌ {msg}", embed=None, view=None)
            return

        self.is_unlimited = is_admin
        self.target = fresh_target

        missing = bot_missing_permissions(guild, "moderate_members")
        if missing:
            await interaction.response.edit_message(
                content=f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}", embed=None, view=None
            )
            return

        until = discord.utils.utcnow() + timedelta(seconds=self.duration_seconds)

        # الرسالة الخاصة أولاً، وبعدها التنفيذ الفعلي
        try:
            dm_embed = branded_embed(title="🔇 اكلت تايم", color=discord.Color.red())
            dm_embed.add_field(name="السبب", value=self.reason, inline=False)
            dm_embed.add_field(name="المدة", value=self.duration_code, inline=False)
            await self.target.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        try:
            await self.target.timeout(until, reason=self.reason)
        except discord.Forbidden:
            await interaction.response.edit_message(
                content="❌ ما قدرت أعطي التايم أوت. تأكد إنه رتبة البوت أعلى من رتبة الشخص.",
                embed=None, view=None,
            )
            return

        if not self.is_unlimited:
            await Storage.increment_usage(guild.id, "time", self.invoker.id)

        await Storage.set_timeout_giver(guild.id, self.target.id, self.invoker.id)

        await interaction.response.edit_message(
            content=f"✅ تم إعطاء {self.target.mention} تايم أوت لمدة **{self.duration_code}**",
            embed=None, view=None,
        )

        await self.cog.send_log(guild, "time", {
            "العملية": "🔇 إعطاء تايم",
            "بواسطة": self.invoker.mention,
            "الهدف": self.target.mention,
            "المدة": self.duration_code,
            "السبب": self.reason,
        })


class TimeSystem(commands.Cog):
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

    # ---------------- /set-up-time ----------------

    @app_commands.command(name="set-up-time", description="إعداد نظام التايم أوت")
    @app_commands.describe(
        giver_role_1="أول رتبة تقدر تعطي تايم أوت",
        daily_limit="أقصى عدد تايمات يومياً لهاي الرتب",
        admin_role="رتبة الأدمن (تايم غير محدود)",
        log_channel="قناة اللوق",
        giver_role_2="رتبة ثانية اختيارية",
        giver_role_3="رتبة ثالثة اختيارية",
        giver_role_4="رتبة رابعة اختيارية",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_time(
        self,
        interaction: discord.Interaction,
        giver_role_1: discord.Role,
        daily_limit: int,
        admin_role: discord.Role,
        log_channel: discord.TextChannel,
        giver_role_2: discord.Role = None,
        giver_role_3: discord.Role = None,
        giver_role_4: discord.Role = None,
    ):
        role_ids = collect_roles(giver_role_1, giver_role_2, giver_role_3, giver_role_4)
        await Storage.update_guild(interaction.guild.id, "time", {
            "giver_role_ids": role_ids,
            "daily_limit": daily_limit,
            "admin_role_id": admin_role.id,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام التايم", color=discord.Color.green())
        embed.add_field(name="رتب معطي التايم", value=", ".join(f"<@&{i}>" for i in role_ids))
        embed.add_field(name="الحد اليومي", value=str(daily_limit))
        embed.add_field(name="رتبة الأدمن (غير محدود)", value=admin_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_time.error
    async def set_up_time_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- تايم ----------------

    @commands.command(name="تايم")
    @commands.check(check_timeout_permission)
    @commands.guild_only()
    async def timeout_cmd(self, ctx: commands.Context, member: discord.Member = None):
        if member is None:
            await ctx.reply("استخدم الأمر هيك: `تايم @شخص`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        t = conf["time"]
        if not t["giver_role_ids"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-time` أول.")
            return

        is_admin = has_role(ctx.author, t["admin_role_id"])
        is_giver = has_any_role(ctx.author, t["giver_role_ids"])
        if not (is_admin or is_giver):
            return

        ok, msg = can_target(ctx.author, member)
        if not ok:
            await ctx.reply(f"❌ {msg}")
            return

        if not is_admin and t["daily_limit"]:
            used = await Storage.get_usage(ctx.guild.id, "time", ctx.author.id)
            if used >= t["daily_limit"]:
                await ctx.reply(f"❌ وصلت للحد الأقصى من التايم اليوم ({t['daily_limit']}).")
                return

        flow = TimeoutFlow(self, ctx, member, is_unlimited=is_admin)
        await flow.start()


async def setup(bot: commands.Bot):
    await bot.add_cog(TimeSystem(bot))
