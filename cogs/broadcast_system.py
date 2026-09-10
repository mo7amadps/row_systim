"""نظام برودكاست متعدد البوتات مدموج مع بوت الإدارة الرئيسي."""

import asyncio
import base64
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from utils.storage import Storage
from utils.checks import is_owner


SEND_DELAY_SECONDS = 0.6
PROGRESS_EVERY = 25
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

    # لا نستخدم SESSION_SECRET أو أي قيمة افتراضية؛ مفتاح التوكنات يجب أن
    # يكون موجوداً كـ Secret صريح حتى لا يتغير أو يصبح معروفاً بالخطأ.
    raise RuntimeError(
        "أضف BC_ENCRYPT_KEY إلى Replit Secrets قبل استخدام البرودكاست."
    )


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _token_records(raw_tokens) -> list[dict]:
    """يرجع الشكل الجديد للتوكنات مع دعم البيانات القديمة التي كانت strings."""
    records = []
    for item in raw_tokens or []:
        if isinstance(item, dict):
            encrypted = item.get("encrypted_token") or item.get("token")
            if not encrypted:
                continue
            record = dict(item)
            record["encrypted_token"] = encrypted
            record.pop("token", None)
            record.setdefault(
                "id",
                f"bot_{hashlib.sha256(encrypted.encode('utf-8')).hexdigest()[:10]}",
            )
            record.setdefault("name", "بوت قديم")
            record.setdefault("bot_id", None)
            record.setdefault("status", "pending")
            record.setdefault("last_checked_at", None)
            record.setdefault("last_error", None)
            records.append(record)
            continue

        if isinstance(item, str):
            # التوافق مع النسخة القديمة: لا نفك التوكن هنا ولا نعرضه.
            fingerprint = hashlib.sha256(item.encode("utf-8")).hexdigest()[:10]
            records.append(
                {
                    "id": f"legacy_{fingerprint}",
                    "name": "بوت قديم",
                    "bot_id": None,
                    "encrypted_token": item,
                    "status": "pending",
                    "last_checked_at": None,
                    "last_error": None,
                }
            )
    return records


def _safe_validation_error(reason: str) -> str:
    """أسباب ثابتة وآمنة للتخزين؛ لا نخزن نص أخطاء قد يحتوي معلومات حساسة."""
    allowed = {
        "invalid_token",
        "decrypt_failed",
        "temporary_error",
        "missing_user",
    }
    return reason if reason in allowed else "temporary_error"


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
    stop_event: asyncio.Event,
    on_progress: Callable[[int, int], Awaitable[None]],
    on_done: Callable[[int, int, bool], Awaitable[None]],
    start_index: int = 0,
    initial_done: int = 0,
    initial_failed: int = 0,
) -> None:
    """يرسل بالتوازي بين التوكنات، وبالتتابع داخل كل توكن."""
    if not tokens:
        await on_done(initial_done, initial_failed + len(member_ids), False)
        return

    # نوزع القائمة بالتساوي على كل التوكنات؛ مثلاً 300 عضو و3 توكنات
    # تعني 100 عضو لكل توكن. كل التوكنات تعمل معاً عبر asyncio.gather.
    remaining_ids = member_ids[max(0, start_index):]
    buckets = [[] for _ in tokens]
    for index, member_id in enumerate(remaining_ids):
        buckets[index % len(tokens)].append(member_id)

    done = initial_done
    failed = initial_failed
    counters_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    stopped = False

    async def report_progress(done_value: int, failed_value: int):
        async with progress_lock:
            await on_progress(done_value, failed_value)

    async def record_result(success: bool):
        nonlocal done, failed
        async with counters_lock:
            if success:
                done += 1
            else:
                failed += 1
            processed = done + failed
            should_report = processed % PROGRESS_EVERY == 0
            snapshot = (done, failed)

        # لا نرسل تحديثات Discord متزامنة من أكثر من توكن.
        if should_report:
            await report_progress(*snapshot)

    async def run_token(token: str, bucket: list[int]) -> bool:
        nonlocal done, failed, stopped
        if not bucket:
            return False

        client = discord.Client(intents=discord.Intents.none())
        try:
            try:
                await client.login(token)
            except Exception:
                async with counters_lock:
                    failed += len(bucket)
                    snapshot = (done, failed)
                await report_progress(*snapshot)
                return False

            for member_id in bucket:
                if stop_event.is_set():
                    stopped = True
                    break
                try:
                    user = await client.fetch_user(member_id)
                    await user.send(f"**{message}\n<@{member_id}>**")
                    await record_result(True)
                except Exception:
                    await record_result(False)
                if not stop_event.is_set():
                    await asyncio.sleep(SEND_DELAY_SECONDS)
        finally:
            await client.close()
        return stop_event.is_set()

    results = await asyncio.gather(
        *(run_token(token, bucket) for token, bucket in zip(tokens, buckets))
    )
    stopped = stopped or stop_event.is_set() or any(results)
    await on_done(done, failed, stopped)


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


