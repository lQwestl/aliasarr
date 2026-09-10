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
    session_id: Optional[str] = None
    trigger: Optional[str] = None
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
    session_id: Optional[str] = None,
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

    if session_id:
        q = q.filter(ReleaseLog.session_id == session_id)

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


@router.delete("")
def clear_release_logs(
    show_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_release_logs")),
):
    """Очистить журнал релизов (все записи или записи для конкретного тайтла)."""
    q = db.query(ReleaseLog)
    real_show_id = show_id if isinstance(show_id, int) and not isinstance(show_id, bool) else None
    if real_show_id is not None:
        q = q.filter(ReleaseLog.show_id == real_show_id)
    count = q.delete(synchronize_session=False)
    db.commit()
    msg = f"Очищено записей для тайтла {real_show_id}: {count}" if real_show_id is not None else f"Очищено записей: {count}"
    return {"success": True, "deleted": count, "show_id": real_show_id, "message": msg}


@router.get("/export")
async def export_release_logs(
    show_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("view_release_logs", "manage_release_logs")),
):
    """Выгрузить логи релизов (все или конкретного тайтла) и диагностику загрузчиков в текстовый файл (.txt) для анализа и отладки."""
    q = db.query(ReleaseLog)
    show_obj = None
    real_show_id = show_id if isinstance(show_id, int) and not isinstance(show_id, bool) else None
    if real_show_id is not None:
        q = q.filter(ReleaseLog.show_id == real_show_id)
        from app.models.db import Show
        try:
            show_obj = db.query(Show).filter(Show.id == real_show_id).first()
        except Exception:
            show_obj = None

    logs = q.order_by(ReleaseLog.created_at.asc()).limit(5000).all()
    lines = []
    if show_obj and isinstance(getattr(show_obj, "title", None), str):
        year_val = getattr(show_obj, "year", None)
        year_str = f" ({year_val})" if isinstance(year_val, (int, str)) else ""
        lines.append(f"=== ALIASARR RELEASE LOGS: {show_obj.title}{year_str} ===")
        if isinstance(getattr(show_obj, "id", None), int):
            lines.append(f"Show ID: {show_obj.id}")
        if isinstance(getattr(show_obj, "content_type", None), str):
            lines.append(f"Content Type: {show_obj.content_type}")
        if isinstance(getattr(show_obj, "path", None), str):
            lines.append(f"Library Path: {show_obj.path}")
    else:
        lines.append("=== ALIASARR RELEASE LOGS DUMP ===")
    lines.append(f"Generated at: {dt.datetime.utcnow().isoformat()}Z")
    lines.append(f"Total entries: {len(logs)}\n" + "=" * 50 + "\n")

    for l in logs:
        ts = l.created_at.strftime("%Y-%m-%d %H:%M:%S")
        trigger_info = f" [TRIG:{l.trigger.upper()}]" if getattr(l, "trigger", None) and isinstance(l.trigger, str) else ""
        lines.append(f"[{ts}] [{l.level.upper()}] [{l.stage.upper()}]{trigger_info}")
        if getattr(l, "show_title", None) and isinstance(l.show_title, str):
            lines.append(f"  Show: {l.show_title}")
        if getattr(l, "release_title", None) and isinstance(l.release_title, str):
            lines.append(f"  Release: {l.release_title}")
        if getattr(l, "indexer", None) and isinstance(l.indexer, str):
            lines.append(f"  Indexer: {l.indexer}")
        if getattr(l, "session_id", None) and isinstance(l.session_id, str):
            lines.append(f"  Session ID: {l.session_id}")
        if getattr(l, "details", None) and isinstance(l.details, dict):
            src_url = l.details.get("page_url") or l.details.get("download_url")
            if src_url and isinstance(src_url, str):
                lines.append(f"  Source Link: {src_url}")
        lines.append(f"  Message: {l.message}")
        if getattr(l, "details", None) and isinstance(l.details, dict):
            import json
            try:
                lines.append(f"  Details: {json.dumps(l.details, ensure_ascii=False)}")
            except Exception:
                pass
        lines.append("-" * 40)

    # Append Download Clients Diagnostics and RPC logs if exporting all logs
    if real_show_id is None:
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
                    if diag and isinstance(diag, dict):
                        lines.append(f"  Version: {diag.get('version') or diag.get('webapi_version') or 'N/A'}")
                        lines.append(f"  Download Speed: {diag.get('download_speed_b_s', 0)} B/s, Upload Speed: {diag.get('upload_speed_b_s', 0)} B/s")
                        if diag.get('free_space_bytes') is not None:
                            lines.append(f"  Free Space: {diag.get('free_space_bytes')} bytes")
                        torrents = diag.get("torrents", [])
                        if isinstance(torrents, list):
                            lines.append(f"  Torrents Count: {len(torrents)}")
                            if torrents:
                                lines.append("  Torrents in Client:")
                                for t in torrents[:30]:
                                    pct = round((t.get('progress') or 0) * 100)
                                    lines.append(f"    - [{t.get('state', 'unknown')}] {t.get('name', t.get('id', '—'))} ({pct}%, size: {t.get('size')} bytes)")

                    logs = await client_inst.get_client_logs(limit=50)
                    if logs and isinstance(logs, list):
                        lines.append("\n  === Recent Daemon Logs ===")
                        for entry in logs:
                            if isinstance(entry, dict):
                                t_str = entry.get("timestamp") or entry.get("time") or ""
                                msg = entry.get("message") or ""
                                lvl = entry.get("level") or entry.get("type") or ""
                                lines.append(f"    [{t_str}] [lvl:{lvl}] {msg}")
                except Exception as exc:
                    lines.append(f"  Client Error: {exc}")
                lines.append("-" * 40)
        except Exception as exc:
            lines.append(f"Error gathering client diagnostics: {exc}")

    import re
    safe_name = ""
    if show_obj and isinstance(getattr(show_obj, "title", None), str):
        safe_name = "_" + re.sub(r"[^\w\-_.]", "_", show_obj.title)[:40]

    filename = f"aliasarr_release_logs{safe_name}_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
