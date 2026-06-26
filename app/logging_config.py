import os
import logging
import sys
import shutil
from datetime import datetime
from logging import LogRecord, Handler

LOG_DIR = "logs"


def _today_folder() -> str:
    """Return the date-stamped sub-folder name for today (e.g. '2026-06-26')."""
    return datetime.now().strftime("%Y-%m-%d")


class DailyFolderRotatingHandler(Handler):
    """Writes logs to ``logs/<YYYY-MM-DD>/gtmflow.log``.

    At midnight the handler atomically switches to a new date folder.
    Old folders beyond ``backup_days`` are pruned automatically.
    """

    def __init__(self, backup_days: int = 30):
        super().__init__()
        self._backup_days = backup_days
        self._formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self._current_date = ""
        self._file = None  # type: ignore[assignment]

    def _open_today(self) -> None:
        """Open (or re-open) the log file for today's date folder."""
        today = _today_folder()
        if today == self._current_date and self._file and not self._file.closed:
            return  # already pointing at the right file
        # Close previous file handle
        self._close()
        # Ensure the folder exists
        day_dir = os.path.join(LOG_DIR, today)
        os.makedirs(day_dir, exist_ok=True)
        path = os.path.join(day_dir, "gtmflow.log")
        self._file = open(path, "a", encoding="utf-8")
        self._current_date = today
        self._prune_old()

    def _close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()
        self._file = None

    def _prune_old(self) -> None:
        """Remove folders in LOG_DIR older than backup_days."""
        if not os.path.isdir(LOG_DIR):
            return
        now = datetime.now()
        for name in os.listdir(LOG_DIR):
            folder_path = os.path.join(LOG_DIR, name)
            if not os.path.isdir(folder_path):
                continue
            try:
                dt = datetime.strptime(name, "%Y-%m-%d")
                if (now - dt).days > self._backup_days:
                    shutil.rmtree(folder_path, ignore_errors=True)
            except ValueError:
                continue  # not a date folder, leave it alone

    def emit(self, record: LogRecord) -> None:
        try:
            self._open_today()
            msg = self._formatter.format(record)
            self._file.write(msg + "\n")
            self._file.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self._close()
        super().close()


def setup_logging():
    """Configure structured logging for the application."""
    logger = logging.getLogger("gtmflow")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler — writes into logs/<YYYY-MM-DD>/gtmflow.log, keeps 30 days
    file_handler = DailyFolderRotatingHandler(backup_days=30)
    logger.addHandler(file_handler)

    return logger


# Initialize logger
logger = setup_logging()
