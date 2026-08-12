"""
تخزين بسيط مبني على JSON لكل إعدادات السيرفرات (تايم / رتب / باند)
وكمان عدّادات الاستخدام اليومي لكل شخص.
"""

import json
import os
import asyncio
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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


def _default_guild() -> dict:
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
    }


class Storage:
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
