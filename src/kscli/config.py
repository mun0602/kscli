"""Config loader — load 5SIM API key & other settings from ~/.kuaishou_desktop_qt/config.toml"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from dataclasses import dataclass

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # fallback for 3.10

log = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".kuaishou_desktop_qt"
CONFIG_FILE = CONFIG_DIR / "config.toml"

# Default config structure
DEFAULT_CONFIG = """
# Kuaishou Desktop Qt Configuration
# This file contains API keys and settings (NOT committed to git)

[fivesim]
# Get your API key from https://5sim.net/
# Keep this SECRET!
api_key = ""
country = "vietnam"
operator = "any"
product = "kwai"

[kuaishou]
# Account settings
enable_auto_login = false
use_password = false  # if false, use OTP instead
"""


@dataclass
class FiveSimConfig:
    """5SIM API configuration."""
    api_key: str = ""
    country: str = "vietnam"
    operator: str = "any"
    product: str = "kwai"


@dataclass
class KuaishouConfig:
    """Kuaishou application configuration."""
    enable_auto_login: bool = False
    use_password: bool = False


@dataclass
class AppConfig:
    """Main application configuration."""
    fivesim: FiveSimConfig
    kuaishou: KuaishouConfig

    @classmethod
    def load(cls) -> AppConfig:
        """Load configuration from file, or create default if missing."""
        if not CONFIG_FILE.exists():
            log.info(f"⚙️ Config file không tồn tại, tạo mới: {CONFIG_FILE}")
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(DEFAULT_CONFIG)
            log.info(f"  ✅ Tạo file config tại {CONFIG_FILE}")
            log.info(f"  ⚠️ Vui lòng thêm 5SIM API key vào [fivesim] api_key")

        try:
            text = CONFIG_FILE.read_text()
            data = tomllib.loads(text)
        except Exception as e:
            log.error(f"❌ Lỗi đọc config: {e}, dùng default")
            return cls(
                fivesim=FiveSimConfig(),
                kuaishou=KuaishouConfig(),
            )

        fivesim_cfg = data.get("fivesim", {})
        kuaishou_cfg = data.get("kuaishou", {})

        return cls(
            fivesim=FiveSimConfig(
                api_key=fivesim_cfg.get("api_key", ""),
                country=fivesim_cfg.get("country", "vietnam"),
                operator=fivesim_cfg.get("operator", "any"),
                product=fivesim_cfg.get("product", "kwai"),
            ),
            kuaishou=KuaishouConfig(
                enable_auto_login=kuaishou_cfg.get("enable_auto_login", False),
                use_password=kuaishou_cfg.get("use_password", False),
            ),
        )

    @classmethod
    def ensure_config_file(cls) -> None:
        """Ensure config file exists (create if missing)."""
        if not CONFIG_FILE.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(DEFAULT_CONFIG)
            log.info(f"✅ Config file tạo tại {CONFIG_FILE}")


def get_config() -> AppConfig:
    """Get singleton config instance (lazily load)."""
    if not hasattr(get_config, "_instance"):
        get_config._instance = AppConfig.load()
    return get_config._instance


# Try Python 3.11+ tomllib first, then tomli as fallback
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        # Fallback: add tomli to requirements if not present
        log.warning("⚠️ tomli not installed, install with: pip install tomli")
        tomllib = None
