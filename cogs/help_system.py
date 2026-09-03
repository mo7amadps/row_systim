import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import branded_embed

HELP_ROLE_NAME = "ستريتر"

COMMAND_GROUPS = [
    ("🎭 الرتب", [
        ("رتب @شخص", "تعديل رتب شخص (اختيار من قائمة)"),
        ("رول @شخص id_الرتبة", "إعطاء/شيل رتبة محددة (toggle)"),
        ("ترقية @شخص عدد", "ترقية بعدد رتب معين"),
        ("تخفيض @شخص عدد", "تخفيض بعدد رتب معين"),
        ("/role-all", "إعطاء رتبة للكل / الأعضاء بس / البوتات بس"),
        ("صغرى @شخص [رقم]", "تعيين صغرى برتبة معينة (بدون رقم = رتبة 1) + رتبة تكتات تلقائياً"),
        ("عليا @شخص [رقم]", "نفس مبدأ صغرى لسلسلة العليا"),
        ("اونر @شخص [رقم]", "نفس مبدأ صغرى لسلسلة الاونر"),
        ("مفصول @شخص", "يشيل كل رتب الشخص يلي فوق الرتبة المحمية المُعدة"),
    ]),
    ("🛡️ الإدارة", [
        ("باند @شخص أو آيدي [السبب]", "باند شخص (فوري - فيك تباند حتى لو مش بالسيرفر). أسماء بديلة: بانكاي، لف، تفو، زحلق"),
        ("فك-الباند آيدي_الشخص", "فك الباند عن شخص"),
        ("تايم @شخص", "تايم أوت شخص (فوري بعد ما تكتب السبب). أسماء بديلة: اص، اسكت"),
        ("ان @شخص", "إلغاء التايم أوت عن شخص"),
        ("نك @شخص الاسم", "تغيير نك شخص جوا السيرفر (فيك تغيّر نكك أنت بحرية)"),
        ("تحذير @شخص", "تحذير شخص (بيسألك عن السبب). اسم بديل: ت"),
        ("شيل @شخص", "شيل تحذير عن شخص"),
        ("$rar @شخص", "شيل كل رتب شخص دفعة وحدة"),
        ("ف [#قناة]", "فتح القناة"),
        ("ق [#قناة]", "قفل القناة"),
        ("مسح عدد", "مسح رسائل"),
        ("سجن @شخص [السبب]", "يشيل كل رتب/رومات الشخص ويحطه بروم السجن للأبد"),
        ("انسجن @شخص", "فك السجن عن شخص وإرجاع رتبه القديمة"),
        ("فك السجن @شخص", "نفس أمر انسجن (صيغة بديلة)"),
    ]),
    ("⭐ نظام XP والمستويات", [
        ("رانك [@شخص]", "عرض المستوى والـXP (أسماء بديلة: مستوى، لفل)"),
        ("توب", "أفضل 10 بالـXP (كتابة، كل الوقت)"),
        ("$top text", "أفضل المتفاعلين بالكتابة - كل الوقت"),
        ("$top day text", "أفضل المتفاعلين بالكتابة - اليوم"),
        ("$top week text", "أفضل المتفاعلين بالكتابة - الأسبوع"),
        ("$top voice", "أفضل المتفاعلين بالفويس - كل الوقت"),
        ("$top day voice", "أفضل المتفاعلين بالفويس - اليوم"),
        ("$top week voice", "أفضل المتفاعلين بالفويس - الأسبوع"),
        ("اعطي-اكسبي @شخص عدد", "إضافة/سحب XP يدوياً (نص) - أو استخدم /add-xp"),
        ("/add-xp", "إضافة/سحب XP يدوياً (سلاش) - مربوط بالمهام تلقائياً"),
        ("/set-up-xp", "إعداد نظام XP (حدود الرسالة، الفويس، الكولداون، اللوق)"),
        ("/set-xp-role-reward", "ربط رتبة مكافأة بمستوى معين"),
        ("/channel-dont-add-xp", "استثناء لغاية 10 رومات من احتساب XP"),
    ]),
    ("📜 نظام المهام التلقائي", [
        ("مهام صغرى / عليا / اونر", "نشر مهمة جديدة (قائمة تفاعلية لاختيار النوع، وقت النشر، وكمية الـXP)"),
        ("مهام الكل", "حالة كل تصنيفات المهام دفعة وحدة"),
        ("مهام وقف صغرى/عليا/اونر", "إيقاف مهمة شغالة أو مجدولة"),
        ("مهام عدل صغرى/عليا/اونر", "تعديل هدف الـXP (والوقت لو لسا مجدولة)"),
        ("مهام تقدم صغرى/عليا/اونر [@شخص]", "تقدّمك أو تقدّم شخص تاني بالمهمة الحالية"),
        ("مهام تاريخ صغرى/عليا/اونر", "آخر 10 مهمات مكتملة/متوقفة/منتهية"),
        ("/set-up-quest-staff", "إعداد نظام مهام صغرى (رتب مسموحة، لوق، أول وآخر رتبة)"),
        ("/set-up-quest-highstaff", "إعداد نظام مهام عليا"),
        ("/set-up-quest-owner", "إعداد نظام مهام اونر"),
    ]),
    ("⚙️ الإعداد (أدمن بس)", [
        ("اعدادات", "داشبورد يلخص كل إعدادات البوت بصفحات (اسم بديل: داشبورد)"),
        ("/dashboard", "نفس أمر اعدادات (سلاش)"),
        ("/set-up-role", "إعداد رتب"),
        ("/set-up-roles", "إعداد رول"),
        ("/set-up-add-role", "إعداد ترقية"),
        ("/set-up-remove-role", "إعداد تخفيض"),
        ("/set-up-ban", "إعداد باند"),
        ("/set-up-time", "إعداد تايم"),
        ("/set-up-unmute", "إعداد ان"),
        ("/set-up-unban", "إعداد فك-الباند"),
        ("/set-up-staff", "إعداد نظام staff"),
        ("/set-up-highstaff", "إعداد نظام highstaff"),
        ("/set-up-owner", "إعداد نظام owner"),
        ("/set-up-مفصول", "إعداد أمر مفصول"),
        ("/set-up-rar", "إعداد rar"),
        ("/set-up-nickname", "إعداد نك"),
        ("/set-up-warn", "إعداد تحذير"),
        ("/set-up-unwarn", "إعداد شيل"),
        ("/set-up-lock", "إعداد ق"),
        ("/set-up-unlock", "إعداد ف"),
        ("/set-up-clear", "إعداد مسح"),
        ("/set-up-prison", "إعداد نظام السجن (سجن / انسجن)"),
        ("/set-up-reply", "إعداد الردود التلقائية"),
        ("/set-up-security ...", "إعداد نظام الحماية (5 أوامر فرعية)"),
        ("/set-up-embed ...", "بناء قوائم إمبد تفاعلية"),
            ("/send-broadcast-panel", "نشر لوحة تحكم البرودكاست"),
            ("!bc الرسالة", "إرسال البرودكاست للجميع"),
            ("!obc الرسالة", "إرسال البرودكاست للأعضاء المتصلين"),
    ]),
]


class HelpSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="عرض كل أوامر البوت")
    @app_commands.guild_only()
    async def help_cmd(self, interaction: discord.Interaction):
        is_streeter = any(r.name == HELP_ROLE_NAME for r in interaction.user.roles)
        is_admin = interaction.user.guild_permissions.administrator
        if not (is_streeter or is_admin):
            return

        embeds = []
        for group_name, commands_list in COMMAND_GROUPS:
            embed = branded_embed(title=f"📖 أوامر البوت — {group_name}", color=discord.Color.blurple())
            value = "\n".join(f"`{cmd}` — {desc}" for cmd, desc in commands_list)
            # الحد الأقصى لطول قيمة الحقل بالإمبد 1024 حرف - نقسم لو تجاوزنا
            chunks = [value]
            if len(value) > 1024:
                lines = value.split("\n")
                chunks = []
                current = ""
                for line in lines:
                    if len(current) + len(line) + 1 > 1024:
                        chunks.append(current)
                        current = line
                    else:
                        current = f"{current}\n{line}" if current else line
                if current:
                    chunks.append(current)
            for i, chunk in enumerate(chunks):
                field_name = group_name if i == 0 else "‌"
                embed.add_field(name=field_name, value=chunk, inline=False)
            embeds.append(embed)

        view = HelpView(embeds, interaction.user.id)
        await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=True)

    @commands.command(name="اوامر", aliases=["الاوامر"])
    @commands.guild_only()
    async def help_text_cmd(self, ctx: commands.Context):
        is_streeter = any(r.name == HELP_ROLE_NAME for r in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if not (is_streeter or is_admin):
            return
        await ctx.reply("استخدم `/help` لعرض كل أوامر البوت بصفحات.")


class HelpView(discord.ui.View):
    def __init__(self, embeds: list, author_id: int):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.author_id = author_id
        self.page = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= len(self.embeds) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ بس يلي طلب الهلب فيه يتصفح الصفحات.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(len(self.embeds) - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpSystem(bot))

