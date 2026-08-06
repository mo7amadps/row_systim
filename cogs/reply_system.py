import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.embeds import branded_embed

MAX_SLOTS = 50
PAGE_SIZE = 25  # أقصى عدد خيارات مسموح بيها ديسكورد بكل قائمة منسدلة واحدة


class ReplyModal(discord.ui.Modal, title="إعداد رد تلقائي"):
    def __init__(self, guild_id: int, slot_number: str, existing: dict = None):
        super().__init__()
        self.guild_id = guild_id
        self.slot_number = slot_number

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
        await Storage.set_reply_slot(self.guild_id, self.slot_number, trigger, reply_text)

        embed = branded_embed(title=f"✅ تم حفظ خانة {self.slot_number}", color=discord.Color.green())
        embed.add_field(name="الكلمة", value=trigger, inline=False)
        embed.add_field(name="الرد", value=reply_text, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)


class SlotSelect(discord.ui.Select):
    def __init__(self, guild_id: int, slots: dict, page: int):
        start = page * PAGE_SIZE + 1
        end = min(start + PAGE_SIZE - 1, MAX_SLOTS)
        options = []
        for i in range(start, end + 1):
            existing = slots.get(str(i))
            label = f"خانة {i}" + (f" - {existing['trigger']}" if existing else " (فاضية)")
            options.append(discord.SelectOption(label=label[:100], value=str(i)))
        super().__init__(placeholder=f"اختار رقم الخانة لتعديلها ({start}-{end})", options=options)
        self.guild_id = guild_id
        self.slots = slots

    async def callback(self, interaction: discord.Interaction):
        slot_number = self.values[0]
        existing = self.slots.get(slot_number)
        await interaction.response.send_modal(ReplyModal(self.guild_id, slot_number, existing))


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

    @app_commands.command(name="set-up-reply", description="إعداد نظام الردود التلقائية")
    @app_commands.describe(trigger_role="الرتبة يلي لازم تكون مع الشخص حتى البوت يرد عليه (اختياري لو ما بدك تغييرها)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_reply(self, interaction: discord.Interaction, trigger_role: discord.Role = None):
        if trigger_role is not None:
            await Storage.update_guild(interaction.guild.id, "auto_reply", {"trigger_role_id": trigger_role.id})

        conf = await Storage.get_guild(interaction.guild.id)
        slots = conf["auto_reply"]["slots"]
        role_id = conf["auto_reply"]["trigger_role_id"]

        embed = branded_embed(title="🛠️ إعداد الردود التلقائية", color=discord.Color.blurple())
        embed.add_field(
            name="الرتبة المفعّلة (بس أصحابها بياخدوا رد)",
            value=f"<@&{role_id}>" if role_id else "❌ ما تم تحديدها بعد",
            inline=False,
        )
        embed.add_field(name="اختار رقم من القائمة تحت لتعديل الكلمة والرد", value=f"1 لحد {MAX_SLOTS}", inline=False)

        await interaction.response.send_message(
            embed=embed,
            view=SlotPanelView(interaction.guild.id, slots, interaction.user.id),
            ephemeral=True,
        )

    @set_up_reply.error
    async def set_up_reply_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- الاستماع للرسائل وإطلاق الرد ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        conf = await Storage.get_guild(message.guild.id)
        cfg = conf["auto_reply"]
        role_id = cfg["trigger_role_id"]
        if not role_id:
            return
        if not any(r.id == role_id for r in message.author.roles):
            return

        content = message.content.strip()
        if not content:
            return

        for slot in cfg["slots"].values():
            if slot.get("trigger", "").strip() == content:
                try:
                    await message.reply(slot.get("reply", ""))
                except discord.Forbidden:
                    pass
                return


async def setup(bot: commands.Bot):
    await bot.add_cog(ReplySystem(bot))
