import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.embeds import branded_embed, CREDITS_TEXT


def _parse_color(color_str: str):
    if not color_str:
        return discord.Color.blurple().value
    s = color_str.strip().lstrip("#")
    try:
        return int(s, 16)
    except ValueError:
        return discord.Color.blurple().value


def _build_main_embed(panel: dict) -> discord.Embed:
    embed = discord.Embed(
        title=panel.get("title") or None,
        description=panel.get("description") or None,
        color=panel.get("color", discord.Color.blurple().value),
    )
    if panel.get("image_url"):
        embed.set_image(url=panel["image_url"])
    embed.set_footer(text=CREDITS_TEXT)
    return embed


def _build_option_embed(option: dict) -> discord.Embed:
    embed = branded_embed(
        title=option.get("title") or option.get("label"),
        description=option.get("text") or None,
        color=discord.Color.blurple(),
    )
    if option.get("image_url"):
        embed.set_image(url=option["image_url"])
    return embed


class PanelSelect(discord.ui.Select):
    def __init__(self, guild_id: int, panel_id: str, options: list):
        self.guild_id = guild_id
        self.panel_id = panel_id
        select_options = [
            discord.SelectOption(
                label=o["label"],
                description=(o.get("title") or "")[:100] or None,
                value=o["label"],
            )
            for o in options
        ]
        super().__init__(
            placeholder="اختر من هون 👇",
            options=select_options,
            min_values=1,
            max_values=1,
            custom_id=f"embed_panel_select:{panel_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        # نجيب البانل من التخزين طازة كل مرة، فأي تعديل عالمحتوى بينعكس فوراً من غير ما تحتاج تعيد النشر
        panel = await Storage.get_embed_panel(self.guild_id, self.panel_id)
        if not panel:
            await interaction.response.send_message("❌ هاد النظام ما عاد موجود.", ephemeral=True)
            return
        option = next((o for o in panel.get("options", []) if o["label"] == self.values[0]), None)
        if not option:
            await interaction.response.send_message("❌ هاد الخيار ما عاد موجود.", ephemeral=True)
            return
        await interaction.response.send_message(embed=_build_option_embed(option), ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self, guild_id: int, panel_id: str, options: list):
        super().__init__(timeout=None)
        if options:
            self.add_item(PanelSelect(guild_id, panel_id, options))


class EmbedPanelSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # نسجل الـ Views الدائمة من جديد لكل البانلات الموجودة بكل السيرفرات
        # حتى القوائم المنشورة قبل إعادة تشغيل البوت تضل شغالة
        panels = await Storage.iter_all_panels()
        for guild_id, panel_id, panel_data in panels:
            options = panel_data.get("options", [])
            if options:
                self.bot.add_view(PanelView(guild_id, panel_id, options))

    group = app_commands.Group(name="set-up-embed", description="نظام بناء قوائم إمبد تفاعلية")

    @group.command(name="create", description="أنشئ بانل إمبد جديد (أقصى شي 5 بانلات بالسيرفر)")
    @app_commands.describe(
        name="اسم مختصر للبانل (بالإنجليزي أفضل، بدون مسافات) - مش هو العنوان الظاهر",
        title="عنوان الإمبد الظاهر",
        description="نص الإمبد",
        image="صورة اختيارية تنحط بالإمبد",
        color="لون الإمبد بصيغة هيكس زي #00ff00 (اختياري)",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def create_cmd(
        self, interaction: discord.Interaction, name: str, title: str, description: str,
        image: discord.Attachment = None, color: str = None
    ):
        panel_data = {
            "title": title[:256],
            "description": description[:4000],
            "image_url": image.url if image else None,
            "color": _parse_color(color),
            "options": [],
        }
        result = await Storage.create_embed_panel(interaction.guild.id, name, panel_data)
        if result == "duplicate":
            await interaction.response.send_message(f"❌ فيه بانل اسمه `{name}` أصلاً. اختار اسم تاني أو احذف القديم.", ephemeral=True)
            return
        if result == "limit":
            await interaction.response.send_message(f"❌ وصلت أقصى عدد بانلات ({Storage.MAX_PANELS_PER_GUILD}). احذف وحدة قديمة أول.", ephemeral=True)
            return
        embed = branded_embed(title="✅ تم إنشاء البانل", color=discord.Color.green())
        embed.add_field(name="الاسم", value=f"`{name}`")
        embed.add_field(name="الخطوة الجاية", value=f"ضيف خيارات بـ `/set-up-embed add-option` (أقصى شي {Storage.MAX_OPTIONS_PER_PANEL})", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="add-option", description="ضيف خيار (سطر بالقائمة المنسدلة) لبانل موجود")
    @app_commands.describe(
        panel="اسم البانل",
        label="اسم الخيار الظاهر بالقائمة (أقصى شي 25 حرف)",
        response_title="عنوان الرسالة يلي بتطلع لما يختاروه",
        response_text="نص الرسالة يلي بتطلع لما يختاروه",
        response_image="صورة اختيارية تنحط برسالة هاد الخيار",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def add_option_cmd(
        self, interaction: discord.Interaction, panel: str, label: str, response_title: str,
        response_text: str, response_image: discord.Attachment = None
    ):
        if len(label) > 25:
            await interaction.response.send_message("❌ اسم الخيار طويل، أقصى شي 25 حرف (حد ديسكورد للقوائم المنسدلة).", ephemeral=True)
            return
        option = {
            "label": label,
            "title": response_title[:256],
            "text": response_text[:4000],
            "image_url": response_image.url if response_image else None,
        }
        result = await Storage.add_embed_option(interaction.guild.id, panel, option)
        if result == "not_found":
            await interaction.response.send_message(f"❌ ما في بانل اسمه `{panel}`. شوف `/set-up-embed list`.", ephemeral=True)
            return
        if result == "duplicate":
            await interaction.response.send_message(f"❌ فيه خيار اسمه `{label}` أصلاً بهاد البانل.", ephemeral=True)
            return
        if result == "limit":
            await interaction.response.send_message(f"❌ البانل وصل أقصى عدد خيارات ({Storage.MAX_OPTIONS_PER_PANEL}).", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ تمت إضافة الخيار `{label}` لبانل `{panel}`.\n"
            f"إذا كان منشور قبل هيك، لازم تعيد `/set-up-embed publish` حتى يظهر الخيار الجديد بالقائمة.",
            ephemeral=True,
        )

    @group.command(name="remove-option", description="شيل خيار من بانل")
    @app_commands.describe(panel="اسم البانل", label="اسم الخيار يلي بدك تشيله")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_option_cmd(self, interaction: discord.Interaction, panel: str, label: str):
        removed = await Storage.remove_embed_option(interaction.guild.id, panel, label)
        if not removed:
            await interaction.response.send_message("❌ ما لقيت هاد الخيار بهاد البانل.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ تم شيل `{label}`. لو البانل منشور، أعد `/set-up-embed publish` حتى يتحدث شكل القائمة.", ephemeral=True
        )

    @group.command(name="delete", description="احذف بانل بالكامل")
    @app_commands.describe(panel="اسم البانل")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_cmd(self, interaction: discord.Interaction, panel: str):
        removed = await Storage.delete_embed_panel(interaction.guild.id, panel)
        if not removed:
            await interaction.response.send_message(f"❌ ما في بانل اسمه `{panel}`.", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ تم حذف البانل `{panel}` من التخزين (الرسائل المنشورة قبل هيك ما رح تشتغل بعدها).", ephemeral=True)

    @group.command(name="list", description="شوف كل البانلات وخياراتها")
    @app_commands.guild_only()
    async def list_cmd(self, interaction: discord.Interaction):
        panels = await Storage.list_embed_panels(interaction.guild.id)
        if not panels:
            await interaction.response.send_message("ℹ️ ما في ولا بانل لسا. استخدم `/set-up-embed create`.", ephemeral=True)
            return
        embed = branded_embed(title="📋 بانلات الإمبد", color=discord.Color.blue())
        for name, p in panels.items():
            option_labels = ", ".join(o["label"] for o in p.get("options", [])) or "(ولا خيار لسا)"
            embed.add_field(name=f"`{name}` — {p.get('title', '')}", value=option_labels, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="publish", description="انشر البانل برسالة بقناة معينة")
    @app_commands.describe(panel="اسم البانل", channel="القناة يلي بدك تنشر فيها")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def publish_cmd(self, interaction: discord.Interaction, panel: str, channel: discord.TextChannel):
        panel_data = await Storage.get_embed_panel(interaction.guild.id, panel)
        if not panel_data:
            await interaction.response.send_message(f"❌ ما في بانل اسمه `{panel}`.", ephemeral=True)
            return
        if not panel_data.get("options"):
            await interaction.response.send_message("❌ لازم تضيف خيار وحد ع الأقل قبل النشر (`/set-up-embed add-option`).", ephemeral=True)
            return

        embed = _build_main_embed(panel_data)
        view = PanelView(interaction.guild.id, panel, panel_data["options"])
        try:
            await channel.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.response.send_message("❌ ما قدرت أنشر بهاي القناة، تأكد من صلاحيات البوت فيها.", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ تم نشر البانل `{panel}` بقناة {channel.mention}", ephemeral=True)

    @create_cmd.error
    @add_option_cmd.error
    @remove_option_cmd.error
    @delete_cmd.error
    @publish_cmd.error
    async def group_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedPanelSystem(bot))
