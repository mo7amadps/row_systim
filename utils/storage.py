"""
تخزين بسيط مبني على JSON لكل إعدادات السيرفرات (تايم / رتب / باند)
وكمان عدّادات الاستخدام اليومي لكل شخص.
"""

import asyncio
import json
import os
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_configured_data_dir = os.getenv("BOT_DATA_DIR")
if _configured_data_dir:
    DATA_DIR = (
        _configured_data_dir
        if os.path.isabs(_configured_data_dir)
        else os.path.join(BASE_DIR, _configured_data_dir)
    )
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "guilds.json")

_lock = asyncio.Lock()


def _ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _read() -> dict:
    _ensure_files()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        # احتفظ بنسخة احتياطية إذا انقطع التخزين أثناء عملية قديمة،
        # ثم ابدأ بملف صالح بدل إيقاف البوت بالكامل.
        corrupt_file = f"{DATA_FILE}.corrupt"
        try:
            os.replace(DATA_FILE, corrupt_file)
        except OSError:
            pass
        _write({})
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict):
    # اكتب إلى ملف مؤقت ثم استبدله حتى لا يبقى ملف JSON ناقصاً إذا
    # توقف البوت بشكل مفاجئ أثناء الحفظ.
    os.makedirs(DATA_DIR, exist_ok=True)
    temp_file = f"{DATA_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_file, DATA_FILE)


def xp_needed_for_level(level: int) -> int:
    """مجموع الـ XP التراكمي المطلوب للوصول لهاد المستوى (منحنى معروف - نفس فكرة أشهر بوتات اللفلينج)."""
    total = 0
    for lvl in range(1, level + 1):
        total += 5 * (lvl ** 2) + 50 * lvl + 100
    return total


def _level_from_xp(xp: int) -> int:
    level = 0
    while xp_needed_for_level(level + 1) <= xp:
        level += 1
        if level > 1000:  # حماية بسيطة من حلقة لا نهائية بحالة رقم غريب
            break
    return level