class BroadcastStopView(discord.ui.View):
    """زر إيقاف الحملة الحالية، مع نفس فحص صلاحيات البرودكاست."""

    def __init__(self, cog: "BroadcastSystem", guild_id: int):
        super().__init__(timeout=3600)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog._require_broadcast_access(interaction)

    @discord.ui.button(
        label="إيقاف البرودكاست",
        style=discord.ButtonStyle.danger,
        emoji="⏹️",
    )
    async def stop(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        stopped = await self.cog.stop_broadcast(self.guild_id)
        if stopped:
            await interaction.response.send_message(
                "تم طلب إيقاف البرودكاست. سيتوقف بعد العملية الحالية.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "ما في برودكاست شغال حالياً.",
                ephemeral=True,
            )


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
        # كل سيرفر يسمح بحملة واحدة فقط في نفس الوقت.
        self._active_broadcasts: dict[int, dict] = {}
        self._resume_started = False

    async def cog_load(self):
        # الأزرار تبقى فعالة للبانلات القديمة بعد إعادة تشغيل البوت.
        self.bot.add_view(BroadcastPanelView(self))

    @commands.Cog.listener()
    async def on_ready(self):
        """يستأنف أي حملة كانت محفوظة بحالة running قبل Restart."""
        if self._resume_started:
            return
        self._resume_started = True
        for guild_id, campaign in await Storage.get_broadcast_campaigns("running"):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            try:
                tokens, _, _ = await self._validate_stored_tokens(guild_id)
                if not tokens:
                    await Storage.update_guild(
                        guild_id,
                        TOKEN_SECTION,
                        {
                            "campaign": {
                                **campaign,
                                "status": "paused",
                                "last_error": "no_valid_tokens",
                            }
                        },
                    )
                    continue

                channel = guild.get_channel(campaign.get("channel_id"))
                status_message = None
                if channel and campaign.get("message_id"):
                    try:
                        status_message = await channel.fetch_message(
                            campaign["message_id"]
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        status_message = None
                if channel is None:
                    await Storage.update_guild(
                        guild_id,
                        TOKEN_SECTION,
                        {
                            "campaign": {
                                **campaign,
                                "status": "paused",
                                "last_error": "channel_not_found",
                            }
                        },
                    )
                    continue
                if status_message is None:
                    status_message = await channel.send(
                        embed=_broadcast_embed(
                            "استئناف البرودكاست بعد إعادة التشغيل",
                            len(campaign.get("member_ids", [])),
                            campaign.get("done", 0),
                            campaign.get("failed", 0),
                            discord.Color.teal(),
                        ),
                        view=BroadcastStopView(self, guild_id),
                    )

                await self._launch_broadcast(
                    guild,
                    status_message,
                    tokens,
                    campaign.get("member_ids", []),
                    campaign.get("message", ""),
                    start_index=campaign.get("cursor", 0),
                    initial_done=campaign.get("done", 0),
                    initial_failed=campaign.get("failed", 0),
                )
            except Exception:
                logger.exception("Failed to resume broadcast for guild %s", guild_id)

    async def _config(self, guild_id: int) -> dict:
        return (await Storage.get_guild(guild_id)).get(TOKEN_SECTION, {})

    @staticmethod
    async def _validate_plain_token(token: str):
        """يتحقق من التوكن بدون تسجيله أو إظهار قيمته في أي رسالة أو Log."""
        client = discord.Client(intents=discord.Intents.none())
        try:
            await client.login(token)
            if client.user is None:
                return None, "missing_user"
            return client.user, None
        except discord.LoginFailure:
            return None, "invalid_token"
        except Exception:
            # لا نسجل نص الاستثناء لأن بعض المكتبات قد تضع بيانات حساسة داخله.
            return None, "temporary_error"
        finally:
            await client.close()

    async def _validate_stored_tokens(self, guild_id: int):
        """
        يفحص كل التوكنات قبل الحملة.
        التوكن غير الصالح يتعطل، أما الخطأ المؤقت فيبقى بحالة error ولا يُستخدم.
        """
        config = await self._config(guild_id)
        records = _token_records(config.get("tokens", []))
        valid_tokens = []
        disabled_count = 0
        temporary_count = 0

        for record in records:
            checked_at = _now_iso()
            try:
                token = decrypt_token(record["encrypted_token"])
            except Exception:
                record.update(
                    status="disabled",
                    last_checked_at=checked_at,
                    last_error=_safe_validation_error("decrypt_failed"),
                )
                disabled_count += 1
                continue

            bot_user, reason = await self._validate_plain_token(token)
            if bot_user is not None:
                record.update(
                    name=str(bot_user),
                    bot_id=bot_user.id,
                    status="valid",
                    last_checked_at=checked_at,
                    last_error=None,
                )
                valid_tokens.append(token)
                continue

            record.update(
                status="disabled" if reason == "invalid_token" else "error",
                last_checked_at=checked_at,
                last_error=_safe_validation_error(reason),
            )
            if reason == "invalid_token":
                disabled_count += 1
            else:
                temporary_count += 1

        # هذا يحول التوكنات القديمة تلقائياً إلى سجلات مرتبة بدون كشفها.
        await Storage.update_guild(guild_id, TOKEN_SECTION, {"tokens": records})
        return valid_tokens, disabled_count, temporary_count

    async def _prepare_broadcast(self, guild: discord.Guild, audience: str):
        """يفحص الحملة ويجهز قائمة الأعضاء قبل إنشاء الـTask."""
        if guild.id in self._active_broadcasts:
            return None, None, "في برودكاست شغال حالياً بهذا السيرفر."

        config = await self._config(guild.id)
        if not config.get("tokens"):
            return None, None, "لم يتم اضافة أي بوت برودكاست."

        valid_tokens, disabled_count, temporary_count = (
            await self._validate_stored_tokens(guild.id)
        )
        if not valid_tokens:
            return (
                None,
                None,
                "ما في أي توكن صالح حالياً. أضف بوت جديد أو افحص إعدادات Secrets.",
            )

        await guild.chunk(cache=True)
        members = [member for member in guild.members if not member.bot]
        if audience == "online":
            members = [member for member in members if _is_online(member)]
        elif audience == "offline":
            members = [
                member
                for member in members
                if member.status in {discord.Status.offline, discord.Status.invisible}
            ]

        notice_parts = []
        if disabled_count:
            notice_parts.append(f"تم تعطيل {disabled_count} توكن غير صالح")
        if temporary_count:
            notice_parts.append(f"تم تجاوز {temporary_count} توكن بسبب خطأ مؤقت")
        notice = " — ".join(notice_parts) if notice_parts else None
        return valid_tokens, [member.id for member in members], notice

    async def stop_broadcast(self, guild_id: int) -> bool:
        job = self._active_broadcasts.get(guild_id)
        if not job:
            return False
        job["stop_event"].set()
        return True

    async def _launch_broadcast(
        self,
        guild: discord.Guild,
        status_message: discord.Message,
        tokens: list[str],
        member_ids: list[int],
        message: str,
        start_index: int = 0,
        initial_done: int = 0,
        initial_failed: int = 0,
    ) -> bool:
        if guild.id in self._active_broadcasts:
            return False

        stop_event = asyncio.Event()
        self._active_broadcasts[guild.id] = {
            "stop_event": stop_event,
            "task": None,
        }
        campaign = {
            "status": "running",
            "channel_id": status_message.channel.id,
            "message_id": status_message.id,
            "member_ids": member_ids,
            "message": message,
            "cursor": start_index,
            "done": initial_done,
            "failed": initial_failed,
            "started_at": _now_iso(),
            "last_error": None,
        }
        await Storage.update_guild(
            guild.id,
            TOKEN_SECTION,
            {"campaign": campaign},
        )

        async def safe_progress(done: int, failed: int):
            campaign_update = {
                **campaign,
                "cursor": done + failed,
                "done": done,
                "failed": failed,
                "status": "running",
            }
            campaign.update(campaign_update)
            await Storage.update_guild(
                guild.id,
                TOKEN_SECTION,
                {"campaign": campaign_update},
            )
            try:
                await status_message.edit(
                    embed=_broadcast_embed(
                        "جاري إرسال البرودكاست",
                        len(member_ids),
                        done,
                        failed,
                        discord.Color.teal(),
                    ),
                    view=BroadcastStopView(self, guild.id),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        async def on_done(done: int, failed: int, stopped: bool):
            title = "تم إيقاف البرودكاست" if stopped else "تم الانتهاء من البرودكاست"
            color = discord.Color.orange() if stopped else discord.Color.green()
            campaign_update = {
                **campaign,
                "status": "stopped" if stopped else "completed",
                "cursor": done + failed,
                "done": done,
                "failed": failed,
                "finished_at": _now_iso(),
            }
            campaign.update(campaign_update)
            await Storage.update_guild(
                guild.id,
                TOKEN_SECTION,
                {"campaign": campaign_update},
            )
            try:
                await status_message.edit(
                    embed=_broadcast_embed(
                        title,
                        len(member_ids),
                        done,
                        failed,
                        color,
                    ),
                    view=None,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        async def worker():
            try:
                await run_broadcast(
                    tokens,
                    member_ids,
                    message,
                    stop_event,
                    safe_progress,
                    on_done,
                    start_index,
                    initial_done,
                    initial_failed,
                )
            except Exception:
                logger.exception("Broadcast worker failed for guild %s", guild.id)
                await Storage.update_guild(
                    guild.id,
                    TOKEN_SECTION,
                    {
                        "campaign": {
                            **campaign,
                            "status": "error",
                            "last_error": "worker_failed",
                        }
                    },
                )
                try:
                    await status_message.edit(
                        content="❌ توقف البرودكاست بسبب خطأ غير متوقع.",
                        view=None,
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            finally:
                self._active_broadcasts.pop(guild.id, None)

        task = asyncio.create_task(worker())
        self._active_broadcasts[guild.id]["task"] = task
        return True

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
            tokens = _token_records(config.get("tokens", []))
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
        records = _token_records(config.get("tokens", []))
        try:
            for record in records:
                try:
                    if decrypt_token(record["encrypted_token"]) == token:
                        await interaction.followup.send(
                            "هذا البوت موجود بالفعل.",
                            ephemeral=True,
                        )
                        return
                except Exception:
                    continue

            bot_user, reason = await self._validate_plain_token(token)
            if bot_user is None:
                message = (
                    "التوكن غير صالح."
                    if reason == "invalid_token"
                    else "تعذر فحص التوكن حالياً. حاول مرة ثانية."
                )
                await interaction.followup.send(message, ephemeral=True)
                return

            bot_tag = str(bot_user)
            bot_id = bot_user.id
            record = {
                "id": f"bot_{bot_user.id}",
                "name": str(bot_user),
                "bot_id": bot_user.id,
                "encrypted_token": encrypt_token(token),
                "status": "valid",
                "last_checked_at": _now_iso(),
                "last_error": None,
            }
            if any(item.get("id") == record["id"] for item in records):
                await interaction.followup.send(
                    "هذا البوت موجود بالفعل.",
                    ephemeral=True,
                )
                return
            records.append(record)
            await Storage.update_guild(
                interaction.guild.id,
                TOKEN_SECTION,
                {"tokens": records},
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
            logger.exception("Broadcast token operation failed for guild %s", interaction.guild.id)
            await interaction.followup.send(
                "تعذر حفظ البوت. تأكد من إعداد BC_ENCRYPT_KEY وحاول مرة ثانية.",
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
        message = config.get("message")
        if not message:
            await interaction.followup.send("لم يتم تحديد رسالة البرودكاست.")
            return

        tokens, member_ids, notice = await self._prepare_broadcast(
            interaction.guild, audience
        )
        if tokens is None:
            await interaction.followup.send(notice)
            return

        total = len(member_ids)
        status_message = await interaction.followup.send(
            embed=_broadcast_embed(
                "جاري تجهيز البرودكاست",
                total,
                0,
                0,
                discord.Color.teal(),
            ),
            content=notice,
            view=BroadcastStopView(self, interaction.guild.id),
            wait=True,
        )
        started = await self._launch_broadcast(
            interaction.guild,
            status_message,
            tokens,
            member_ids,
            message,
        )
        if not started:
            await status_message.edit(
                content="في برودكاست شغال حالياً بهذا السيرفر.",
                embed=None,
                view=None,
            )

    async def _start_from_channel(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        audience: str,
        message: str,
    ):
        """مسار الأوامر النصية !bc و !obc."""
        tokens, member_ids, notice = await self._prepare_broadcast(guild, audience)
        if tokens is None:
            await channel.send(notice)
            return

        total = len(member_ids)
        status_message = await channel.send(
            embed=_broadcast_embed(
                "جاري تجهيز البرودكاست",
                total,
                0,
                0,
                discord.Color.teal(),
            ),
            content=notice,
            view=BroadcastStopView(self, guild.id),
        )
        started = await self._launch_broadcast(
            guild,
            status_message,
            tokens,
            member_ids,
            message,
        )
        if not started:
            await status_message.edit(
                content="في برودكاست شغال حالياً بهذا السيرفر.",
                embed=None,
                view=None,
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

    @app_commands.command(
        name="broadcast-bots",
        description="عرض بوتات البرودكاست وحالتها بدون إظهار التوكنات",
    )
    @app_commands.guild_only()
    async def broadcast_bots(self, interaction: discord.Interaction):
        if interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message(
                "هذا الأمر مخصص لمالك السيرفر فقط.", ephemeral=True
            )
            return

        config = await self._config(interaction.guild.id)
        records = _token_records(config.get("tokens", []))
        if not records:
            await interaction.response.send_message(
                "ما في بوتات برودكاست مسجلة حالياً.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🤖 بوتات البرودكاست",
            description="الحذف يتم باستخدام المعرّف فقط. التوكنات لا تظهر هنا.",
            color=discord.Color.teal(),
        )
        for record in records[:25]:
            status = {
                "valid": "✅ صالح",
                "disabled": "⛔ معطّل",
                "error": "⚠️ خطأ مؤقت",
                "pending": "⏳ يحتاج فحص",
            }.get(record.get("status"), "❔ غير معروف")
            value = (
                f"المعرّف: `{record.get('id', '—')}`\n"
                f"Bot ID: `{record.get('bot_id') or '—'}`\n"
                f"الحالة: {status}"
            )
            if record.get("last_checked_at"):
                value += f"\nآخر فحص: `{record['last_checked_at']}`"
            embed.add_field(
                name=record.get("name") or "بوت بدون اسم",
                value=value,
                inline=False,
            )
        if len(records) > 25:
            embed.set_footer(text=f"يتم عرض أول 25 من أصل {len(records)} بوت")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="remove-token",
        description="إزالة بوت برودكاست باستخدام المعرّف، بدون كتابة التوكن",
    )
    @app_commands.guild_only()
    @app_commands.describe(bot_id="المعرّف الظاهر في أمر /broadcast-bots")
    async def remove_token(self, interaction: discord.Interaction, bot_id: str):
        if interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message(
                "هذا الأمر مخصص لمالك السيرفر فقط.", ephemeral=True
            )
            return
        config = await self._config(interaction.guild.id)
        records = _token_records(config.get("tokens", []))
        remaining = [record for record in records if record.get("id") != bot_id.strip()]
        if len(remaining) == len(records):
            await interaction.response.send_message(
                "ما لقيت بوت بهذا المعرّف. استخدم `/broadcast-bots` أولاً.",
                ephemeral=True,
            )
            return
        await Storage.update_guild(
            interaction.guild.id, TOKEN_SECTION, {"tokens": remaining}
        )
        await interaction.response.send_message(
            "تم إزالة بوت البرودكاست بنجاح، بدون إظهار التوكن.",
            ephemeral=True,
        )
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