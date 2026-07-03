"""SQLite backup service."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

from app.config import BACKUP_DIR, BACKUP_RETENTION_COUNT, DATABASE_URL


def backup_database() -> Optional[Path]:
    source = get_sqlite_database_path()
    if source is None:
        return None
    if not source.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    target = BACKUP_DIR / f"hotel_prices_{stamp}.db"
    shutil.copy2(source, target)
    prune_backups()
    return target


def prune_backups() -> None:
    backups = sorted(BACKUP_DIR.glob("hotel_prices_*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old_backup in backups[BACKUP_RETENTION_COUNT:]:
        old_backup.unlink(missing_ok=True)


def list_backups() -> list[dict]:
    backups = sorted(BACKUP_DIR.glob("hotel_prices_*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "filename": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }
        for path in backups
    ]


def get_sqlite_database_path() -> Optional[Path]:
    if not DATABASE_URL.startswith("sqlite"):
        return None
    parts = urlsplit(DATABASE_URL)
    if not parts.path:
        return None
    return Path(unquote(parts.path))