def _default_guild() -> dict:
    import time as _time
    _now = _time.time()
    return {
        "time": {
            "giver_role_ids": [],
            "daily_limit": None,
            "admin_role_id": None,
            "log_channel_id": None,
            "usage": {},   # {user_id: {"date": "YYYY-MM-DD", "count": N}}
            "active": {},  # {target_user_id: giver_user_id}  -> مين عطى مين تايم حالياً
        },
        "role": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "ban": {
            "allowed_role_ids": [],
            "daily_limit": None,
            "unlimited_role_id": None,
            "log_channel_id": None,
            "usage": {},
        },
        "add_role": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "remove_role": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "auto_reply": {
            "trigger_role_id": None,
            "slots": {},  # {"1": {"trigger": "مرحبا", "reply": "اهلين"}, ...}
        },
        "rar": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "nickname": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "warn": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "unwarn": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "warnings": {},  # {user_id: [{"id": "a1b2c3", "reason": "...", "by": mod_id, "at": "iso"}, ...]}
        "role_assign": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "embed_panels": {},  # {panel_id: {title, description, image_url, color, options: [{label,title,text,image_url}]}}
        "broadcast": {
            "tokens": [],
            "message": None,
            "message_id": None,
            "channel_id": None,
            # عند ضبطها يجب أن تجتمع هذه الرتبة مع Administrator
            # لاستخدام البرودكاست.
            "whitelist_role_id": None,
        },
        "unmute": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "unban": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "staff": {
            "allowed_role_ids": [],
            "first_role_id": None,
            "last_role_id": None,
            "tickets_role_id": None,
            "log_channel_id": None,
        },
        "highstaff": {
            "allowed_role_ids": [],
            "first_role_id": None,
            "last_role_id": None,
            "tickets_role_id": None,
            "log_channel_id": None,
        },
        "owner": {
            "allowed_role_ids": [],
            "first_role_id": None,
            "last_role_id": None,
            "tickets_role_id": None,
            "log_channel_id": None,
        },
        "dismiss": {
            "allowed_role_ids": [],
            "protect_role_id": None,
            "log_channel_id": None,
        },
        "lock": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "unlock": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "clear": {
            "allowed_role_ids": [],
            "log_channel_id": None,
        },
        "prison": {
            "imprison_role_ids": [],   # مين يقدر يستخدم أمر سجن
            "release_role_ids": [],    # مين يقدر يستخدم أمر انسجن / فك السجن
            "jail_role_id": None,      # الرتبة يلي تُعطى وقت السجن وتُشال وقت الفك
            "prison_channel_id": None, # روم السجن يلي بضل ظاهر للمسجون بس
            "log_channel_id": None,
            "jailed": {},  # {user_id: {"roles": [role_id, ...], "by": mod_id, "reason": str|None, "at": iso}}
        },
        "security": {
            "bot_add": {
                "allowed_role_ids": [],
                "log_channel_id": None,
                "notify_role_id": None,
                "jail_role_id": None,
            },
            "prune": {
                "allowed_role_ids": [],
                "log_channel_id": None,
                "notify_role_id": None,
                "jail_role_id": None,
            },
            "webhook": {
                "allowed_role_ids": [],
                "log_channel_id": None,
                "notify_role_id": None,
                "jail_role_id": None,
            },
            "channels": {
                "allowed_role_ids": [],
                "log_channel_id": None,
                "notify_role_id": None,
                "jail_role_id": None,
            },
            "roles": {
                "allowed_role_ids": [],
                "log_channel_id": None,
                "notify_role_id": None,
                "jail_role_id": None,
            },
        },
        "xp": {
            "xp_min": 1,
            "xp_max": 4,
            "cooldown_seconds": 60,
            "levelup_channel_id": None,   # None => نفس روم الرسالة يلي عملت اللفل أب
            "log_channel_id": None,
            "no_xp_role_ids": [],
            "no_xp_channel_ids": [],   # عام: مو محتسبة فيه لا خبرة كتابة ولا فويس
            "role_rewards": {},   # {"5": role_id, "10": role_id, ...}  مستوى -> رتبة
            "users": {},           # {user_id: {"xp": N, "level": N, "xp_day": N, "xp_week": N, "last_at": epoch_float}}
        },
        "voice_xp": {
            "xp_per_minute": 2,
            "users": {},   # {user_id: {"xp": N, "level": N, "xp_day": N, "xp_week": N}}
        },
        "xp_period": {
            "day_reset_at": _now,
            "week_reset_at": _now,
        },
        "quest_staff": {
            "allowed_role_ids": [],
            "stopper_role_id": None,   # رتبة إضافية (متل ستريتر) فيها توقف أي مهمة من هاد التصنيف
            "room_channel_id": None,
            "xp_amount": None,
            "reward": None,   # نص الجائزة، أو منشن رتبة "<@&ID>" لو النوع ترقية
            "log_channel_id": None,
            "rank_ladder_role_ids": [],   # سلّم رتب مرتب من الأقل للأعلى - يستخدم لنوع «ترقية»
        },
        "quest_highstaff": {
            "allowed_role_ids": [],
            "stopper_role_id": None,
            "room_channel_id": None,
            "xp_amount": None,
            "reward": None,
            "log_channel_id": None,
            "rank_ladder_role_ids": [],
        },
        "quest_owner": {
            "allowed_role_ids": [],
            "stopper_role_id": None,
            "room_channel_id": None,
            "xp_amount": None,
            "reward": None,
            "log_channel_id": None,
            "rank_ladder_role_ids": [],
        },
        "quests": {
            "active": {},   # {"staff": {...quest...}, "highstaff": {...}, "owner": {...}}
        },
    }


