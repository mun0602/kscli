"""SQLite persistence layer for KuaishouBot Qt."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from kscli.models.schemas import ActionLog, BotSettings, DailyStats

APP_DATA_DIR = os.path.expanduser("~/.kuaishou_desktop_qt")
DB_PATH = os.path.join(APP_DATA_DIR, "kuaishou.db")
COMMENTS_PATH = os.path.join(APP_DATA_DIR, "comments.json")


class Database:
    """Manages all SQLite persistence."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS app_meta (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS actions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           TEXT NOT NULL,
                device_index INTEGER NOT NULL,
                action       TEXT NOT NULL,
                success      INTEGER NOT NULL,
                detail       TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                stat_date    TEXT NOT NULL,
                device_index INTEGER NOT NULL,
                likes        INTEGER NOT NULL DEFAULT 0,
                follows      INTEGER NOT NULL DEFAULT 0,
                comments     INTEGER NOT NULL DEFAULT 0,
                addfriends   INTEGER NOT NULL DEFAULT 0,
                videos_watched INTEGER NOT NULL DEFAULT 0,
                failures     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (stat_date, device_index)
            );
        """)
        self.conn.commit()

        # Migration: add addfriends column if missing
        try:
            self.conn.execute("SELECT addfriends FROM daily_stats LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE daily_stats ADD COLUMN addfriends INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()

    # ── Settings ──────────────────────────────────────────────
    def save_settings(self, settings: BotSettings) -> None:
        now = datetime.now().isoformat()
        data = json.dumps(settings.__dict__, ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO app_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("bot_settings", data, now),
            )
            self.conn.commit()

    def load_settings(self) -> BotSettings:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM app_meta WHERE key = ?", ("bot_settings",)
            ).fetchone()
        if row:
            try:
                data = json.loads(row["value"])
                return BotSettings(**data)
            except Exception:
                pass
        return BotSettings()

    # ── Comments ─────────────────────────────────────────────
    def save_comments(self, comments: list[str]) -> None:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        with open(COMMENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(comments, f, ensure_ascii=False, indent=2)

    def load_comments(self) -> list[str]:
        if not os.path.exists(COMMENTS_PATH):
            return []
        try:
            with open(COMMENTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ── Action Logs ──────────────────────────────────────────
    def write_log(self, entry: ActionLog) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO actions (ts, device_index, action, success, detail) VALUES (?,?,?,?,?)",
                (entry.ts, entry.device_index, entry.action, int(entry.success), entry.detail),
            )
            self.conn.commit()

    def daily_summary(self, device_index: int | None = None) -> dict:
        today = date.today().isoformat()
        where = "ts >= ?"
        params: list = [today]
        if device_index is not None:
            where += " AND device_index = ?"
            params.append(device_index)
        cur = self.conn.execute(
            f"""
            SELECT
                CASE
                    WHEN action IN ('liked','like') THEN 'like'
                    WHEN action IN ('followed','follow') THEN 'follow'
                    WHEN action IN ('commented','comment') THEN 'comment'
                    ELSE action
                END AS normalized,
                SUM(success)
            FROM actions
            WHERE {where}
            GROUP BY normalized
            """,
            params,
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    # ── Daily Stats ──────────────────────────────────────────
    def increment_stat(self, device_index: int, action: str, count: int = 1) -> None:
        today = date.today().isoformat()
        col_map = {"like": "likes", "follow": "follows", "comment": "comments", "addfriend": "addfriends", "watch": "videos_watched"}
        col = col_map.get(action)
        if not col:
            return
        with self._lock:
            self.conn.execute(
                f"""
            INSERT INTO daily_stats (stat_date, device_index, {col})
            VALUES (?, ?, ?)
            ON CONFLICT(stat_date, device_index) DO UPDATE SET {col} = {col} + ?
            """,
                (today, device_index, count, count),
            )
            self.conn.commit()

    def get_today_stats(self) -> dict:
        today = date.today().isoformat()
        with self._lock:
            cur = self.conn.execute(
                "SELECT SUM(likes), SUM(follows), SUM(comments), SUM(videos_watched), SUM(addfriends) FROM daily_stats WHERE stat_date = ?",
                (today,),
            )
            row = cur.fetchone()
        if row and row[0] is not None:
            return {"likes": row[0], "follows": row[1], "comments": row[2], "videos": row[3], "addfriends": row[4] or 0}
        return {"likes": 0, "follows": 0, "comments": 0, "videos": 0, "addfriends": 0}

    def close(self) -> None:
        self.conn.close()
