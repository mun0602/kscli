from __future__ import annotations

import logging

from kscli.core.session_runner import FarmWorker
from kscli.models.database import Database
from kscli.models.schemas import BotSettings

log = logging.getLogger(__name__)


class _CliFarmWorker(FarmWorker):
    """Synchronous FarmWorker wrapper for CLI usage."""

    def __init__(
        self,
        settings: BotSettings,
        vm_indices: list[int],
        video_count: int,
        comments: list[str],
        db: Database,
    ):
        super().__init__(
            settings=settings,
            vm_indices=vm_indices,
            video_count=video_count,
            comments=comments,
            db=db,
            parent=None,
        )
        self.cli_logs: list[str] = []

    def _log(self, msg: str) -> None:
        self.cli_logs.append(msg)
        log.info(msg)


def run_cli_farm_session(
    settings: BotSettings,
    vm_indices: list[int],
    video_count: int,
    comments: list[str],
    db: Database,
) -> dict:
    """Run a farm session synchronously for CLI callers."""
    worker = _CliFarmWorker(
        settings=settings,
        vm_indices=vm_indices,
        video_count=video_count,
        comments=comments,
        db=db,
    )
    completed = False
    error: str | None = None

    try:
        worker._do_run()
        completed = not worker._stop_flag
    except Exception as exc:
        error = str(exc)
        worker.cli_logs.append(f"❌ Lỗi nghiêm trọng: {exc}")
        log.exception("CLI farm session failed")

    return {
        "completed": completed and error is None,
        "vm_indices": vm_indices,
        "video_count": video_count,
        "totals": worker._total.copy(),
        "logs": worker.cli_logs,
        "error": error,
    }
