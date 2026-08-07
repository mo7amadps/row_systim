import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import can_target, has_role, bot_missing_permissions
from utils.embeds import branded_embed


class BanReasonModal(discord.ui.Modal, title="سبب الباند"):
    reason = discord.ui.TextInput(
        label="ليش بدك تبند هاد الشخص؟",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True,
    )

    def __init__(self, flow: "BanFlow"):
        super().__init__()
        self.flow = flow

    async def on_submit(self, interaction: discord.Interaction):
        self.flow.reason = str(self.reason)
        await self.flow.show_are_you_sure(interaction)


class StartView(discord.ui.View):
    def __init__(self, flow: "BanFlow"):
        super().__init__(timeout=120)
        self.flow = flow

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📝 اكتب السبب", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        await interaction.response.send_modal(BanReasonModal(self.flow))

    async def on_timeout(self):
        try:
            await self.flow.message.edit(content="⌛ انتهت مهلة الأمر.", embed=None, view=None)
        except Exception:
            pass


class AreYouSureView(discord.ui.View):
    def __init__(self, flow: "BanFlow"):
        super().__init__(timeout=60)
        self.flow = flow

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        await self.flow.show_confirm(interaction)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        await interaction.response.edit_message(content="❌ تم الإلغاء.", embed=None, view=None)


class ConfirmView(discord.ui.View):
    def __init__(self, flow: "BanFlow"):
        super().__init__(timeout=60)
        self.flow = flow

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="تأكيد نهائي ✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        await self.flow.execute(interaction)


class BanFlow:
    def __init__(self, cog: "BanSystem", ctx: commands.Context, target: discord.Member, is_unlimited: bool):
        self.cog = cog
        self.ctx = ctx
        self.invoker = ctx.author
        self.target = target
        self.is_unlimited = is_unlimited
        self.reason = None
        self.message = None

    async def start(self):
        embed = branded_embed(
            title="🔨 باند",
            description=f"الهدف: {self.target.mention}\nاضغط الزر تحت حتى تكتب السبب 👇",
            color=discord.Color.dark_red(),
        )
        self.message = await self.ctx.reply(embed=embed, view=StartView(self))

    async def show_are_you_sure(self, interaction: discord.Interaction):
        embed = branded_embed(title="⚠️ Are You Sure?", color=discord.Color.orange())
        embed.add_field(name="الشخص", value=self.target.mention, inline=False)
        embed.add_field(name="السبب", value=self.reason, inline=False)
        await interaction.response.edit_message(embed=embed, view=AreYouSureView(self))

    async def show_confirm(self, interaction: discord.Interaction):
        embed = branded_embed(title="⚠️ تأكيد نهائي", color=discord.Color.red())
        embed.add_field(name="الشخص", value=self.target.mention, inline=False)
        embed.add_field(name="السبب", value=self.reason, inline=False)
        embed.set_footer(text="هاد آخر تأكيد قبل التنفيذ")
        await interaction.response.edit_message(embed=embed, view=ConfirmView(self))

    async def execute(self, interaction: discord.Interaction):
        guild = self.ctx.guild

        # إعادة فحص الصلاحية والتسلسل الهرمي وقت التنفيذ (مو بس وقت بداية الأمر)
        fresh_invoker = guild.get_member(self.invoker.id)
        fresh_target = guild.get_member(self.target.id)
        if fresh_invoker is None or fresh_target is None:
            await interaction.response.edit_message(content="❌ أحد الطرفين ما عاد موجود بالسيرفر.", embed=None, view=None)
            return

        conf = await Storage.get_guild(guild.id)
        b = conf["ban"]
        is_unlimited = has_role(fresh_invoker, b["unlimited_role_id"])
        is_allowed = has_role(fresh_invoker, b["allowed_role_id"])
        if not (is_unlimited or is_allowed):
            await interaction.response.edit_message(content="❌ ما عاد معك صلاحية تنفيذ هاد الأمر.", embed=None, view=None)
            return

        ok, msg = can_target(fresh_invoker, fresh_target)
        if not ok:
            await interaction.response.edit_message(content=f"❌ {msg}", embed=None, view=None)
            return

        self.is_unlimited = is_unlimited
        self.target = fresh_target

        missing = bot_missing_permissions(guild, "ban_members")
        if missing:
            await interaction.response.edit_message(
                content=f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}", embed=None, view=None
            )
            return

        # الرسالة الخاصة أولاً، وبعدها الباند فعلياً
        try:
            dm_embed = branded_embed(title="🔨 تم تبنيدك", color=discord.Color.red())
            dm_embed.add_field(name="السبب", value=self.reason, inline=False)
            await self.target.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        try:
            await guild.ban(self.target, reason=self.reason, delete_message_seconds=0)
        except discord.Forbidden:
            await interaction.response.edit_message(
                content="❌ ما قدرت أبند الشخص، تأكد إنه رتبة البوت أعلى من رتبته.",
                embed=None, view=None,
            )
            return

        if not self.is_unlimited:
            await Storage.increment_usage(guild.id, "ban", self.invoker.id)

        await interaction.response.edit_message(
            content=f"✅ تم باند {self.target.mention}", embed=None, view=None
        )

        await self.cog.send_log(guild, "ban", {
            "العملية": "🔨 باند",
            "بواسطة": self.invoker.mention,
            "الهدف": f"{self.target} ({self.target.id})",
            "السبب": self.reason,
        })


