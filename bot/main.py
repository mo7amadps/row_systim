import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Bot is ready and operational!")

@bot.event
async def on_command_error(ctx, error):
    # Ignore permission errors gracefully without sending error noise
    if isinstance(error, (commands.MissingPermissions, commands.MissingRole, commands.MissingAnyRole, commands.CheckFailure)):
        return
        
    if isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية قبل ما تعيد الأمر.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ تأكد من كتابة الأمر صح.")
    else:
        original = getattr(error, "original", error)
        print(f"خطأ غير متوقع بأمر {ctx.command}: {original!r}")

async def load_extensions():
    cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
    if os.path.exists(cogs_dir):
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py"):
                await bot.load_extension(f"cogs.{filename[:-3]}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        print("Error: DISCORD_TOKEN environment variable not set.")
