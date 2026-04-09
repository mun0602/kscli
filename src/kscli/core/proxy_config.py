"""Proxy configuration loader — pure-Python, no Qt dependency.

Reads proxy settings from ~/.kuaishou_desktop_qt/proxy.json.
Extracted from app.controllers.proxy_controller for CLI independence.
"""
from __future__ import annotations

import json
import os

CONFIG_PATH = os.path.expanduser("~/.kuaishou_desktop_qt/proxy.json")


def load_proxy_config() -> dict | None:
    """Load proxy config from disk. Returns None if disabled or not configured."""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if cfg.get("enabled") else None
    except Exception:
        return None
