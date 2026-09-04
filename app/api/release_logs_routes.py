from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import ReleaseLog, User, DownloadClient
from app.services.download_client import get_client
from app.services.user_service import require_permission, require_any_permission, get_current_user

router = APIRouter(prefix="/api/v1/release-logs", tags=["release-logs"])


class ReleaseLogOut(BaseModel):
    id: int
    created_at: dt.datetime
    stage: str
    level: str
    show_id: Optional[int] = None
    show_title: Optional[str] = None
    release_title: Optional[str] = None
    indexer: Optional[str] = None
    message: str
    details: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class ReleaseLogsPageOut(BaseModel):
    items: list[ReleaseLogOut]
    total: int
    page: int
    page_size: int


@router.get("", response_model=ReleaseLogsPageOut)
def list_release_logs(
    stage: Optional[str] = None,
    level: Optional[str] = None,
    query: Optional[str] = None,
    show_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
    sort: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("view_release_logs", "manage_release_logs")),
):
    """Получение журнала логики релизов с пагинацией и фильтрацией."""
    q = db.query(ReleaseLog)

    if stage and stage != "all":
        q = q.filter(ReleaseLog.stage == stage)

    if level and level != "all":
        q = q.filter(ReleaseLog.level == level)

    if show_id is not None:
        q = q.filter(ReleaseLog.show_id == show_id)

    if query:
        search_like = f"%{query.strip()}%"
        q = q.filter(
            (ReleaseLog.show_title.ilike(search_like)) |
            (ReleaseLog.release_title.ilike(search_like)) |
            (ReleaseLog.indexer.ilike(search_like)) |
            (ReleaseLog.message.ilike(search_like))
        )

    total = q.count()
    order_col = ReleaseLog.created_at.desc() if sort == "desc" else ReleaseLog.created_at.asc()
    items = q.order_by(order_col).offset((page - 1) * page_size).limit(page_size).all()

    return ReleaseLogsPageOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/download-client-logs")
async def get_download_client_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("view_release_logs", "manage_release_logs")),
):
    """Возвращает живые диагностические логи и статус всех настроенных активных загрузчиков."""
    clients = db.query(DownloadClient).filter(DownloadClient.enabled == True).all()  # noqa: E712
    result = []

    for dc_row in clients:
        client_info = {
            "id": dc_row.id,
            "name": dc_row.name,
            "type": dc_row.type,
            "host": dc_row.host,
            "port": dc_row.port,
            "diagnostics": {},
            "logs": [],
            "error": None,
        }
        try:
            client_inst = get_client(dc_row)
            client_info["diagnostics"] = await client_inst.get_client_diagnostics()
            client_info["logs"] = await client_inst.get_client_logs(limit=60)
        except Exception as exc:
            client_info["error"] = str(exc)

        result.append(client_info)

    return {"clients": result}


@router.delete("")
def clear_release_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_release_logs")),
):
    """Очистить журнал релизов."""
    count = db.query(ReleaseLog).delete()
    db.commit()
    return {"success": True, "deleted": count, "message": f"Очищено записей: {count}"}


@router.get("/export")
async def export_release_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("view_release_logs", "manage_release_logs")),
):
    """Выгрузить все логи релизов и диагностику загрузчиков в текстовый файл (.txt) для анализа и отладки."""
    logs = db.query(ReleaseLog).order_by(ReleaseLog.created_at.asc()).limit(5000).all()
    lines = []
    lines.append("=== ALIASARR RELEASE LOGS DUMP ===")
    lines.append(f"Generated at: {dt.datetime.utcnow().isoformat()}Z")
    lines.append(f"Total entries: {len(logs)}\n" + "=" * 50 + "\n")

    for l in logs:
        ts = l.created_at.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{ts}] [{l.level.upper()}] [{l.stage.upper()}]")
        if l.show_title:
            lines.append(f"  Show: {l.show_title}")
        if l.release_title:
            lines.append(f"  Release: {l.release_title}")
        if l.indexer:
            lines.append(f"  Indexer: {l.indexer}")
        if l.details and isinstance(l.details, dict):
            src_url = l.details.get("page_url") or l.details.get("download_url")
            if src_url:
                lines.append(f"  Source Link: {src_url}")
        lines.append(f"  Message: {l.message}")
        if l.details:
            import json
            try:
                lines.append(f"  Details: {json.dumps(l.details, ensure_ascii=False)}")
            except Exception:
                pass
        lines.append("-" * 40)

    # Append Download Clients Diagnostics and RPC logs
    lines.append("\n\n" + "=" * 50)
    lines.append("=== DOWNLOAD CLIENTS DIAGNOSTICS & STATUS ===")
    lines.append("=" * 50 + "\n")

    try:
        clients = db.query(DownloadClient).filter(DownloadClient.enabled == True).all()  # noqa: E712
        if not clients:
            lines.append("No active download clients configured.\n")
        for dc_row in clients:
            lines.append(f"Client: {dc_row.name} ({dc_row.type}) at {dc_row.host}:{dc_row.port}")
            try:
                client_inst = get_client(dc_row)
                diag = await client_inst.get_client_diagnostics()
                if diag:
                    lines.append(f"  Version: {diag.get('version') or diag.get('webapi_version') or 'N/A'}")
                    lines.append(f"  Download Speed: {diag.get('download_speed_b_s', 0)} B/s, Upload Speed: {diag.get('upload_speed_b_s', 0)} B/s")
                    if diag.get('free_space_bytes') is not None:
                        lines.append(f"  Free Space: {diag.get('free_space_bytes')} bytes")
                    torrents = diag.get("torrents", [])
                    lines.append(f"  Torrents Count: {len(torrents)}")
                    if torrents:
                        lines.append("  Torrents in Client:")
                        for t in torrents[:30]:
                            pct = round((t.get('progress') or 0) * 100)
                            lines.append(f"    - [{t.get('state', 'unknown')}] {t.get('name', t.get('id', '—'))} ({pct}%, size: {t.get('size')} bytes)")

                logs = await client_inst.get_client_logs(limit=50)
                if logs:
                    lines.append("\n  === Recent Daemon Logs ===")
                    for entry in logs:
                        t_str = entry.get("timestamp") or entry.get("time") or ""
                        msg = entry.get("message") or ""
                        lvl = entry.get("level") or entry.get("type") or ""
                        lines.append(f"    [{t_str}] [lvl:{lvl}] {msg}")
            except Exception as exc:
                lines.append(f"  Client Error: {exc}")
            lines.append("-" * 40)
    except Exception as exc:
        lines.append(f"Error gathering client diagnostics: {exc}")

    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=aliasarr_release_logs.txt"}
    )
