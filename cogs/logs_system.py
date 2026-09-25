import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.embeds import branded_embed

# أنظمة الحماية يلي بتشترك بلوق "حماية" العام (كل شي ما عدا الويب هوك يلي إله لوق خاص فيه)
SECURITY_SHARED_SUBSECTIONS = (
    "bot_add", "prune", "channels", "roles",
    "permission_escalation", "guild_update", "rate_limit",
)


class LogsSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send(self, guild: discord.Guild, section: str, embed: discord.Embed):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf.get(section, {}).get("channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    # ---------------- /mo7-log ----------------

    @app_commands.command(name="mo7-log", description="تحديد/تحديث كل قنوات اللوق تاعت البوت بمكان واحد")
    @app_commands.describe(
        ban_log="لوق الباند",
        warn_log="لوق التحذير",
        timeout_log="لوق التايم",
        unban_log="لوق فك الباند",
        clear_log="لوق المسح (مسح العادي ومسح شخص محدد)",
        messages_log="لوق الرسائل (حذف/تعديل - قبل وبعد)",
        join_log="لوق دخول الأعضاء",
        leave_log="لوق خروج الأعضاء",
        security_log="لوق الحماية العام (كل الحماية ما عدا الويب هوك)",
        webhook_log="لوق حماية الويب هوك",
        commands_log="لوق كل أوامر البوت",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def mo7_log(
        self,
        interaction: discord.Interaction,
        ban_log: discord.TextChannel = None,
        warn_log: discord.TextChannel = None,
        timeout_log: discord.TextChannel = None,
        unban_log: discord.TextChannel = None,
        clear_log: discord.TextChannel = None,
        messages_log: discord.TextChannel = None,
        join_log: discord.TextChannel = None,
        leave_log: discord.TextChannel = None,
        security_log: discord.TextChannel = None,
        webhook_log: discord.TextChannel = None,
        commands_log: discord.TextChannel = None,
    ):
        gid = interaction.guild.id
        updated = []

        if ban_log:
            await Storage.update_guild(gid, "ban", {"log_channel_id": ban_log.id})
            updated.append(("🔨 باند", ban_log))
        if warn_log:
            await Storage.update_guild(gid, "warn", {"log_channel_id": warn_log.id})
            updated.append(("⚠️ تحذير", warn_log))
        if timeout_log:
            await Storage.update_guild(gid, "time", {"log_channel_id": timeout_log.id})
            updated.append(("⏱️ تايم", timeout_log))
        if unban_log:
            await Storage.update_guild(gid, "unban", {"log_channel_id": unban_log.id})
            updated.append(("🔓 فك باند", unban_log))
        if clear_log:
            await Storage.update_guild(gid, "clear", {"log_channel_id": clear_log.id})
            await Storage.update_guild(gid, "clear_v2", {"log_channel_id": clear_log.id})
            updated.append(("🧹 مسح", clear_log))
        if messages_log:
            await Storage.update_guild(gid, "message_log", {"channel_id": messages_log.id})
            updated.append(("💬 رسائل", messages_log))
        if join_log:
            await Storage.update_guild(gid, "join_log", {"channel_id": join_log.id})
            updated.append(("📥 دخول", join_log))
        if leave_log:
            await Storage.update_guild(gid, "leave_log", {"channel_id": leave_log.id})
            updated.append(("📤 خروج", leave_log))
        if security_log:
            for sub in SECURITY_SHARED_SUBSECTIONS:
                await Storage.update_security(gid, sub, {"log_channel_id": security_log.id})
            updated.append(("🛡️ حماية عام", security_log))
        if webhook_log:
            await Storage.update_security(gid, "webhook", {"log_channel_id": webhook_log.id})
            updated.append(("🔗 ويب هوك", webhook_log))
        if commands_log:
            await Storage.update_guild(gid, "command_log", {"channel_id": commands_log.id})
            updated.append(("🤖 كل الأوامر", commands_log))

        if not updated:
            await interaction.response.send_message("❌ ما حددت ولا قناة، اختار قناة وحدة عالأقل حتى أحدثها.", ephemeral=True)
            return

        embed = branded_embed(title="✅ تم تحديث قنوات اللوق", color=discord.Color.green())
        for label, channel in updated:
            embed.add_field(name=label, value=channel.mention, inline=True)
        embed.add_field(
            name="ℹ️ ملاحظة",
            value="هاد الأمر بيحدث بس القنوات يلي حددتها، الباقي ضل متل ما كان. "
                  "لتغيير الرتب المسموحة لأي نظام لحاله، استخدم السيت اب الخاص فيه.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @mo7_log.error
    async def mo7_log_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return

    # ---------------- لوق دخول/خروج الأعضاء ----------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = branded_embed(title="📥 عضو جديد انضم", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.add_field(name="العضو", value=f"{member.mention} ({member})", inline=False)
        embed.add_field(name="تاريخ إنشاء الحساب", value=discord.utils.format_dt(member.created_at, style="R"), inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await self._send(member.guild, "join_log", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        embed = branded_embed(title="📤 عضو غادر", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        embed.add_field(name="العضو", value=f"{member.mention} ({member})", inline=False)
        if member.joined_at:
            embed.add_field(name="انضم", value=discord.utils.format_dt(member.joined_at, style="R"), inline=False)
        roles = [r.mention for r in member.roles if not r.is_default()]
        if roles:
            embed.add_field(name="الرتب يلي كانت معه", value=", ".join(roles), inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await self._send(member.guild, "leave_log", embed)

    # ---------------- لوق الرسائل (حذف/تعديل) ----------------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        content = message.content or "*(بدون نص - ملحق أو صورة بس)*"
        if len(content) > 1000:
            content = content[:1000] + "..."
        embed = branded_embed(title="🗑️ رسالة انمسحت", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
        embed.add_field(name="الكاتب", value=f"{message.author.mention} ({message.author})", inline=False)
        embed.add_field(name="الروم", value=message.channel.mention, inline=False)
        embed.add_field(name="النص", value=content, inline=False)
        if message.attachments:
            embed.add_field(name="المرفقات", value="\n".join(a.url for a in message.attachments[:5]), inline=False)
        await self._send(message.guild, "message_log", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return  # تعديل مو بالنص (متل تحميل معاينة رابط) - تجاهله
        before_txt = before.content or "*(فاضي)*"
        after_txt = after.content or "*(فاضي)*"
        if len(before_txt) > 500:
            before_txt = before_txt[:500] + "..."
        if len(after_txt) > 500:
            after_txt = after_txt[:500] + "..."
        embed = branded_embed(title="✏️ رسالة انعدلت", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        embed.add_field(name="الكاتب", value=f"{before.author.mention} ({before.author})", inline=False)
        embed.add_field(name="الروم", value=before.channel.mention, inline=False)
        embed.add_field(name="قبل", value=before_txt, inline=False)
        embed.add_field(name="بعد", value=after_txt, inline=False)
        embed.add_field(name="الرابط", value=f"[روح للرسالة]({after.jump_url})", inline=False)
        await self._send(before.guild, "message_log", embed)

    # ---------------- لوق كل أوامر البوت ----------------

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        if not ctx.guild:
            return
        content = ctx.message.content
        if len(content) > 200:
            content = content[:200] + "..."
        embed = branded_embed(title="🤖 استخدام أمر", color=discord.Color.greyple(), timestamp=discord.utils.utcnow())
        embed.add_field(name="بواسطة", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
        embed.add_field(name="الأمر", value=f"`{content}`", inline=False)
        embed.add_field(name="الروم", value=ctx.channel.mention, inline=False)
        await self._send(ctx.guild, "command_log", embed)

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        if not interaction.guild:
            return
        embed = branded_embed(title="🤖 استخدام أمر (Slash)", color=discord.Color.greyple(), timestamp=discord.utils.utcnow())
        embed.add_field(name="بواسطة", value=f"{interaction.user.mention} ({interaction.user})", inline=False)
        embed.add_field(name="الأمر", value=f"`/{command.qualified_name}`", inline=False)
        if interaction.channel:
            embed.add_field(name="الروم", value=interaction.channel.mention, inline=False)
        await self._send(interaction.guild, "command_log", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LogsSystem(bot))
