import discord
from discord.ext import commands

from utils.embeds import branded_embed

HELP_ROLE_NAME = "ستريتر"

COMMAND_GROUPS = [
    ("🎭 الرتب", [
        ("$رتب @شخص", "تعديل رتب شخص (اختيار من قائمة)"),
        ("$رول @شخص id_الرتبة", "إعطاء/شيل رتبة محددة (toggle)"),
        ("$ترقية @شخص عدد", "ترقية بعدد رتب معين"),
        ("$تخفيض @شخص عدد", "تخفيض بعدد رتب معين"),
    ]),
    ("🛡️ الإدارة", [
        ("$باند @شخص [السبب]", "باند شخص"),
        ("$تايم @شخص", "تايم أوت شخص"),
        ("$ان @شخص", "إلغاء التايم أوت عن شخص"),
        ("$نك @شخص الاسم", "تغيير نك شخص جوا السيرفر"),
        ("$تحذير @شخص", "تحذير شخص (بيسألك عن السبب)"),
        ("$شيل @شخص", "شيل تحذير عن شخص"),
        ("$rar @شخص", "شيل كل رتب شخص دفعة وحدة"),
        ("$ف [#قناة]", "قفل القناة"),
        ("$ق [#قناة]", "فتح القناة"),
        ("$مسح عدد", "مسح رسائل"),
    ]),
    ("⚙️ الإعداد (أدمن بس)", [
        ("/set-up-role", "إعداد $رتب"),
        ("/set-up-roles", "إعداد $رول"),
        ("/set-up-add-role", "إعداد $ترقية"),
        ("/set-up-remove-role", "إعداد $تخفيض"),
        ("/set-up-ban", "إعداد $باند"),
        ("/set-up-time", "إعداد $تايم"),
        ("/set-up-unmute", "إعداد $ان"),
        ("/set-up-rar", "إعداد $rar"),
        ("/set-up-nickname", "إعداد $نك"),
        ("/set-up-warn", "إعداد $تحذير"),
        ("/set-up-unwarn", "إعداد $شيل"),
        ("/set-up-lock", "إعداد $ف"),
        ("/set-up-unlock", "إعداد $ق"),
        ("/set-up-clear", "إعداد $مسح"),
        ("/set-up-reply", "إعداد الردود التلقائية"),
        ("/set-up-security ...", "إعداد نظام الحماية (5 أوامر فرعية)"),
        ("/set-up-embed ...", "بناء قوائم إمبد تفاعلية"),
    ]),
]


class HelpSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="help")
    @commands.guild_only()
    async def help_cmd(self, ctx: commands.Context):
        is_streeter = any(r.name == HELP_ROLE_NAME for r in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if not (is_streeter or is_admin):
            await ctx.reply(f"❌ هاد الأمر بس لصاحب صلاحية أدمن أو رتبة {HELP_ROLE_NAME}.")
            return

        embed = branded_embed(title="📖 كل أوامر البوت", color=discord.Color.blurple())
        for group_name, commands_list in COMMAND_GROUPS:
            value = "\n".join(f"`{cmd}` — {desc}" for cmd, desc in commands_list)
            embed.add_field(name=group_name, value=value, inline=False)
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpSystem(bot))
