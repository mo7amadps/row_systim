import os
import sqlite3
import json
import asyncio

# Permanent storage database path (Railway Volume or local data directory)
DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "database.db")

_lock = asyncio.Lock()

def _init_db():
    """Create persistent SQLite tables if they do not exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS storage (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()

_init_db()

class Storage:
    @staticmethod
    async def get_guild(guild_id: int) -> dict:
        """Retrieve server settings from SQLite database or initialize default structure."""
        async with _lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM storage WHERE key = ?", (f"guild_{guild_id}",))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                
                default_data = {
                    "ban": {
                        "allowed_role_ids": [],
                        "daily_limit": 0,
                        "unlimited_role_id": None,
                        "log_channel_id": None
                    },
                    "warn": {
                        "allowed_role_ids": [],
                        "log_channel_id": None
                    },
                    "unwarn": {
                        "allowed_role_ids": [],
                        "log_channel_id": None
                    },
                    "nickname": {
                        "allowed_role_ids": [],
                        "log_channel_id": None
                    },
                    "rar": {
                        "allowed_role_ids": [],
                        "log_channel_id": None
                    },
                    "prison": {
                        "allowed_role_ids": [],
                        "jail_role_id": None,
                        "prison_channel_id": None,
                        "log_channel_id": None
                    }
                }
                cursor.execute("INSERT INTO storage (key, value) VALUES (?, ?)", (f"guild_{guild_id}", json.dumps(default_data)))
                conn.commit()
                return default_data

    @staticmethod
    async def update_guild(guild_id: int, section: str, data: dict):
        """Update specific settings section for a guild."""
        async with _lock:
            guild_data = await Storage.get_guild(guild_id)
            if section not in guild_data:
                guild_data[section] = {}
            guild_data[section].update(data)
            
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("REPLACE INTO storage (key, value) VALUES (?, ?)", (f"guild_{guild_id}", json.dumps(guild_data)))
                conn.commit()

    @staticmethod
    async def get_user_bans(guild_id: int, user_id: int) -> dict:
        """Fetch daily ban counts for a user."""
        async with _lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM storage WHERE key = ?", (f"ban_user_{guild_id}_{user_id}",))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return {"count": 0, "last_reset": None}

    @staticmethod
    async def update_user_bans(guild_id: int, user_id: int, count: int, last_reset: str):
        """Update daily ban counter for a user."""
        async with _lock:
            data = {"count": count, "last_reset": last_reset}
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("REPLACE INTO storage (key, value) VALUES (?, ?)", (f"ban_user_{guild_id}_{user_id}", json.dumps(data)))
                conn.commit()
