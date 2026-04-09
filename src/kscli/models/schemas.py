"""Data models for KuaishouBot Qt."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BotSettings:
    """Bot-wide settings, persisted to SQLite."""
    machine_count: int = 2
    slot_count: int = 2
    video_min: int = 5
    video_max: int = 10
    watch_min_sec: int = 5
    watch_max_sec: int = 12
    like_enabled: bool = True
    follow_enabled: bool = True
    comment_enabled: bool = False
    addfriend_enabled: bool = False
    daytime_only: bool = True
    like_rate: int = 100
    follow_rate: int = 100
    comment_rate: int = 0
    addfriend_rate: int = 0
    addfriend_delay_min: float = 1.0   # giây chờ tối thiểu giữa các lần kết bạn
    addfriend_delay_max: float = 3.0   # giây chờ tối đa giữa các lần kết bạn
    addfriend_min: int = 1
    addfriend_max: int = 3
    proxy_enabled: bool = False
    proxy_type: str = "http"
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_username: str = ""
    proxy_password: str = ""
    action_delay_min: float = 0.5
    action_delay_max: float = 1.5
    swipe_delay_min: float = 2.5
    swipe_delay_max: float = 4.5


@dataclass
class VMInfo:
    """Virtual machine info from MuMu."""
    index: int
    name: str
    status: str  # "running" | "stopped"
    adb_port: int = 0


@dataclass
class ActionLog:
    """Single bot action record."""
    device_index: int
    action: str  # "like" | "follow" | "comment" | "addfriend" | "watch" | "swipe"
    success: bool
    detail: str = ""
    ts: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DailyStats:
    """Aggregated daily stats per device."""
    stat_date: str
    device_index: int
    likes: int = 0
    follows: int = 0
    comments: int = 0
    addfriends: int = 0
    videos_watched: int = 0
    failures: int = 0


@dataclass
class SessionState:
    """Runtime state of a single device session."""
    device_index: int
    status: str = "idle"  # idle|starting|running|stopping|failed|completed
    started_at: str | None = None
    ended_at: str | None = None
    actions_completed: int = 0
    last_message: str = ""
