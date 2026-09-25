from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from utils.storage import Storage
from utils.embeds import branded_embed


class MentionTracker(commands.Cog):
    """
    نظام تتبّع المنشنات: كل ما حدا يمنشن شخص، منسجل مين منشنه ووين.
    أمر "منشن" بيوري القائمة (آخر 24 ساعة بس - أي منشن أقدم بيوقع لحاله من القائمة تلقائياً).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.prune_task.start()

    def cog_unload(self):
        self.prune_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not message.mentions:
            return

        seen = set()
        for member in message.mentions:
            if member.bot or member.id == message.author.id or member.id in seen:
                continue
            seen.add(member.id)
            await Storage.add_mention(
                message.guild.id, member.id, message.author.id, message.channel.id, message.id
            )

    @commands.command(name="منشن")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def mention_cmd(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        entries = await Storage.get_recent_mentions(ctx.guild.id, target.id, within_hours=24)

        if not entries:
            who = "حدا" if target.id == ctx.author.id else target.display_name
            await ctx.reply(f"ℹ️ ما في حدا منشن {who} بآخر 24 ساعة.")
            return

        lines = []
        for e in entries[:15]:
            by_member = ctx.guild.get_member(e["by"])
            by_name = by_member.mention if by_member else f"<@{e['by']}>"
            try:
                at = datetime.fromisoformat(e["at"])
            except ValueError:
                at = None
            time_txt = discord.utils.format_dt(at, style="R") if at else "؟"
            link = f"https://discord.com/channels/{ctx.guild.id}/{e['channel_id']}/{e['message_id']}"
            lines.append(f"• {by_name} بـ <#{e['channel_id']}> - [اذهب للرسالة]({link}) - {time_txt}")

        embed = branded_embed(title=f"📣 مين منشن {target.display_name} (آخر 24 ساعة)", color=discord.Color.blurple())
        embed.description = "\n".join(lines)
        if len(entries) > 15:
            embed.set_footer(text=f"{embed.footer.text} • وفي {len(entries) - 15} منشن إضافي مو ظاهر هون")

        await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @mention_cmd.error
    async def mention_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    @tasks.loop(hours=1)
    async def prune_task(self):
        try:
            await Storage.prune_all_old_mentions(older_than_hours=24)
        except Exception as e:
            print(f"⚠️ فشل تنظيف المنشنات القديمة: {e}")

    @prune_task.before_loop
    async def before_prune_task(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(MentionTracker(bot))