class Storage:
    @staticmethod
    async def initialize():
        """Ensure the persistent settings file exists before the bot starts."""
        async with _lock:
            _ensure_files()

    @staticmethod
    async def get_guild(guild_id: int) -> dict:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            merged = _default_guild()
            existing = data.get(gid, {})
            for section in merged:
                merged[section].update(existing.get(section, {}))
            return merged

    @staticmethod
    async def update_guild(guild_id: int, section: str, updates: dict):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault(section, {})
            data[gid][section].update(updates)
            _write(data)

    @staticmethod
    async def update_security(guild_id: int, subsection: str, updates: dict):
        """subsection: 'bot_add' | 'prune' | 'webhook' | 'channels' | 'roles'"""
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("security", _default_guild()["security"])
            default_sub = _default_guild()["security"][subsection]
            existing_sub = data[gid]["security"].get(subsection, {})
            data[gid]["security"][subsection] = {**default_sub, **existing_sub, **updates}
            _write(data)

    # ---------- الحدود اليومية ----------

    @staticmethod
    async def get_usage(guild_id: int, section: str, user_id: int) -> int:
        today = date.today().isoformat()
        async with _lock:
            data = _read()
            gid = str(guild_id)
            usage = data.get(gid, {}).get(section, {}).get("usage", {})
            entry = usage.get(str(user_id))
            if not entry or entry.get("date") != today:
                return 0
            return entry.get("count", 0)

    @staticmethod
    async def increment_usage(guild_id: int, section: str, user_id: int):
        today = date.today().isoformat()
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault(section, {})
            data[gid][section].setdefault("usage", {})
            usage = data[gid][section]["usage"]
            entry = usage.get(str(user_id))
            if not entry or entry.get("date") != today:
                entry = {"date": today, "count": 0}
            entry["count"] += 1
            usage[str(user_id)] = entry
            _write(data)

    # ---------- مين عطى مين تايم (عشان أمر ان) ----------

    @staticmethod
    async def set_timeout_giver(guild_id: int, target_id: int, giver_id: int):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("time", {}).setdefault("active", {})
            data[gid]["time"]["active"][str(target_id)] = giver_id
            _write(data)

    @staticmethod
    async def get_timeout_giver(guild_id: int, target_id: int):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            return data.get(gid, {}).get("time", {}).get("active", {}).get(str(target_id))

    @staticmethod
    async def clear_timeout_giver(guild_id: int, target_id: int):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            active = data.get(gid, {}).get("time", {}).get("active", {})
            active.pop(str(target_id), None)
            _write(data)

    # ---------- التحذيرات (عشان تحذير و شيل) ----------

    @staticmethod
    async def add_warning(guild_id: int, user_id: int, reason: str, moderator_id: int) -> str:
        import uuid
        from datetime import datetime, timezone

        warning_id = uuid.uuid4().hex[:6]
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("warnings", {})
            data[gid]["warnings"].setdefault(str(user_id), [])
            data[gid]["warnings"][str(user_id)].append({
                "id": warning_id,
                "reason": reason,
                "by": moderator_id,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            _write(data)
        return warning_id

    @staticmethod
    async def get_warnings(guild_id: int, user_id: int) -> list:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            return list(data.get(gid, {}).get("warnings", {}).get(str(user_id), []))

    @staticmethod
    async def remove_warning(guild_id: int, user_id: int, warning_id: str) -> bool:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            warnings = data.get(gid, {}).get("warnings", {}).get(str(user_id), [])
            new_list = [w for w in warnings if w.get("id") != warning_id]
            removed = len(new_list) != len(warnings)
            if removed:
                data[gid]["warnings"][str(user_id)] = new_list
                _write(data)
            return removed

    # ---------- نظام السجن (عشان أمر سجن / انسجن) ----------

    @staticmethod
    async def set_jailed(guild_id: int, user_id: int, entry: dict):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("prison", _default_guild()["prison"])
            data[gid]["prison"].setdefault("jailed", {})
            data[gid]["prison"]["jailed"][str(user_id)] = entry
            _write(data)

    @staticmethod
    async def get_jailed(guild_id: int, user_id: int):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            return data.get(gid, {}).get("prison", {}).get("jailed", {}).get(str(user_id))

    @staticmethod
    async def remove_jailed(guild_id: int, user_id: int):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            jailed = data.get(gid, {}).get("prison", {}).get("jailed", {})
            removed = jailed.pop(str(user_id), None)
            if removed is not None:
                _write(data)
            return removed

    @staticmethod
    async def list_jailed(guild_id: int) -> dict:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            return dict(data.get(gid, {}).get("prison", {}).get("jailed", {}))

    # ---------- بانلات الإمبد (embed panels) ----------

    MAX_PANELS_PER_GUILD = 5
    MAX_OPTIONS_PER_PANEL = 6

    @staticmethod
    async def create_embed_panel(guild_id: int, panel_id: str, panel_data: dict) -> str:
        """يرجع 'ok' أو رسالة خطأ إذا اتعدى الحد أو الاسم مكرر."""
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("embed_panels", {})
            panels = data[gid]["embed_panels"]
            if panel_id in panels:
                return "duplicate"
            if len(panels) >= Storage.MAX_PANELS_PER_GUILD:
                return "limit"
            panels[panel_id] = panel_data
            _write(data)
            return "ok"

    @staticmethod
    async def delete_embed_panel(guild_id: int, panel_id: str) -> bool:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            panels = data.get(gid, {}).get("embed_panels", {})
            if panel_id not in panels:
                return False
            del panels[panel_id]
            _write(data)
            return True

    @staticmethod
    async def get_embed_panel(guild_id: int, panel_id: str):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            return data.get(gid, {}).get("embed_panels", {}).get(panel_id)

    @staticmethod
    async def list_embed_panels(guild_id: int) -> dict:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            return dict(data.get(gid, {}).get("embed_panels", {}))

    @staticmethod
    async def add_embed_option(guild_id: int, panel_id: str, option: dict) -> str:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            panels = data.get(gid, {}).get("embed_panels", {})
            if panel_id not in panels:
                return "not_found"
            options = panels[panel_id].setdefault("options", [])
            if any(o["label"] == option["label"] for o in options):
                return "duplicate"
            if len(options) >= Storage.MAX_OPTIONS_PER_PANEL:
                return "limit"
            options.append(option)
            _write(data)
            return "ok"

    @staticmethod
    async def remove_embed_option(guild_id: int, panel_id: str, label: str) -> bool:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            panels = data.get(gid, {}).get("embed_panels", {})
            if panel_id not in panels:
                return False
            options = panels[panel_id].get("options", [])
            new_list = [o for o in options if o["label"] != label]
            removed = len(new_list) != len(options)
            if removed:
                panels[panel_id]["options"] = new_list
                _write(data)
            return removed

    @staticmethod
    async def iter_all_panels():
        """لتسجيل الـ Views الدائمة (persistent views) من جديد لما البوت يعيد التشغيل."""
        async with _lock:
            data = _read()
            result = []
            for gid, gdata in data.items():
                for panel_id, panel_data in gdata.get("embed_panels", {}).items():
                    result.append((int(gid), panel_id, panel_data))
            return result

    # ---------- نظام الـ XP (نفس ستايل نوفا: XP لكل رسالة + فويس + مستويات + رتب مكافآت) ----------
    # bucket: "xp" (كتابة) أو "voice_xp" (فويس) - نفس الشكل بالضبط لتوحيد المنطق.

    @staticmethod
    async def add_xp(guild_id: int, user_id: int, bucket: str, amount: int, cooldown_seconds: int = 0):
        """
        بتضيف XP محسوب مسبقاً لبكت معين (xp أو voice_xp) مع احترام كولداون اختياري.
        بترجع dict: {"gained": N, "total_xp": N, "old_level": N, "new_level": N}
        - لو amount صفر أو أقل ما منلمس الكولداون أصلاً.
        - لو الشخص لسا بالكولداون (وcooldown_seconds > 0)، gained بيكون 0 بدون تغيير.
        """
        import time

        if amount <= 0:
            entry = await Storage._get_bucket_user(guild_id, user_id, bucket)
            return {
                "gained": 0,
                "total_xp": entry.get("xp", 0),
                "old_level": entry.get("level", 0),
                "new_level": entry.get("level", 0),
            }

        now = time.time()
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault(bucket, _default_guild()[bucket])
            data[gid][bucket].setdefault("users", {})
            users = data[gid][bucket]["users"]
            uid = str(user_id)
            entry = users.get(uid, {"xp": 0, "level": 0, "xp_day": 0, "xp_week": 0, "last_at": 0})

            if cooldown_seconds and now - entry.get("last_at", 0) < cooldown_seconds:
                return {
                    "gained": 0,
                    "total_xp": entry.get("xp", 0),
                    "old_level": entry.get("level", 0),
                    "new_level": entry.get("level", 0),
                }

            old_level = entry.get("level", 0)
            new_xp = entry.get("xp", 0) + amount
            new_level = _level_from_xp(new_xp)

            users[uid] = {
                "xp": new_xp,
                "level": new_level,
                "xp_day": entry.get("xp_day", 0) + amount,
                "xp_week": entry.get("xp_week", 0) + amount,
                "last_at": now,
            }
            _write(data)
            return {
                "gained": amount,
                "total_xp": new_xp,
                "old_level": old_level,
                "new_level": new_level,
            }

    @staticmethod
    async def _get_bucket_user(guild_id: int, user_id: int, bucket: str) -> dict:
        async with _lock:
            data = _read()
            gid = str(guild_id)
            entry = data.get(gid, {}).get(bucket, {}).get("users", {}).get(str(user_id))
            return dict(entry) if entry else {"xp": 0, "level": 0, "xp_day": 0, "xp_week": 0, "last_at": 0}

    @staticmethod
    async def get_xp_user(guild_id: int, user_id: int, bucket: str = "xp") -> dict:
        return await Storage._get_bucket_user(guild_id, user_id, bucket)

    @staticmethod
    async def set_xp_user(guild_id: int, user_id: int, xp: int, bucket: str = "xp"):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault(bucket, _default_guild()[bucket])
            data[gid][bucket].setdefault("users", {})
            level = _level_from_xp(max(xp, 0))
            existing = data[gid][bucket]["users"].get(str(user_id), {})
            data[gid][bucket]["users"][str(user_id)] = {
                "xp": max(xp, 0),
                "level": level,
                "xp_day": existing.get("xp_day", 0),
                "xp_week": existing.get("xp_week", 0),
                "last_at": existing.get("last_at", 0),
            }
            _write(data)
            return {"xp": max(xp, 0), "level": level}

    @staticmethod
    async def get_leaderboard(guild_id: int, bucket: str, period: str, limit: int = None) -> list:
        """period: 'all' | 'day' | 'week' - بترجع [(user_id, entry), ...] مرتبة تنازلي، بدون أصحاب صفر."""
        field = {"all": "xp", "day": "xp_day", "week": "xp_week"}.get(period, "xp")
        async with _lock:
            data = _read()
            gid = str(guild_id)
            users = data.get(gid, {}).get(bucket, {}).get("users", {})
            ranked = sorted(
                ((uid, e) for uid, e in users.items() if e.get(field, 0) > 0),
                key=lambda kv: kv[1].get(field, 0),
                reverse=True,
            )
            if limit:
                ranked = ranked[:limit]
            return [(int(uid), entry) for uid, entry in ranked]

    @staticmethod
    async def get_xp_leaderboard(guild_id: int, limit: int = 10) -> list:
        """للتوافق مع كود قديم - نفس get_leaderboard(bucket='xp', period='all')."""
        return await Storage.get_leaderboard(guild_id, "xp", "all", limit)

    @staticmethod
    async def reset_period_counters_if_needed(guild_id: int):
        """بتصفر عدّادات اليوم/الأسبوع (xp_day / xp_week) لكل المستخدمين لو الوقت فات، لبكتي xp وvoice_xp."""
        import time

        now = time.time()
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("xp_period", {"day_reset_at": now, "week_reset_at": now})
            period = data[gid]["xp_period"]

            changed = False
            reset_day = now - period.get("day_reset_at", 0) >= 86400
            reset_week = now - period.get("week_reset_at", 0) >= 604800

            if reset_day or reset_week:
                for bucket in ("xp", "voice_xp"):
                    data[gid].setdefault(bucket, _default_guild()[bucket])
                    users = data[gid][bucket].setdefault("users", {})
                    for uid, entry in users.items():
                        if reset_day:
                            entry["xp_day"] = 0
                        if reset_week:
                            entry["xp_week"] = 0
                changed = True

            if reset_day:
                period["day_reset_at"] = now
            if reset_week:
                period["week_reset_at"] = now

            if changed:
                _write(data)

    # ---------- نظام المهام التلقائي ----------

    @staticmethod
    async def get_active_quest(guild_id: int, tier: str):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            return data.get(gid, {}).get("quests", {}).get("active", {}).get(tier)

    @staticmethod
    async def get_all_active_quests() -> list:
        """بترجع [(guild_id, tier, quest_dict), ...] لكل السيرفرات - تُستخدم لمهمة الإنهاء التلقائي."""
        async with _lock:
            data = _read()
            result = []
            for gid, gdata in data.items():
                for tier, quest in gdata.get("quests", {}).get("active", {}).items():
                    if quest:
                        result.append((int(gid), tier, quest))
            return result

    @staticmethod
    async def set_active_quest(guild_id: int, tier: str, quest_data: dict):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("quests", {"active": {}})
            data[gid]["quests"].setdefault("active", {})
            data[gid]["quests"]["active"][tier] = quest_data
            _write(data)

    @staticmethod
    async def clear_active_quest(guild_id: int, tier: str):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            active = data.get(gid, {}).get("quests", {}).get("active", {})
            removed = active.pop(tier, None)
            if removed is not None:
                _write(data)
            return removed

    @staticmethod
    async def add_quest_progress(guild_id: int, tier: str, user_id: int, amount: int):
        """
        بتضيف تقدّم لمشارك بمهمة تصنيف معين (لو فيه مهمة فعّالة أصلاً لهاد التصنيف).
        بترجع None لو ما في مهمة فعّالة، وإلا dict فيه:
        {"progress": N, "goal": N, "just_completed": bool, "quest": quest_dict}
        """
        async with _lock:
            data = _read()
            gid = str(guild_id)
            quest = data.get(gid, {}).get("quests", {}).get("active", {}).get(tier)
            if not quest:
                return None

            uid = str(user_id)
            quest.setdefault("progress", {})
            quest.setdefault("completed_users", [])

            already_completed = uid in quest["completed_users"]
            new_progress = quest["progress"].get(uid, 0) + amount
            quest["progress"][uid] = new_progress

            just_completed = False
            goal = quest.get("goal", 0)
            if not already_completed and goal and new_progress >= goal:
                quest["completed_users"].append(uid)
                just_completed = True

            data[gid]["quests"]["active"][tier] = quest
            _write(data)
            return {
                "progress": new_progress,
                "goal": goal,
                "just_completed": just_completed,
                "quest": dict(quest),
            }

    # ---------- الردود التلقائية ----------

    @staticmethod
    async def set_reply_slot(guild_id: int, slot_number: str, trigger: str, reply: str):
        async with _lock:
            data = _read()
            gid = str(guild_id)
            if gid not in data:
                data[gid] = _default_guild()
            data[gid].setdefault("auto_reply", {"trigger_role_id": None, "slots": {}})
            data[gid]["auto_reply"].setdefault("slots", {})
            data[gid]["auto_reply"]["slots"][str(slot_number)] = {"trigger": trigger, "reply": reply}
            _write(data)
