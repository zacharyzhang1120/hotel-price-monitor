"""Backup routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.backup_service import backup_database, list_backups

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("")
async def get_backups():
    return {"data": list_backups()}


@router.post("/create")
async def create_backup():
    target = backup_database()
    if not target:
        raise HTTPException(status_code=400, detail="当前数据库无法备份或文件不存在")
    return {"filename": target.name, "path": str(target)}
