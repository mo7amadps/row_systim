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
    ]),
    ("🛡️ الإدارة", [
        ("باند @شخص [السبب]", "باند شخص"),
        ("فك-الباند آيدي_الشخص", "فك الباند عن شخص"),
        ("تايم @شخص", "تايم أوت شخص (بينفذ فوراً بعد ما تكتب السبب)"),
        ("ان @شخص", "إلغاء التايم أوت عن شخص"),
        ("نك @شخص الاسم", "تغيير نك شخص جوا السيرفر (فيك تغيّر نكك أنت بحرية)"),
        ("تحذير @شخص", "تحذير شخص (بيسألك عن السبب)"),
        ("شيل @شخص", "شيل تحذير عن شخص"),
        ("$rar @شخص", "شيل كل رتب شخص دفعة وحدة"),
        ("ف [#قناة]", "فتح القناة"),
        ("ق [#قناة]", "قفل القناة"),
        ("مسح عدد", "مسح رسائل"),
        ("سجن @شخص [السبب]", "يشيل كل رتب/رومات الشخص ويحطه بروم السجن للأبد"),
        ("انسجن @شخص", "فك السجن عن شخص وإرجاع رتبه القديمة"),
        ("فك السجن @شخص", "نفس أمر انسجن (صيغة بديلة)"),
    ]),
    ("⚙️ الإعداد (أدمن بس)", [
        ("/set-up-role", "إعداد رتب"),
        ("/set-up-roles", "إعداد رول"),
        ("/set-up-add-role", "إعداد ترقية"),
        ("/set-up-remove-role", "إعداد تخفيض"),
        ("/set-up-ban", "إعداد باند"),
        ("/set-up-time", "إعداد تايم"),
        ("/set-up-unmute", "إعداد ان"),
        ("/set-up-unban", "إعداد فك-الباند"),
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

        embed = branded_embed(title="📖 كل أوامر البوت", color=discord.Color.blurple())
        for group_name, commands_list in COMMAND_GROUPS:
            value = "\n".join(f"`{cmd}` — {desc}" for cmd, desc in commands_list)
            embed.add_field(name=group_name, value=value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpSystem(bot))
