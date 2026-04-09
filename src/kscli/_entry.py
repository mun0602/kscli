"""Entry point for `dk` CLI command installed via pip.

Sets up logging, PATH, and sys.path before delegating to kscli.cli.run_cli.
"""
from __future__ import annotations

import logging
import os
import sys


def _setup() -> None:
    """One-time setup: PATH, logging, sys.path."""
    # Inject known paths for ADB and other tools
    extra_paths = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        os.path.expanduser("~/Library/Android/sdk/platform-tools"),
    ]
    current = os.environ.get("PATH", "")
    for p in extra_paths:
        if p not in current:
            current = p + ":" + current
    os.environ["PATH"] = current

    # Force qfluentwidgets to use PySide6 (not needed for pure CLI, but keeps compatibility)
    os.environ["QT_API"] = "pyside6"

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> None:
    """CLI entry point — called by `dk` command after pip install."""
    _setup()

    from kscli.cli import run_cli

    raise SystemExit(run_cli())