class BanSystem(commands.Cog):
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

    # ---------------- /set-up-ban ----------------

    @app_commands.command(name="set-up-ban", description="إعداد نظام الباند")
    @app_commands.describe(
        allowed_role="الرتبة يلي تقدر تستخدم أمر الباند",
        daily_limit="أقصى عدد باندات يومياً لهاي الرتبة",
        unlimited_role="رتبة باند لا نهائي (بدون حد يومي)",
        log_channel="قناة اللوق",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_ban(
        self,
        interaction: discord.Interaction,
        allowed_role: discord.Role,
        daily_limit: int,
        unlimited_role: discord.Role,
        log_channel: discord.TextChannel,
    ):
        await Storage.update_guild(interaction.guild.id, "ban", {
            "allowed_role_id": allowed_role.id,
            "daily_limit": daily_limit,
            "unlimited_role_id": unlimited_role.id,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام الباند", color=discord.Color.green())
        embed.add_field(name="الرتبة المسموحة", value=allowed_role.mention)
        embed.add_field(name="الحد اليومي", value=str(daily_limit))
        embed.add_field(name="رتبة باند لا نهائي", value=unlimited_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_ban.error
    async def set_up_ban_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- $باند ----------------

    @commands.command(name="باند")
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)  # كولداون 10 ثواني بين كل باند
    async def ban_cmd(self, ctx: commands.Context, member: discord.Member = None):
        if member is None:
            await ctx.reply("استخدم الأمر هيك: `$باند @شخص`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        b = conf["ban"]
        if not b["allowed_role_id"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-ban` أول.")
            return

        is_unlimited = has_role(ctx.author, b["unlimited_role_id"])
        is_allowed = has_role(ctx.author, b["allowed_role_id"])
        if not (is_unlimited or is_allowed):
            await ctx.reply("❌ ما معك صلاحية تستخدم هاد الأمر.")
            return

        ok, msg = can_target(ctx.author, member)
        if not ok:
            await ctx.reply(f"❌ {msg}")
            return

        if not is_unlimited and b["daily_limit"]:
            used = await Storage.get_usage(ctx.guild.id, "ban", ctx.author.id)
            if used >= b["daily_limit"]:
                await ctx.reply(f"❌ وصلت للحد الأقصى من الباند اليوم ({b['daily_limit']}).")
                return

        flow = BanFlow(self, ctx, member, is_unlimited=is_unlimited)
        await flow.start()

    @ban_cmd.error
    async def ban_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى شوي، فيك تعمل باند تاني بعد {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")


async def setup(bot: commands.Bot):
    await bot.add_cog(BanSystem(bot))
