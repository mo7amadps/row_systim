import os
import asyncio
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from utils.checks import SilentPermissionCheck
from utils.storage import Storage

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True          # ضروري لأوامر الرتب والباند والتايم
intents.message_content = True  # ضروري حتى تشتغل تايم / باند / رتب / ان / سجن ...
if hasattr(intents, "moderation"):
    intents.moderation = True   # ضروري حتى تشتغل مراقبة سجل الأحداث (Audit Log) لنظام الحماية

# ما عاد في بادئة (زي $) قبل الأوامر - كل الأوامر تنكتب مباشرة باسمها
# (مثال: "باند @شخص" بدل "$باند @شخص"). خلي بالك: هيك أي رسالة نصها
# بيطابق تماماً اسم أمر (زي كلمة "سجن" لحالها) رح تشغّل الأمر.
bot = commands.Bot(command_prefix=commands.when_mentioned_or(""), intents=intents, help_command=None)

# --- إصلاح خطأ "Unknown message" (كود 50035) ---
# لما رسالة الأمر الأصلية تنشال (تنحذف) قبل ما البوت يرد عليها (مثلاً بوت حماية/سلو مود/أنتي سبام
# تاني شالها، أو المستخدم حذفها بنفسه)، ctx.reply() بيفشل لأنه بيحاول يعمل "رد" على رسالة ما عادت موجودة.
# هلق منلف ctx.reply بحيث لو صار هاد الخطأ بالذات، منرجع نبعت رسالة عادية (ctx.send) بدل ما نكسر الأمر بالكامل.
_original_context_reply = commands.Context.reply


async def _safe_context_reply(self: commands.Context, *args, **kwargs):
    try:
        return await _original_context_reply(self, *args, **kwargs)
    except discord.HTTPException as e:
        if getattr(e, "code", None) == 50035:
            kwargs.pop("mention_author", None)
            kwargs.pop("reference", None)
            return await self.send(*args, **kwargs)
        raise


commands.Context.reply = _safe_context_reply

INITIAL_COGS = [
    "cogs.time_system",
    "cogs.role_system",
    "cogs.ban_system",
    "cogs.security_system",
    "cogs.rank_system",
    "cogs.reply_system",
    "cogs.moderation_system",
    "cogs.role_assign",
    "cogs.embed_panel",
    "cogs.broadcast_system",
    "cogs.help_system",
    "cogs.unmute_system",
    "cogs.unban_system",
    "cogs.channel_utils",
    "cogs.prison_system",
    "cogs.role_all_system",
    "cogs.tiered_staff_system",
    "cogs.dismiss_system",
    "cogs.xp_system",
    "cogs.quest_system",
    "cogs.dashboard_system",
    "cogs.mention_tracker",
]


@bot.event
async def on_ready():
    print(f"✅ سجل الدخول كـ {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 تمت مزامنة {len(synced)} أمر سلاش")
    except Exception as e:
        print(f"⚠️ فشلت مزامنة الأوامر: {e}")
    if not periodic_backup_task.is_running():
        periodic_backup_task.start()


@tasks.loop(minutes=15)
async def periodic_backup_task():
    """
    نسخة احتياطية دورية لكل إعدادات البوت (JSON) - حماية إضافية فوق الحفظ الذري
    الموجود أصلاً بـ utils/storage.py. لو الملف الرئيسي انعطب أو انمسح لأي سبب
    (تعطل مفاجئ، مشكلة قرص، إلخ)، البوت بيسترجع تلقائياً من آخر نسخة سليمة
    أول ما يحاول يقرأ الإعدادات - بدون أي تدخل يدوي.
    """
    try:
        await Storage.backup_now()
    except Exception as e:
        print(f"⚠️ فشلت النسخة الاحتياطية الدورية: {e}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")
    elif isinstance(error, SilentPermissionCheck):
        # The command intentionally stays completely silent for unauthorized users.
        pass
    elif isinstance(error, commands.CommandNotFound):
        pass  # نتجاهل أي أمر غير موجود
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية قبل ما تعيد الأمر.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ تأكد من كتابة الأمر صح.")
    else:
        # قبل كده أي خطأ غير متوقع (زي HTTPException أو أي Exception ثاني) كان بس
        # يتطبع بالـ console وما كان يوصل أي رد للمستخدم، فكان يبين إنه الأمر "ما اشتغل"
        # من غير ما يبين ليش. هلق منرد رسالة واضحة بالإضافة للطباعة بالـ console.
        original = getattr(error, "original", error)
        print(f"خطأ غير متوقع بأمر {ctx.command}: {original!r}")
        try:
            await ctx.reply("❌ صار خطأ غير متوقع وأنا عم أنفذ الأمر. جرب مرة ثانية، ولو تكرر بلغ الأدمن.")
        except discord.HTTPException:
            pass


async def main():
    async with bot:
        await Storage.initialize()
        for cog in INITIAL_COGS:
            await bot.load_extension(cog)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
