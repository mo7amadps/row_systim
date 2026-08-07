import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True          # ضروري لأوامر الرتب والباند والتايم
intents.message_content = True  # ضروري حتى يشتغل $تايم / $باند / $رتب / $ان
if hasattr(intents, "moderation"):
    intents.moderation = True   # ضروري حتى تشتغل مراقبة سجل الأحداث (Audit Log) لنظام الحماية

bot = commands.Bot(command_prefix="$", intents=intents, help_command=None)

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
]


@bot.event
async def on_ready():
    print(f"✅ سجل الدخول كـ {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 تمت مزامنة {len(synced)} أمر سلاش")
    except Exception as e:
        print(f"⚠️ فشلت مزامنة الأوامر: {e}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")
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
        for cog in INITIAL_COGS:
            await bot.load_extension(cog)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
