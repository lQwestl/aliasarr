from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import ReleaseLog, User
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


@router.delete("")
def clear_release_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_release_logs")),
):
    """Очистить журнал релизов."""
    count = db.query(ReleaseLog).delete()
    db.commit()
    return {"success": True, "deleted": count, "message": f"Очищено записей: {count}"}


@router.get("/download-client-logs")
async def get_download_client_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("view_release_logs", "manage_release_logs")),
):
    """Получить диагностику и недавний журнал сообщений от активных клиентов загрузки (Transmission, qBittorrent)."""
    from app.models.db import DownloadClient
    from app.services.download_client import get_client

    active_clients = db.query(DownloadClient).filter(DownloadClient.enabled == True).all()
    results = []
    for dc in active_clients:
        client_info = {
            "id": dc.id,
            "name": dc.name,
            "type": dc.type,
            "host": f"{dc.host}:{dc.port}",
            "diagnostics": {},
            "logs": [],
        }
        try:
            client = get_client(dc)
            client_info["diagnostics"] = await client.get_client_diagnostics()
            client_info["logs"] = await client.get_client_logs(limit=100)
        except Exception as e:
            client_info["error"] = str(e)
        results.append(client_info)
    return results


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

    # Добавляем диагностику и логи всех активных клиентов загрузки (Transmission, qBittorrent)
    from app.models.db import DownloadClient
    from app.services.download_client import get_client

    active_dc_rows = db.query(DownloadClient).filter(DownloadClient.enabled == True).all()
    if active_dc_rows:
        lines.append("\n" + "=" * 60)
        lines.append("=== DOWNLOAD CLIENTS DIAGNOSTICS & STATUS ===")
        lines.append("=" * 60)
        for dc in active_dc_rows:
            lines.append(f"\n[DOWNLOAD CLIENT: {dc.name} ({dc.type.upper()}) | {dc.host}:{dc.port}]")
            try:
                client = get_client(dc)
                diag = await client.get_client_diagnostics()
                if diag:
                    lines.append(f"  Connected: {diag.get('connected', False)}")
                    lines.append(f"  Version: {diag.get('version', 'unknown')}")
                    if "download_dir" in diag:
                        lines.append(f"  Download Dir: {diag.get('download_dir')}")
                    if "download_speed" in diag or "upload_speed" in diag:
                        lines.append(f"  Speeds: DL {diag.get('download_speed', 0)} B/s, UL {diag.get('upload_speed', 0)} B/s")
                    torrents = diag.get("torrents", [])
                    lines.append(f"  Total Torrents in client: {len(torrents)}")
                    if torrents:
                        lines.append("  Torrents Snapshot:")
                        for t in torrents:
                            lines.append(
                                f"    * [{t.get('state', '').upper()}] {t.get('name')} (hash: {t.get('hash')}): "
                                f"Progress: {t.get('progress')}%, Left: {t.get('left_until_done')} bytes, Size: {t.get('size')} bytes"
                            )

                c_logs = await client.get_client_logs(limit=100)
                if c_logs:
                    lines.append(f"\n  --- Recent Daemon Logs ({len(c_logs)} entries) ---")
                    for cl in c_logs:
                        lines.append(f"  [{cl.get('timestamp')}] [{cl.get('level', '').upper()}] [{cl.get('category', '')}] {cl.get('message')}")
            except Exception as dc_err:
                lines.append(f"  Failed to retrieve diagnostics from client '{dc.name}': {dc_err}")

    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=aliasarr_release_logs.txt"}
    )
