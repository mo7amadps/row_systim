import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.embeds import branded_embed

MAX_SLOTS = 50
PAGE_SIZE = 25  # أقصى عدد خيارات مسموح بيها ديسكورد بكل قائمة منسدلة واحدة


class ReplyModal(discord.ui.Modal, title="✏️ إعداد رد تلقائي"):
    def __init__(self, guild_id: int, slot_number: str, role_id: int, existing: dict = None):
        super().__init__()
        self.guild_id = guild_id
        self.slot_number = slot_number
        self.role_id = role_id

        self.trigger_input = discord.ui.TextInput(
            label="الكلمة (لما حد يكتبها بالظبط)",
            default=(existing or {}).get("trigger", ""),
            max_length=100,
            required=True,
        )
        self.reply_input = discord.ui.TextInput(
            label="الرد",
            style=discord.TextStyle.paragraph,
            default=(existing or {}).get("reply", ""),
            max_length=1000,
            required=True,
        )
        self.add_item(self.trigger_input)
        self.add_item(self.reply_input)

    async def on_submit(self, interaction: discord.Interaction):
        trigger = str(self.trigger_input).strip()
        reply_text = str(self.reply_input).strip()
        await Storage.set_reply_slot(self.guild_id, self.slot_number, trigger, reply_text, self.role_id)

        embed = branded_embed(
            title=f"✅ تم حفظ خانة {self.slot_number}",
            color=discord.Color.green(),
            description="هاد الرد صار شغال، وخاص بس بالرتبة يلي اخترتها لهاد الخانة.",
        )
        embed.add_field(name="🎭 الرتبة المفعّلة لهاد الرد", value=f"<@&{self.role_id}>", inline=False)
        embed.add_field(name="💬 الكلمة", value=f"```{trigger}```", inline=False)
        embed.add_field(name="↩️ الرد", value=reply_text, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)


