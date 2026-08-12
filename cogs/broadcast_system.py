"""نظام برودكاست متعدد البوتات مدموج مع بوت الإدارة الرئيسي."""

import asyncio
import base64
import hashlib
import logging
import os
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from utils.storage import Storage
from utils.checks import is_owner


SEND_DELAY_SECONDS = 0.6
TOKEN_SECTION = "broadcast"
logger = logging.getLogger(__name__)


def _encryption_key() -> bytes:
    """يرجع مفتاحاً ثابتاً للتشفير، مع دعم BC_ENCRYPT_KEY المتوافق مع نسخة Node."""
    configured = os.getenv("BC_ENCRYPT_KEY")
    if configured:
        if len(configured) != 64:
            raise ValueError("BC_ENCRYPT_KEY لازم يكون سلسلة hex طولها 64 حرف.")
        try:
            return bytes.fromhex(configured)
        except ValueError as error:
            raise ValueError("BC_ENCRYPT_KEY لازم يحتوي أحرف hex فقط.") from error

    # يحافظ على التشغيل داخل Replit بدون إضافة سر جديد، مع إبقاء BC_ENCRYPT_KEY
    # هو الخيار المفضل عند النشر أو عند مشاركة البيانات بين نسخ مختلفة من البوت.
    session_secret = os.getenv("SESSION_SECRET")
    if session_secret:
        return hashlib.sha256(session_secret.encode("utf-8")).digest()
    raise RuntimeError("أضف BC_ENCRYPT_KEY إلى متغيرات البيئة قبل حفظ توكنات البرودكاست.")


def encrypt_token(token: str) -> str:
    key = _encryption_key()
    nonce = os.urandom(12)
    encrypted_with_tag = AESGCM(key).encrypt(nonce, token.encode("utf-8"), None)
    ciphertext, auth_tag = encrypted_with_tag[:-16], encrypted_with_tag[-16:]
    return ":".join(
        base64.b64encode(part).decode("ascii")
        for part in (nonce, auth_tag, ciphertext)
    )


def decrypt_token(value: str) -> str:
    """يفك تنسيق AES-256-GCM نفسه الموجود في ملف JavaScript، ويدعم القديم."""
    parts = value.split(":")
    if len(parts) != 3:
        return value
    nonce_b64, auth_tag_b64, ciphertext_b64 = parts
    nonce = base64.b64decode(nonce_b64)
    auth_tag = base64.b64decode(auth_tag_b64)
    ciphertext = base64.b64decode(ciphertext_b64)
    return AESGCM(_encryption_key()).decrypt(
        nonce, ciphertext + auth_tag, None
    ).decode("utf-8")


def _broadcast_embed(
    title: str,
    total: int,
    done: int,
    failed: int,
    color: discord.Color,
) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=(
            f"**⚫ عدد الأعضاء: `{total}`\n"
            f"🟢 تم الإرسال إلى: `{done}`\n"
            f"🔴 فشل الإرسال إلى: `{failed}`**"
        ),
        color=color,
    )


def _top_server_role(guild: discord.Guild):
    """أعلى رتبة حقيقية بالسيرفر (تستثني @everyone ورتب البوتات/التكاملات)."""
    candidates = [r for r in guild.roles if not r.is_default() and not r.managed]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.position)


def _can_manage_broadcast_whitelist(member: discord.Member) -> bool:
    """مسموح فقط لصاحب السيرفر، أو لصاحب أعلى رتبة حقيقية بالسيرفر."""
    guild = member.guild
    if is_owner(member):
        return True
    top_role = _top_server_role(guild)
    if top_role is not None and top_role in member.roles:
        return True
    return False


def _is_online(member: discord.Member) -> bool:
    return (
        member.status in {
            discord.Status.online,
            discord.Status.idle,
            discord.Status.dnd,
        }
        or any(
            isinstance(activity, discord.Streaming)
            for activity in member.activities
        )
    )


async def run_broadcast(
    tokens: list[str],
    member_ids: list[int],
    message: str,
    on_progress: Callable[[int, int], Awaitable[None]],
    on_done: Callable[[int, int], Awaitable[None]],
) -> None:
    """يرسل بالتتابع على التوكنات مع تأخير ثابت لتقليل ضغط Discord."""
    buckets = [[] for _ in tokens]
    for index, member_id in enumerate(member_ids):
        buckets[index % len(tokens)].append(member_id)

    done = 0
    failed = 0
    client_intents = discord.Intents.none()

    for token, bucket in zip(tokens, buckets):
        if not bucket:
            continue
        client = discord.Client(intents=client_intents)
        try:
            try:
                await client.login(token)
            except Exception:
                failed += len(bucket)
                await on_progress(done, failed)
                continue

            for member_id in bucket:
                try:
                    user = await client.fetch_user(member_id)
                    await user.send(f"**{message}\n<@{member_id}>**")
                    done += 1
                except Exception:
                    failed += 1
                await on_progress(done, failed)
                await asyncio.sleep(SEND_DELAY_SECONDS)
        finally:
            await client.close()

    await on_done(done, failed)


