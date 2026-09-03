"""
نظام السجن: أمر سجن (يشيل كل رتب الشخص، يعطيه رتبة السجن، وتختفي عنه كل
الرومات إلا روم السجن) وأمر انسجن / فك السجن (يرجعله رتبه القديمة ويشيل
رتبة السجن). السجن بدون مدة - بضل مسجون للأبد لحد ما حد يفك عنه.
"""

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.checks import has_any_role, collect_roles, can_target, bot_missing_permissions
from utils.embeds import branded_embed


class PrisonSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- أدوات مساعدة ----------------

    async def send_log(self, guild: discord.Guild, fields: dict):
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["prison"].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل السجن", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    async def _apply_jail_overwrites(
        self, guild: discord.Guild, jail_role: discord.Role, prison_channel: discord.abc.GuildChannel
    ) -> int:
        """
        يخفي كل رومات السيرفر عن رتبة السجن، ويسمح فقط بروم السجن.
        يرجّع عدد الرومات يلي فشل تعديلها (نقص صلاحية عادةً).
        """
        errors = 0
        for channel in guild.channels:
            try:
                overwrite = channel.overwrites_for(jail_role)
                if channel.id == prison_channel.id:
                    overwrite.view_channel = True
                    if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                        overwrite.send_messages = True
                        overwrite.read_message_history = True
                    elif isinstance(channel, discord.VoiceChannel):
                        overwrite.connect = True
                        overwrite.speak = True
                else:
                    overwrite.view_channel = False
                await channel.set_permissions(jail_role, overwrite=overwrite, reason="إعداد نظام السجن")
            except (discord.Forbidden, discord.HTTPException):
                errors += 1
        return errors

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        """أي روم جديد ينعمل بعد الإعداد، يظل مخفي تلقائياً عن رتبة السجن."""
        guild = channel.guild
        conf = await Storage.get_guild(guild.id)
        p = conf["prison"]
        jail_role_id = p.get("jail_role_id")
        if not jail_role_id:
            return
        if channel.id == p.get("prison_channel_id"):
            return
        jail_role = guild.get_role(jail_role_id)
        if not jail_role:
            return
        try:
            overwrite = channel.overwrites_for(jail_role)
            overwrite.view_channel = False
            await channel.set_permissions(jail_role, overwrite=overwrite, reason="نظام السجن: إخفاء روم جديد عن المسجونين")
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _perform_release(self, invoker: discord.Member, guild: discord.Guild, member: discord.Member, reply):
        conf = await Storage.get_guild(guild.id)
        p = conf["prison"]

        if not p.get("jail_role_id"):
            await reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-prison` أول.")
            return

        if not has_any_role(invoker, p["release_role_ids"]) and invoker.id != guild.owner_id:
            return

        jailed = await Storage.get_jailed(guild.id, member.id)
        if not jailed:
            await reply("⚠️ هاد الشخص مو مسجون.")
            return

        missing = bot_missing_permissions(guild, "manage_roles")
        if missing:
            await reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        bot_top_position = guild.me.top_role.position
        to_restore = [
            role for role in (guild.get_role(rid) for rid in jailed.get("roles", []))
            if role is not None and role.position < bot_top_position
        ]

        # نفس فكرة السجن: طلب واحد بس (member.edit) بدل طلبين (remove + add)
        # حتى ترجع الرتب القديمة بسرعة مهما كان عددها. لازم نضل محافظين على
        # أي رتبة managed (بوت/تكامل) عنده حالياً غير رتبة السجن.
        managed_roles = [r for r in member.roles if r.managed]
        new_roles = managed_roles + to_restore

        try:
            await member.edit(roles=new_roles, reason=f"فك السجن بواسطة {invoker}")
        except discord.Forbidden:
            await reply("❌ ما قدرت أفك السجن، تأكد إن رتبة البوت أعلى من رتبة السجن ورتب الشخص القديمة.")
            return

        await Storage.remove_jailed(guild.id, member.id)

        try:
            dm_embed = branded_embed(title="🔓 تم فك سجنك", color=discord.Color.green())
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        await reply(f"🔓 تم فك السجن عن {member.mention}، ورجعتله رتبه القديمة.")

        await self.send_log(guild, {
            "العملية": "🔓 فك سجن",
            "بواسطة": invoker.mention,
            "الهدف": f"{member} ({member.id})",
        })

    # ---------------- /set-up-prison ----------------

    @app_commands.command(name="set-up-prison", description="إعداد نظام السجن")
    @app_commands.describe(
        imprison_role_1="أول رتبة تقدر تستخدم أمر سجن",
        release_role_1="أول رتبة تقدر تستخدم أمر انسجن / فك السجن",
        jail_role="الرتبة يلي تُعطى للشخص وقت السجن وتُشال وقت الفك",
        prison_channel="روم السجن يلي بضل ظاهر للمسجون بس",
        log_channel="قناة اللوق",
        imprison_role_2="رتبة ثانية اختيارية (سجن)",
        imprison_role_3="رتبة ثالثة اختيارية (سجن)",
        imprison_role_4="رتبة رابعة اختيارية (سجن)",
        release_role_2="رتبة ثانية اختيارية (فك سجن)",
        release_role_3="رتبة ثالثة اختيارية (فك سجن)",
        release_role_4="رتبة رابعة اختيارية (فك سجن)",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def set_up_prison(
        self,
        interaction: discord.Interaction,
        imprison_role_1: discord.Role,
        release_role_1: discord.Role,
        jail_role: discord.Role,
        prison_channel: discord.TextChannel,
        log_channel: discord.TextChannel,
        imprison_role_2: discord.Role = None,
        imprison_role_3: discord.Role = None,
        imprison_role_4: discord.Role = None,
        release_role_2: discord.Role = None,
        release_role_3: discord.Role = None,
        release_role_4: discord.Role = None,
    ):
        guild = interaction.guild
        bot_member = guild.me

        if jail_role.is_default() or jail_role.managed:
            await interaction.response.send_message(
                "❌ ما فيك تختار رتبة @everyone أو رتبة مرتبطة ببوت/تكامل كرتبة سجن.", ephemeral=True
            )
            return
        if jail_role.position >= bot_member.top_role.position:
            await interaction.response.send_message(
                "❌ رتبة السجن لازم تكون تحت رتبة البوت حتى يقدر يعطيها ويشيلها.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        imprison_ids = collect_roles(imprison_role_1, imprison_role_2, imprison_role_3, imprison_role_4)
        release_ids = collect_roles(release_role_1, release_role_2, release_role_3, release_role_4)

        await Storage.update_guild(guild.id, "prison", {
            "imprison_role_ids": imprison_ids,
            "release_role_ids": release_ids,
            "jail_role_id": jail_role.id,
            "prison_channel_id": prison_channel.id,
            "log_channel_id": log_channel.id,
        })

        errors = await self._apply_jail_overwrites(guild, jail_role, prison_channel)

        embed = branded_embed(title="✅ تم إعداد نظام السجن", color=discord.Color.green())
        embed.add_field(name="مين يقدر يسجن", value=", ".join(f"<@&{i}>" for i in imprison_ids), inline=False)
        embed.add_field(name="مين يقدر يفك السجن", value=", ".join(f"<@&{i}>" for i in release_ids), inline=False)
        embed.add_field(name="رتبة السجن", value=jail_role.mention, inline=False)
        embed.add_field(name="روم السجن", value=prison_channel.mention, inline=False)
        embed.add_field(name="قناة اللوق", value=log_channel.mention, inline=False)
        embed.add_field(
            name="الأوامر",
            value="`سجن @شخص` — يشيل كل رتبه ورومانه ويحطه بروم السجن للأبد لحد ما يتفك عنه.\n"
                  "`انسجن @شخص` أو `فك السجن @شخص` — يرجعله رتبه القديمة.",
            inline=False,
        )
        if errors:
            embed.add_field(
                name="⚠️ تنبيه",
                value=f"ما قدرت أعدّل صلاحيات {errors} روم (تأكد إن رتبة البوت أعلى من رتبة السجن وعنده صلاحية Manage Channels).",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @set_up_prison.error
    async def set_up_prison_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)

    # ---------------- سجن ----------------

    @commands.command(name="سجن")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def jail_cmd(self, ctx: commands.Context, member: discord.Member = None, *, reason: str = None):
        if member is None:
            await ctx.reply("استخدم الأمر هيك: `سجن @شخص`")
            return

        conf = await Storage.get_guild(ctx.guild.id)
        p = conf["prison"]
        if not p["jail_role_id"] or not p["prison_channel_id"]:
            await ctx.reply("❌ النظام ما تم إعداده لسا. استخدم `/set-up-prison` أول.")
            return
        if not has_any_role(ctx.author, p["imprison_role_ids"]) and ctx.author.id != ctx.guild.owner_id:
            return

        ok, msg = can_target(ctx.author, member)
        if not ok:
            await ctx.reply(f"❌ {msg}")
            return

        existing = await Storage.get_jailed(ctx.guild.id, member.id)
        if existing:
            await ctx.reply("⚠️ هاد الشخص مسجون أصلاً.")
            return

        jail_role = ctx.guild.get_role(p["jail_role_id"])
        if jail_role is None:
            await ctx.reply("❌ رتبة السجن ما عادت موجودة، أعد الإعداد بـ `/set-up-prison`.")
            return

        missing = bot_missing_permissions(ctx.guild, "manage_roles")
        if missing:
            await ctx.reply(f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return
        if jail_role.position >= ctx.guild.me.top_role.position:
            await ctx.reply("❌ رتبة السجن لازم تكون تحت رتبة البوت.")
            return

        # نجمع رتب الشخص الحالية: رتب البوتات/التكاملات (managed) لازم تضل معه
        # زي ما هي، والباقي (غير @everyone) هو يلي رح ينشال ويترجع وقت الفك.
        # هون منسوي التبديل بطلب واحد بس (member.edit) بدل طلبين (remove + add)
        # حتى تصير العملية سريعة جداً مهما كان عدد رتب الشخص.
        managed_roles = [r for r in member.roles if r.managed]
        roles_to_remove = [r for r in member.roles if not r.is_default() and not r.managed]
        stored_role_ids = [r.id for r in roles_to_remove]

        try:
            await member.edit(roles=managed_roles + [jail_role], reason=f"سجن بواسطة {ctx.author}")
        except discord.Forbidden:
            await ctx.reply("❌ ما قدرت أسجن الشخص، تأكد إن رتبة البوت أعلى من رتبته ومن رتبة السجن.")
            return

        await Storage.set_jailed(ctx.guild.id, member.id, {
            "roles": stored_role_ids,
            "by": ctx.author.id,
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

        prison_channel = ctx.guild.get_channel(p["prison_channel_id"])

        try:
            dm_embed = branded_embed(title="🔒 تم سجنك", color=discord.Color.red())
            dm_embed.add_field(name="السبب", value=reason or "بدون سبب محدد", inline=False)
            dm_embed.add_field(
                name="المدة", value="بدون مدة محددة، لحد ما حد يفك السجن عنك.", inline=False
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        embed = branded_embed(title="🔒 تم السجن", color=discord.Color.red())
        embed.add_field(name="الشخص", value=member.mention, inline=False)
        embed.add_field(name="السبب", value=reason or "بدون سبب محدد", inline=False)
        embed.add_field(
            name="المدة",
            value="للأبد، لحد ما حد معه صلاحية يفك السجن يستخدم `انسجن @شخص` أو `فك السجن @شخص`.",
            inline=False,
        )
        if prison_channel:
            embed.add_field(name="روم السجن", value=prison_channel.mention, inline=False)
        await ctx.reply(embed=embed)

        await self.send_log(ctx.guild, {
            "العملية": "🔒 سجن",
            "بواسطة": ctx.author.mention,
            "الهدف": f"{member} ({member.id})",
            "السبب": reason or "بدون سبب محدد",
            "عدد الرتب المشالة": len(stored_role_ids),
        })

    @jail_cmd.error
    async def jail_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ استنى {error.retry_after:.0f} ثانية.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    # ---------------- انسجن ----------------

    @commands.command(name="انسجن")
    @commands.guild_only()
    async def unjail_cmd(self, ctx: commands.Context, member: discord.Member = None):
        if member is None:
            await ctx.reply("استخدم الأمر هيك: `انسجن @شخص` أو `فك السجن @شخص`")
            return
        await self._perform_release(ctx.author, ctx.guild, member, ctx.reply)

    @unjail_cmd.error
    async def unjail_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ ما لقيت هاد الشخص، تأكد من المنشن.")

    # ---------------- فك السجن (أمر بكلمتين، مش فيه مسافة فبنتعامل معه بـ on_message) ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content.strip()
        if content != "فك السجن" and not content.startswith("فك السجن "):
            return
        if not message.mentions:
            await message.reply("استخدم الأمر هيك: `فك السجن @شخص`")
            return
        member = message.mentions[0]
        await self._perform_release(message.author, message.guild, member, message.reply)


async def setup(bot: commands.Bot):
    await bot.add_cog(PrisonSystem(bot))
