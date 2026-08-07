import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_role, assignable_roles, bot_missing_permissions
from utils.embeds import branded_embed

ROLES_PER_PAGE = 25


class RoleEditSession:
    def __init__(self, cog: "RoleSystem", ctx: commands.Context, target: discord.Member):
        self.cog = cog
        self.ctx = ctx
        self.invoker = ctx.author
        self.target = target
        self.message = None

        all_assignable = assignable_roles(ctx.author, ctx.guild)
        self.roles = all_assignable
        self.pages = [self.roles[i:i + ROLES_PER_PAGE] for i in range(0, len(self.roles), ROLES_PER_PAGE)] or [[]]
        self.current_page = 0

        assignable_ids = {r.id for r in self.roles}
        # الرتب المختارة حالياً (نبدأ من الرتب يلي الشخص عنده أصلاً من ضمن الرتب القابلة للتعديل)
        self.selected = {r.id for r in target.roles if r.id in assignable_ids}
        self.original = set(self.selected)

    async def start(self):
        if not self.roles:
            await self.ctx.reply("ℹ️ ما في أي رتب فيك تتحكم فيها حالياً.")
            return None
        embed = self.build_embed()
        self.message = await self.ctx.reply(embed=embed, view=RolePageView(self))
        return self.message

    def build_embed(self):
        embed = branded_embed(
            title="🎭 تعديل الرتب",
            description=f"الهدف: {self.target.mention}\nصفحة {self.current_page + 1} من {len(self.pages)}",
            color=discord.Color.blurple(),
        )
        selected_roles = [self.ctx.guild.get_role(rid) for rid in self.selected]
        selected_roles = [r for r in selected_roles if r]
        embed.add_field(
            name="الرتب المختارة حالياً",
            value=", ".join(r.mention for r in selected_roles) if selected_roles else "لا شي",
            inline=False,
        )
        return embed


