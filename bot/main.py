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

INITIAL_COGS = [
    "cogs.fast_roles",
]

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands successfully!")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Bot is ready and operational with Slash Command support!")

@bot.event
async def on_command_error(ctx, error):
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

async def main():
    async with bot:
        for cog in INITIAL_COGS:
            try:
                await bot.load_extension(cog)
                print(f"Loaded extension: {cog}")
            except Exception as e:
                print(f"Failed to load extension {cog}: {e}")
        
        token = os.getenv("DISCORD_TOKEN")
        if token:
            await bot.start(token)
        else:
            print("Error: DISCORD_TOKEN environment variable not set.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