class BroadcastPanelView(discord.ui.View):
    def __init__(self, cog: "BroadcastSystem"):
        super().__init__(timeout=None)
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """التحقق من صلاحية المستخدم عند الضغط على لوحة قديمة أو عامة."""
        return await self.cog._require_broadcast_access(interaction)

    @discord.ui.button(
        label="اضافة توكن برودكاست",
        style=discord.ButtonStyle.primary,
        emoji="🤖",
        custom_id="broadcast:add-token",
    )
    async def add_token(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.cog.show_add_token_modal(interaction)

    @discord.ui.button(
        label="تحديد رسالة البرودكاست",
        style=discord.ButtonStyle.secondary,
        emoji="📡",
        custom_id="broadcast:set-message",
    )
    async def set_message(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.cog.show_message_modal(interaction)

    @discord.ui.button(
        label="بدأ ارسال البرودكاست",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="broadcast:start",
    )
    async def start(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.cog.show_broadcast_types(interaction)


class BroadcastTypeView(discord.ui.View):
    def __init__(self, cog: "BroadcastSystem", owner_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await self.cog._require_broadcast_access(interaction):
            return False
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "هاد الاختيار مو إلك.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="إرسال للأونلاين", style=discord.ButtonStyle.success, custom_id="broadcast:online"
    )
    async def online(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.cog.start_from_interaction(interaction, "online")

    @discord.ui.button(
        label="إرسال للأوفلاين", style=discord.ButtonStyle.danger, custom_id="broadcast:offline"
    )
    async def offline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.cog.start_from_interaction(interaction, "offline")

    @discord.ui.button(
        label="إرسال للجميع", style=discord.ButtonStyle.primary, custom_id="broadcast:all"
    )
    async def all_members(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.cog.start_from_interaction(interaction, "all")


class AddTokenModal(discord.ui.Modal, title="اضافة توكن بوت برودكاست"):
    token = discord.ui.TextInput(
        label="التوكن",
        style=discord.TextStyle.short,
        min_length=50,
        max_length=100,
        required=True,
    )

    def __init__(self, cog: "BroadcastSystem"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.save_token(interaction, str(self.token).strip())


class BroadcastMessageModal(discord.ui.Modal, title="تحديد رسالة البرودكاست"):
    message = discord.ui.TextInput(
        label="الرسالة",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=4000,
        required=True,
    )

    def __init__(self, cog: "BroadcastSystem"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.save_message(interaction, str(self.message))


class BroadcastSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # الأزرار تبقى فعالة للبانلات القديمة بعد إعادة تشغيل البوت.
        self.bot.add_view(BroadcastPanelView(self))

    async def _config(self, guild_id: int) -> dict:
        return (await Storage.get_guild(guild_id)).get(TOKEN_SECTION, {})

    async def _refresh_panel(self, interaction: discord.Interaction) -> None:
        config = await self._config(interaction.guild.id)
        message_id = config.get("message_id")
        channel_id = config.get("channel_id")
        if not message_id or not channel_id:
            return

        channel = interaction.guild.get_channel(channel_id)
        if channel is None:
            return
        try:
            panel_message = await channel.fetch_message(message_id)
            tokens = config.get("tokens", [])
            text = config.get("message") or "لم يتم تحديد رسالة"
            embed = discord.Embed(
                title="التحكم في البرودكاست",
                description="يمكنك التحكم في البوت عن طريق الأزرار",
                color=discord.Color.teal(),
            )
            embed.add_field(
                name="عدد البوتات المسجلة حاليا",
                value=f"**```{len(tokens)} من البوتات```**",
                inline=False,
            )
            embed.add_field(
                name="رسالة البرودكاست الحالية",
                value=f"**```{text[:1000]}```**",
                inline=False,
            )
            await panel_message.edit(embed=embed, view=BroadcastPanelView(self))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def show_add_token_modal(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_modal(AddTokenModal(self))

    async def show_message_modal(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_modal(BroadcastMessageModal(self))

    async def show_broadcast_types(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        await interaction.response.send_message(
            "اختر نوع الإرسال:",
            view=BroadcastTypeView(self, interaction.user.id),
            ephemeral=True,
        )

    async def _require_broadcast_access(self, interaction: discord.Interaction) -> bool:
        """
        فحص موحد لكل مسارات البرودكاست، بما فيها الأزرار والمودالات.

        وجود Administrator وحده لا يكفي بعد ضبط رتبة whitelist؛ يجب أن
        يجتمع مع الرتبة المحددة حتى لا يستطيع إداري غير مصرح له استخدام
        لوحة الإرسال أو أوامر الإرسال النصية.
        """
        allowed = False
        message = "هذه الميزة مخصصة لأعضاء الإدارة فقط."

        if interaction.guild and isinstance(interaction.user, discord.Member):
            member = interaction.user
            if member.guild_permissions.administrator:
                config = await self._config(interaction.guild.id)
                whitelist_role_id = config.get("whitelist_role_id")
                if not whitelist_role_id:
                    allowed = True
                elif any(role.id == whitelist_role_id for role in member.roles):
                    allowed = True
                else:
                    message = (
                        "حتى لو معك Administrator، لازم تكون معك رتبة "
                        "whitelist الخاصة بالبرودكاست."
                    )

        if allowed:
            return True

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        """اسم توافق داخلي قديم؛ كل عمليات البرودكاست تستخدم الفحص الموحد."""
        return await self._require_broadcast_access(interaction)

    async def save_token(self, interaction: discord.Interaction, token: str):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        config = await self._config(interaction.guild.id)
        encrypted_tokens = config.get("tokens", [])
        try:
            existing_tokens = [decrypt_token(value) for value in encrypted_tokens]
            if token in existing_tokens:
                await interaction.followup.send("هذا التوكن موجود بالفعل.", ephemeral=True)
                return

            client = discord.Client(intents=discord.Intents.none())
            try:
                await client.login(token)
                bot_user = client.user
                if bot_user is None:
                    raise RuntimeError("تعذر قراءة حساب البوت.")
                bot_tag = str(bot_user)
                bot_id = bot_user.id
            finally:
                await client.close()

            encrypted_tokens.append(encrypt_token(token))
            await Storage.update_guild(
                interaction.guild.id,
                TOKEN_SECTION,
                {"tokens": encrypted_tokens},
            )
            invite = discord.ui.Button(
                label="دعوة البوت",
                style=discord.ButtonStyle.link,
                # بوت البرودكاست لا يحتاج صلاحيات سيرفر؛ منحه Administrator
                # يجعل رابط الدعوة خطراً إذا تمت مشاركته خارج الإدارة.
                url=f"https://discord.com/api/oauth2/authorize?client_id={bot_id}&permissions=0&scope=bot",
            )
            embed = discord.Embed(
                title="تم تسجيل الدخول بنجاح",
                color=discord.Color.teal(),
            )
            embed.add_field(name="اسم البوت", value=f"```{bot_tag}```", inline=False)
            embed.add_field(name="ايدي البوت", value=f"```{bot_id}```", inline=False)
            await interaction.followup.send(
                embed=embed,
                view=discord.ui.View().add_item(invite),
                ephemeral=True,
            )
            await self._refresh_panel(interaction)
        except Exception:
            logger.exception(
                "Broadcast token validation or storage failed for guild %s",
                interaction.guild.id,
            )
            await interaction.followup.send(
                "الرجاء التأكد من توكن البوت أو تفعيل الخيارات المطلوبة من إعدادات البوت.",
                ephemeral=True,
            )

    async def save_message(self, interaction: discord.Interaction, message: str):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await Storage.update_guild(
            interaction.guild.id,
            TOKEN_SECTION,
            {"message": message},
        )
        await self._refresh_panel(interaction)
        await interaction.followup.send("تم تحديد الرسالة بنجاح.", ephemeral=True)

    async def start_from_interaction(
        self, interaction: discord.Interaction, audience: str
    ):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer()
        config = await self._config(interaction.guild.id)
        stored_tokens = config.get("tokens", [])
        if not stored_tokens:
            await interaction.followup.send("لم يتم اضافة أي توكن لبوتات البرودكاست.")
            return
        message = config.get("message")
        if not message:
            await interaction.followup.send("لم يتم تحديد رسالة البرودكاست.")
            return

        try:
            tokens = [decrypt_token(value) for value in stored_tokens]
        except Exception:
            logger.exception(
                "Broadcast token decryption failed for guild %s",
                interaction.guild.id,
            )
            await interaction.followup.send(
                "تعذر فك تشفير التوكنات. تأكد من ثبات BC_ENCRYPT_KEY."
            )
            return

        await interaction.guild.chunk(cache=True)
        members = [member for member in interaction.guild.members if not member.bot]
        if audience == "online":
            members = [member for member in members if _is_online(member)]
        elif audience == "offline":
            members = [
                member
                for member in members
                if member.status in {discord.Status.offline, discord.Status.invisible}
            ]
        member_ids = [member.id for member in members]
        total = len(member_ids)

        status_message = await interaction.followup.send(
            embed=_broadcast_embed(
                "تم البدأ في ارسال رسالة البرودكاست",
                total,
                0,
                0,
                discord.Color.teal(),
            ),
            wait=True,
        )

        async def on_progress(done: int, failed: int):
            await status_message.edit(
                embed=_broadcast_embed(
                    "تم البدأ في ارسال رسالة البرودكاست",
                    total,
                    done,
                    failed,
                    discord.Color.teal(),
                )
            )

        async def on_done(done: int, failed: int):
            await status_message.edit(
                embed=_broadcast_embed(
                    "تم الانتهاء من ارسال رسالة البرودكاست",
                    total,
                    done,
                    failed,
                    discord.Color.green(),
                )
            )

        asyncio.create_task(
            run_broadcast(tokens, member_ids, message, on_progress, on_done)
        )

    async def _start_from_channel(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        audience: str,
        message: str,
    ):
        """مسار الأوامر النصية !bc و !obc."""
        config = await self._config(guild.id)
        stored_tokens = config.get("tokens", [])
        if not stored_tokens:
            await channel.send("لم يتم اضافة أي توكن لبوتات البرودكاست.")
            return

        try:
            tokens = [decrypt_token(value) for value in stored_tokens]
        except Exception:
            await channel.send(
                "تعذر فك تشفير التوكنات. تأكد من ثبات BC_ENCRYPT_KEY."
            )
            return

        await guild.chunk(cache=True)
        members = [member for member in guild.members if not member.bot]
        if audience == "online":
            members = [member for member in members if _is_online(member)]
        member_ids = [member.id for member in members]
        total = len(member_ids)
        status_message = await channel.send(
            embed=_broadcast_embed(
                "بدء إرسال البرودكاست",
                total,
                0,
                0,
                discord.Color.teal(),
            )
        )

        async def on_progress(done: int, failed: int):
            await status_message.edit(
                embed=_broadcast_embed(
                    "تحديث حالة البرودكاست",
                    total,
                    done,
                    failed,
                    discord.Color.teal(),
                )
            )

        async def on_done(done: int, failed: int):
            await status_message.edit(
                embed=_broadcast_embed(
                    "تم الانتهاء من إرسال البرودكاست",
                    total,
                    done,
                    failed,
                    discord.Color.green(),
                )
            )

        asyncio.create_task(
            run_broadcast(tokens, member_ids, message, on_progress, on_done)
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content.strip()
        if not (content.startswith("!bc") or content.startswith("!obc")):
            return
        command, _, broadcast_message = content.partition(" ")
        if command not in {"!bc", "!obc"}:
            return
        config = await self._config(message.guild.id)
        if not message.author.guild_permissions.administrator:
            await message.reply("ليس لديك صلاحية Administrator لاستخدام البرودكاست.")
            return
        whitelist_role_id = config.get("whitelist_role_id")
        if whitelist_role_id and not any(
            role.id == whitelist_role_id for role in message.author.roles
        ):
            await message.reply(
                "حتى لو معك Administrator، لازم تكون معك رتبة whitelist الخاصة بالبرودكاست."
            )
            return
        broadcast_message = broadcast_message.strip()
        if not broadcast_message:
            await message.reply("يرجى كتابة رسالة بعد الأمر.")
            return
        await self._start_from_channel(
            message.guild,
            message.channel,
            "online" if command == "!obc" else "all",
            broadcast_message,
        )

    @app_commands.command(
        name="send-broadcast-panel",
        description="ارسال بانل التحكم في البرودكاست",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def send_panel(self, interaction: discord.Interaction):
        if not await self._require_broadcast_access(interaction):
            return
        await interaction.response.defer()
        config = await self._config(interaction.guild.id)
        old_message_id = config.get("message_id")
        old_channel_id = config.get("channel_id")
        if old_message_id and old_channel_id:
            old_channel = interaction.guild.get_channel(old_channel_id)
            if old_channel:
                try:
                    old_message = await old_channel.fetch_message(old_message_id)
                    await old_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        tokens = config.get("tokens", [])
        text = config.get("message") or "لم يتم تحديد رسالة"
        embed = discord.Embed(
            title="التحكم في البرودكاست",
            description="يمكنك التحكم في البوت عن طريق الأزرار",
            color=discord.Color.teal(),
        )
        embed.add_field(
            name="عدد البوتات المسجلة حاليا",
            value=f"**```{len(tokens)} من البوتات```**",
            inline=False,
        )
        embed.add_field(
            name="رسالة البرودكاست الحالية",
            value=f"**```{text[:1000]}```**",
            inline=False,
        )
        panel_message = await interaction.followup.send(
            embed=embed,
            view=BroadcastPanelView(self),
            wait=True,
        )
        await Storage.update_guild(
            interaction.guild.id,
            TOKEN_SECTION,
            {"message_id": panel_message.id, "channel_id": interaction.channel.id},
        )

    @app_commands.command(
        name="whitelist-borad",
        description="تحديد رتبة إضافية مطلوبة لاستخدام البرودكاست",
    )
    @app_commands.describe(
        role="الرتبة التي يجب أن يملكها مستخدم البرودكاست؛ اتركها فارغة لإلغاء التقييد"
    )
    @app_commands.guild_only()
    async def whitelist_borad(
        self,
        interaction: discord.Interaction,
        role: discord.Role = None,
    ):
        """
        تغيير سياسة الوصول محصور بمالك السيرفر أو صاحب أعلى رتبة حقيقية بالسيرفر.

        هذا يمنع أي Administrator عادي من إعطاء نفسه صلاحية البرودكاست،
        كما نرفض الرتب التي لا يستطيع البوت التعامل معها حسب Discord hierarchy.
        """
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "هذا الأمر يعمل داخل السيرفر فقط.", ephemeral=True
            )
            return

        if not _can_manage_broadcast_whitelist(interaction.user):
            await interaction.response.send_message(
                "هذا الأمر مخصص لمالك السيرفر أو لصاحب أعلى رتبة بالسيرفر فقط، "
                "حتى لو كنت Administrator.",
                ephemeral=True,
            )
            return

        if role is not None:
            bot_member = guild.me
            if bot_member is None:
                await interaction.response.send_message(
                    "تعذر معرفة رتبة البوت حالياً، حاول مرة ثانية.",
                    ephemeral=True,
                )
                return
            if role.is_default() or role.managed:
                await interaction.response.send_message(
                    "لا يمكن اختيار رتبة @everyone أو رتبة مرتبطة ببوت/تكامل.",
                    ephemeral=True,
                )
                return
            if role.position >= bot_member.top_role.position:
                await interaction.response.send_message(
                    "لا يمكن استخدام هذه الرتبة: يجب أن تكون رتبة البوت أعلى منها.",
                    ephemeral=True,
                )
                return

        await Storage.update_guild(
            guild.id,
            TOKEN_SECTION,
            {"whitelist_role_id": role.id if role else None},
        )
        if role is None:
            message = "تم إلغاء رتبة whitelist. سيعود الاستخدام لمشرفي Administrator."
        else:
            message = (
                f"تم ضبط رتبة whitelist على {role.mention}.\n"
                "يجب أن يملك المستخدم Administrator وهذه الرتبة معاً."
            )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="remove-token", description="إزالة توكن برودكاست")
    @app_commands.guild_only()
    async def remove_token(self, interaction: discord.Interaction, token: str):
        if interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message(
                "هذا الأمر مخصص لمالك السيرفر فقط.", ephemeral=True
            )
            return
        config = await self._config(interaction.guild.id)
        tokens = config.get("tokens", [])
        remaining = [value for value in tokens if decrypt_token(value) != token]
        if len(remaining) == len(tokens):
            await interaction.response.send_message(
                "هذا التوكن غير موجود في السيرفر.", ephemeral=True
            )
            return
        await Storage.update_guild(
            interaction.guild.id, TOKEN_SECTION, {"tokens": remaining}
        )
        await interaction.response.send_message("تم إزالة التوكن بنجاح.", ephemeral=True)
        await self._refresh_panel(interaction)

    @app_commands.command(
        name="remove-all-tokens", description="إزالة جميع بوتات البرودكاست"
    )
    @app_commands.guild_only()
    async def remove_all_tokens(self, interaction: discord.Interaction):
        if interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message(
                "هذا الأمر مخصص لمالك السيرفر فقط.", ephemeral=True
            )
            return
        await Storage.update_guild(interaction.guild.id, TOKEN_SECTION, {"tokens": []})
        await interaction.response.send_message(
            "تم إزالة جميع التوكنات من السيرفر بنجاح.", ephemeral=True
        )
        await self._refresh_panel(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(BroadcastSystem(bot))