class RoleMultiSelect(discord.ui.Select):
    def __init__(self, session: RoleEditSession):
        self.session = session
        page_roles = session.pages[session.current_page]
        options = [
            discord.SelectOption(
                label=role.name[:100],
                value=str(role.id),
                default=(role.id in session.selected),
            )
            for role in page_roles
        ]
        super().__init__(
            placeholder="اختر الرتب (تقدر تختار أكتر من وحدة)",
            options=options,
            min_values=0,
            max_values=len(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return

        page_role_ids = {r.id for r in self.session.pages[self.session.current_page]}
        chosen_ids = {int(v) for v in self.values}

        # نحدّث بس الرتب يلي بهاي الصفحة، ونحافظ على اختيارات الصفحات الثانية
        self.session.selected -= page_role_ids
        self.session.selected |= chosen_ids

        await interaction.response.edit_message(embed=self.session.build_embed(), view=RolePageView(self.session))


class RolePageView(discord.ui.View):
    def __init__(self, session: RoleEditSession):
        super().__init__(timeout=180)
        self.session = session
        self.add_item(RoleMultiSelect(session))

        prev_btn = discord.ui.Button(label="◀ السابقة", style=discord.ButtonStyle.secondary,
                                      disabled=(session.current_page == 0), row=1)
        next_btn = discord.ui.Button(label="التالية ▶", style=discord.ButtonStyle.secondary,
                                      disabled=(session.current_page >= len(session.pages) - 1), row=1)
        confirm_btn = discord.ui.Button(label="تأكيد ✅", style=discord.ButtonStyle.success, row=1)
        cancel_btn = discord.ui.Button(label="إلغاء ❌", style=discord.ButtonStyle.danger, row=1)

        prev_btn.callback = self.go_prev
        next_btn.callback = self.go_next
        confirm_btn.callback = self.confirm
        cancel_btn.callback = self.cancel

        self.add_item(prev_btn)
        self.add_item(next_btn)
        self.add_item(confirm_btn)
        self.add_item(cancel_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    async def _check_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    async def go_prev(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        self.session.current_page -= 1
        await interaction.response.edit_message(embed=self.session.build_embed(), view=RolePageView(self.session))

    async def go_next(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        self.session.current_page += 1
        await interaction.response.edit_message(embed=self.session.build_embed(), view=RolePageView(self.session))

    async def confirm(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return

        to_add = self.session.selected - self.session.original
        to_remove = self.session.original - self.session.selected

        if not to_add and not to_remove:
            await interaction.response.edit_message(content="ℹ️ ما في أي تغيير.", embed=None, view=None)
            return

        guild = self.session.ctx.guild
        add_names = [guild.get_role(rid).mention for rid in to_add if guild.get_role(rid)]
        remove_names = [guild.get_role(rid).mention for rid in to_remove if guild.get_role(rid)]

        embed = branded_embed(title="⚠️ Are You Sure?", color=discord.Color.orange())
        embed.add_field(name="الشخص", value=self.session.target.mention, inline=False)
        embed.add_field(name="رتب رح تنضاف", value=", ".join(add_names) if add_names else "لا شي", inline=False)
        embed.add_field(name="رتب رح تنشال", value=", ".join(remove_names) if remove_names else "لا شي", inline=False)

        await interaction.response.edit_message(embed=embed, view=FinalConfirmView(self.session, to_add, to_remove))

    async def cancel(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        await interaction.response.edit_message(content="❌ تم الإلغاء.", embed=None, view=None)


class FinalConfirmView(discord.ui.View):
    def __init__(self, session: RoleEditSession, to_add: set, to_remove: set):
        super().__init__(timeout=60)
        self.session = session
        self.to_add = to_add
        self.to_remove = to_remove

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes، احفظ التغييرات", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return

        guild = self.session.ctx.guild
        target = guild.get_member(self.session.target.id)
        fresh_invoker = guild.get_member(interaction.user.id)

        if target is None or fresh_invoker is None:
            await interaction.response.edit_message(content="❌ أحد الطرفين ما عاد موجود بالسيرفر.", embed=None, view=None)
            return

        conf = await Storage.get_guild(guild.id)
        r = conf["role"]
        if not has_role(fresh_invoker, r["allowed_role_id"]) and fresh_invoker.id != guild.owner_id:
            await interaction.response.edit_message(content="❌ ما عاد معك صلاحية تنفيذ هاد الأمر.", embed=None, view=None)
            return

        # نعيد حساب الرتب المتاحة من الصفر وقت الحفظ (مو الحسبة القديمة وقت بداية الأمر)
        # حتى لو تغيّرت رتبة fresh_invoker أو رتبة البوت أثناء الانتظار
        still_assignable_ids = {role.id for role in assignable_roles(fresh_invoker, guild)}
        blocked_add = self.to_add - still_assignable_ids
        blocked_remove = self.to_remove - still_assignable_ids
        if blocked_add or blocked_remove:
            await interaction.response.edit_message(
                content="❌ صلاحياتك أو صلاحيات البوت تغيّرت أثناء الانتظار، أعد الأمر من جديد.",
                embed=None, view=None,
            )
            return

        missing = bot_missing_permissions(guild, "manage_roles")
        if missing:
            await interaction.response.edit_message(
                content=f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}", embed=None, view=None
            )
            return

        add_roles = [guild.get_role(rid) for rid in self.to_add if guild.get_role(rid)]
        remove_roles = [guild.get_role(rid) for rid in self.to_remove if guild.get_role(rid)]

        try:
            if add_roles:
                await target.add_roles(*add_roles, reason=f"تعديل رتب بواسطة {interaction.user}")
            if remove_roles:
                await target.remove_roles(*remove_roles, reason=f"تعديل رتب بواسطة {interaction.user}")
        except discord.Forbidden:
            await interaction.response.edit_message(
                content="❌ ما قدرت أعدل الرتب، تأكد إنه رتبة البوت أعلى من هاي الرتب.",
                embed=None, view=None,
            )
            return

        await interaction.response.edit_message(content="✅ تم حفظ التغييرات بنجاح.", embed=None, view=None)

        await self.session.cog.send_log(guild, "role", {
            "العملية": "🎭 تعديل رتب",
            "بواسطة": interaction.user.mention,
            "الهدف": target.mention,
            "انضاف": ", ".join(r.mention for r in add_roles) if add_roles else "لا شي",
            "انشال": ", ".join(r.mention for r in remove_roles) if remove_roles else "لا شي",
        })

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        await interaction.response.edit_message(content="❌ تم الإلغاء.", embed=None, view=None)


class RoleSystem(commands.Cog):
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

    # ---------------- /set-up-role ----------------

    @app_commands.command(name="set-up-role", description="إعداد نظام تعديل الرتب")
    @app_commands.describe(
        allowed_role="الرتبة يلي تقدر تستخدم أمر تعديل الرتب",
        log_channel="قناة اللوق",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_role(
        self,
        interaction: discord.Interaction,
        allowed_role: discord.Role,
        log_channel: discord.TextChannel,
    ):
        await Storage.update_guild(interaction.guild.id, "role", {
            "allowed_role_id": allowed_role.id,
            "log_channel_id": log_channel.id,
        })
        embed = branded_embed(title="✅ تم إعداد نظام الرتب", color=discord.Color.green())
        embed.add_field(name="الرتبة المسموحة", value=allowed_role.mention)
        embed.add_field(name="قناة اللوق", value=log_channel.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @set_up_role.error
    async def set_up_role_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- $رتب ----------------

    @commands.command(name="رتب")
    @commands.guild_only()
    async def role_cmd(self, ctx: commands.Context, member: discord.Member = None):
        if member is None:
            await ctx.reply("استخدم الأمر هيك: `$رتب @شخص`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        r = conf["role"]
        if not r["allowed_role_id"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-role` أول.")
            return

        if not has_role(ctx.author, r["allowed_role_id"]) and ctx.author.id != ctx.guild.owner_id:
            await ctx.reply("❌ ما معك صلاحية تستخدم هاد الأمر.")
            return

        if member.id == ctx.guild.owner_id and ctx.author.id != ctx.guild.owner_id:
            await ctx.reply("❌ ما فيك تعدل رتب صاحب السيرفر.")
            return

        session = RoleEditSession(self, ctx, member)
        await session.start()


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleSystem(bot))