class RoleStepView(discord.ui.View):
    """خطوة اختيار الرتبة الخاصة بهاد الرد قبل ما نفتح المودال."""

    def __init__(self, guild_id: int, slot_number: str, invoker_id: int, existing: dict = None):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.slot_number = slot_number
        self.invoker_id = invoker_id
        self.existing = existing or {}

        current_role_id = self.existing.get("role_id")
        default_values = [discord.Object(id=current_role_id)] if current_role_id else []

        role_select = discord.ui.RoleSelect(
            placeholder="🎭 اختار الرتبة يلي رح تفعّل هاد الرد",
            min_values=1,
            max_values=1,
            default_values=default_values,
        )
        role_select.callback = self._on_role_selected
        self.add_item(role_select)

        if current_role_id:
            keep_btn = discord.ui.Button(
                label="متابعة بنفس الرتبة الحالية",
                style=discord.ButtonStyle.secondary,
                emoji="↪️",
            )
            keep_btn.callback = self._on_keep_current
            self.add_item(keep_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    async def _on_role_selected(self, interaction: discord.Interaction):
        role = interaction.data["values"][0]
        await interaction.response.send_modal(
            ReplyModal(self.guild_id, self.slot_number, int(role), self.existing)
        )

    async def _on_keep_current(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            ReplyModal(self.guild_id, self.slot_number, self.existing["role_id"], self.existing)
        )


class SlotSelect(discord.ui.Select):
    def __init__(self, guild_id: int, slots: dict, page: int):
        start = page * PAGE_SIZE + 1
        end = min(start + PAGE_SIZE - 1, MAX_SLOTS)
        options = []
        for i in range(start, end + 1):
            existing = slots.get(str(i))
            if existing:
                label = f"🟢 خانة {i} - {existing.get('trigger', '')}"
            else:
                label = f"⚪ خانة {i} (فاضية)"
            options.append(discord.SelectOption(label=label[:100], value=str(i)))
        super().__init__(placeholder=f"📋 اختار رقم الخانة لتعديلها ({start}-{end})", options=options)
        self.guild_id = guild_id
        self.slots = slots

    async def callback(self, interaction: discord.Interaction):
        slot_number = self.values[0]
        existing = self.slots.get(slot_number)

        embed = branded_embed(
            title=f"🎭 الخطوة 1: رتبة الخانة {slot_number}",
            color=discord.Color.blurple(),
            description=(
                "حدد الرتبة يلي بدها تفعّل هاد الرد بالذات (مستقلة تماماً عن باقي الخانات)، "
                "وبعدها رح تفتحلك نافذة تكتب فيها الكلمة والرد."
            ),
        )
        if existing and existing.get("role_id"):
            embed.add_field(name="الرتبة الحالية لهاد الخانة", value=f"<@&{existing['role_id']}>", inline=False)

        await interaction.response.edit_message(
            embed=embed,
            view=RoleStepView(self.guild_id, slot_number, interaction.user.id, existing),
        )


class SlotPanelView(discord.ui.View):
    def __init__(self, guild_id: int, slots: dict, invoker_id: int, page: int = 0):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.slots = slots
        self.invoker_id = invoker_id
        self.page = page
        self.max_page = (MAX_SLOTS - 1) // PAGE_SIZE  # آخر رقم صفحة (تبدأ من 0)

        self.add_item(SlotSelect(guild_id, slots, page))

        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀ السابق", style=discord.ButtonStyle.secondary, disabled=(page == 0))
            next_btn = discord.ui.Button(label="التالي ▶", style=discord.ButtonStyle.secondary, disabled=(page == self.max_page))
            prev_btn.callback = self._make_page_callback(page - 1)
            next_btn.callback = self._make_page_callback(page + 1)
            self.add_item(prev_btn)
            self.add_item(next_btn)

    def _make_page_callback(self, target_page: int):
        async def callback(interaction: discord.Interaction):
            new_view = SlotPanelView(self.guild_id, self.slots, self.invoker_id, target_page)
            await interaction.response.edit_message(view=new_view)
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True


class ReplySystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- /set-up-reply ----------------

    @app_commands.command(name="set-up-reply", description="إعداد نظام الردود التلقائية (كل رد برتبته الخاصة)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_reply(self, interaction: discord.Interaction):
        conf = await Storage.get_guild(interaction.guild.id)
        slots = conf["auto_reply"]["slots"]

        configured = sum(1 for s in slots.values() if s.get("trigger"))

        embed = branded_embed(
            title="✨ إعداد نظام الردود التلقائية",
            color=discord.Color.blurple(),
            description=(
                "كل خانة (رد) عندها **رتبتها الخاصة فيها لحالها** — ممكن رد يشتغل بس لرتبة "
                "الأونر، ورد تاني يشتغل بس لرتبة تانية، بدون ما تأثر على بعض إطلاقاً."
            ),
        )
        embed.add_field(name="📦 خانات مفعّلة حالياً", value=f"**{configured}** من أصل {MAX_SLOTS}", inline=True)
        embed.add_field(name="🧭 كيف تضيف رد", value="اختار رقم خانة تحت ⬇️", inline=True)
        embed.set_footer(text="discord.gg/row  •  نظام الردود التلقائية")

        await interaction.response.send_message(
            embed=embed,
            view=SlotPanelView(interaction.guild.id, slots, interaction.user.id),
            ephemeral=True,
        )

    @set_up_reply.error
    async def set_up_reply_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return

    # ---------------- الاستماع للرسائل وإطلاق الرد ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        conf = await Storage.get_guild(message.guild.id)
        slots = conf["auto_reply"]["slots"]
        if not slots:
            return

        content = message.content.strip()
        if not content:
            return

        author_role_ids = {r.id for r in message.author.roles}

        for slot in slots.values():
            role_id = slot.get("role_id")
            if not role_id or role_id not in author_role_ids:
                continue
            if slot.get("trigger", "").strip() == content:
                try:
                    await message.reply(slot.get("reply", ""))
                except discord.Forbidden:
                    pass
                return


async def setup(bot: commands.Bot):
    await bot.add_cog(ReplySystem(bot))
