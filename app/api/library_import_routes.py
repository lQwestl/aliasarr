"""Массовый импорт тайтлов из существующих папок («Library Import» в Sonarr/Radarr).

Сценарий: свежая установка или переезд с другого решения. Пользователь указывает
корневую папку, Aliasarr показывает список подпапок, подбирает каждой тайтл из
источников метаданных и после подтверждения создаёт карточки, не трогая файлы на
диске, — затем синхронизирует их с уже лежащими рядом сериями.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import Show, User
from app.services.library_import import (
    ParsedFolder,
    folder_has_media,
    is_ignored_folder,
    parse_folder_name,
    rank_candidates,
)
from app.services.settings_service import get_or_create_settings
from app.services.user_service import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/library-import", tags=["library-import"])

# Оценка, ниже которой совпадение считается сомнительным и не подставляется
# автоматически: пользователь должен выбрать тайтл сам.
AUTO_SELECT_THRESHOLD = 0.62

# Сколько раз повторить короткую запись, если SQLite занят другим писателем.
COMMIT_RETRIES = 5
COMMIT_RETRY_DELAY = 0.4


def _is_locked_error(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower() or "database is busy" in str(exc).lower()


def _commit_with_retry(db: Session, what: str) -> None:
    """Фиксирует короткую транзакцию, переживая занятость SQLite.

    busy_timeout здесь не спасает: если сессия уже держала читающую транзакцию,
    SQLite отказывает в повышении до записи сразу, не дожидаясь таймаута. Помогает
    только откатить свой снимок и попробовать заново.
    """
    for attempt in range(1, COMMIT_RETRIES + 1):
        try:
            db.commit()
            return
        except OperationalError as exc:
            db.rollback()
            if not _is_locked_error(exc) or attempt == COMMIT_RETRIES:
                raise
            logger.warning(
                "База занята при операции «%s», попытка %s из %s", what, attempt, COMMIT_RETRIES
            )
            time.sleep(COMMIT_RETRY_DELAY * attempt)


def _release_read_lock(db: Session) -> None:
    """Закрывает открытую читающую транзакцию сессии.

    Любой SELECT через SQLAlchemy открывает транзакцию и держит её до commit или
    rollback. Если после этого уйти в сеть на десятки секунд, а затем попытаться
    записать, SQLite ответит «database is locked» — снимок к тому моменту устарел.
    """
    try:
        db.rollback()
    except Exception:  # pragma: no cover - сессия и так пуста
        pass


class ImportFolderOut(BaseModel):
    name: str
    path: str
    parsed_title: str
    parsed_year: Optional[int] = None
    has_media: bool = False
    already_added: bool = False
    existing_show_id: Optional[int] = None
    existing_show_title: Optional[str] = None


class ScanFoldersOut(BaseModel):
    path: str
    content_type: str
    folders: list[ImportFolderOut]
    skipped_existing: int = 0


class LookupCandidateOut(BaseModel):
    external_id: str
    title: str
    year: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    rating: Optional[float] = None
    country: Optional[str] = None
    genre: Optional[str] = None
    content_type: Optional[str] = None
    original_title: Optional[str] = None
    titles_by_lang: dict[str, str] = {}
    already_added: bool = False
    existing_show_id: Optional[int] = None
    match_score: float = 0.0
    # Кандидат другой категории, чем сканируемая папка (сериал против фильма).
    type_mismatch: bool = False


class LookupOut(BaseModel):
    folder: str
    parsed_title: str
    parsed_year: Optional[int] = None
    query: str
    candidates: list[LookupCandidateOut]
    auto_selected_id: Optional[str] = None
    # Уверенное совпадение, которое уже заведено в медиатеке под другим путём:
    # вторая папка того же тайтла — обычное дело при переезде с другого решения.
    existing_match_id: Optional[str] = None
    existing_show_id: Optional[int] = None
    existing_title: Optional[str] = None


class ImportItemIn(BaseModel):
    path: str
    external_id: str
    content_type: Optional[str] = None
    title: Optional[str] = None
    source_id: Optional[int] = None
    quality_profile_id: Optional[int] = None
    monitored: bool = True
    sync_disk: bool = True


class ImportItemOut(BaseModel):
    path: str
    success: bool
    show_id: Optional[int] = None
    title: Optional[str] = None
    episodes_imported: int = 0
    files_synced: int = 0
    error: Optional[str] = None
    # Карточка создана, но доводка (путь, профиль, мониторинг) не довершилась.
    # Отличать этот случай от «ничего не произошло» обязательно: папка уже занята
    # тайтлом и повторное сканирование её не предложит.
    partial: bool = False


def _is_type_mismatch(requested: Optional[str], candidate: Optional[str]) -> bool:
    """Противоречит ли категория кандидата той, с которой сканировали папку.

    Аниме и сериал взаимозаменяемы: источники расходятся в том, чем считать тайтл.
    А вот фильм и сериал — разные вещи, и подставлять одно вместо другого нельзя.
    """
    if not requested or not candidate:
        return False
    wanted_movie = requested == "movie"
    candidate_movie = candidate == "movie"
    return wanted_movie != candidate_movie


def _normalize_root(raw: str) -> str:
    """Канонизирует путь корневой папки так же, как обзор файловой системы."""
    target = os.path.normpath("/" + (raw or "").strip())
    while target.startswith("//"):
        target = target[1:]
    return target or "/"


def _normalize_for_compare(path: str) -> str:
    return os.path.normpath(path or "").rstrip("/").lower()


def _existing_paths(db: Session) -> dict[str, Show]:
    """Карта «нормализованный путь → тайтл» для всех уже добавленных карточек."""
    mapping: dict[str, Show] = {}
    for show in db.query(Show).filter(Show.path.isnot(None)).all():
        if show.path:
            mapping[_normalize_for_compare(show.path)] = show
    return mapping


@router.get("/default-roots")
def get_default_roots(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Корневые папки из настроек — чтобы окно импорта открывалось уже заполненным."""
    settings = get_or_create_settings(db)
    return {
        "movie": getattr(settings, "root_folder_movies", "") or "",
        "series": getattr(settings, "root_folder_series", "") or "",
        "anime": getattr(settings, "root_folder_anime", "") or "",
        "legacy": getattr(settings, "root_folder", "") or "",
    }


@router.get("/scan", response_model=ScanFoldersOut)
def scan_root_folder(
    path: str,
    content_type: str = "series",
    include_added: bool = False,
    require_media: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Перечисляет подпапки корневой директории как кандидатов на импорт."""
    root = _normalize_root(path)
    if not os.path.isdir(root):
        raise HTTPException(404, f"Папка не найдена: {root}")

    try:
        entries = sorted(os.listdir(root), key=lambda s: s.lower())
    except PermissionError:
        raise HTTPException(403, f"Нет доступа к папке: {root}")

    known = _existing_paths(db)
    folders: list[ImportFolderOut] = []
    skipped = 0

    for name in entries:
        if is_ignored_folder(name):
            continue
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue

        existing = known.get(_normalize_for_compare(full))
        if existing and not include_added:
            skipped += 1
            continue

        has_media = folder_has_media(full)
        if require_media and not has_media:
            continue

        parsed = parse_folder_name(name)
        folders.append(
            ImportFolderOut(
                name=name,
                path=full,
                parsed_title=parsed.title,
                parsed_year=parsed.year,
                has_media=has_media,
                already_added=existing is not None,
                existing_show_id=existing.id if existing else None,
                existing_show_title=existing.title if existing else None,
            )
        )

    return ScanFoldersOut(path=root, content_type=content_type, folders=folders, skipped_existing=skipped)


async def _search_metadata(query: str, db: Session, current_user: User) -> list:
    """Обёртка над сводным поиском по всем источникам метаданных."""
    from app.api.metadata_routes import search_all_metadata_sources

    try:
        return await search_all_metadata_sources(query=query, db=db, current_user=current_user)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - сетевые сбои источников
        logger.warning("Поиск метаданных для «%s» не удался: %s", query, exc)
        return []


@router.get("/lookup", response_model=LookupOut)
async def lookup_folder(
    folder: str,
    content_type: str = "series",
    query: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Подбирает тайтлы под имя папки и возвращает их по убыванию совпадения.

    `query` позволяет переопределить строку поиска — так работает ручной ввод и
    автодополнение в строке подбора напротив папки.
    """
    parsed = parse_folder_name(folder)
    manual = (query or "").strip()
    if manual:
        parsed = ParsedFolder(
            name=parsed.name,
            title=manual,
            year=parsed.year,
            alternative_titles=[],
        )

    terms = parsed.search_terms
    if not terms:
        return LookupOut(folder=folder, parsed_title=parsed.title, parsed_year=parsed.year, query="", candidates=[])

    results = await _search_metadata(terms[0], db, current_user)

    # Если первый вариант названия ничего внятного не дал, пробуем альтернативный
    # («Дюна» → «Dune»): на русских раздачах это типичная ситуация.
    ranked = rank_candidates(parsed, results, content_type)
    best_score = ranked[0][1] if ranked else 0.0
    if best_score < AUTO_SELECT_THRESHOLD and len(terms) > 1:
        seen = {str(getattr(r, "external_id", "")) for r in results}
        for extra_term in terms[1:]:
            for extra in await _search_metadata(extra_term, db, current_user):
                if str(getattr(extra, "external_id", "")) not in seen:
                    seen.add(str(getattr(extra, "external_id", "")))
                    results.append(extra)
        ranked = rank_candidates(parsed, results, content_type)

    candidates = [
        LookupCandidateOut(
            external_id=str(item.external_id),
            title=item.title,
            year=item.year,
            overview=item.overview,
            poster_url=item.poster_url,
            rating=item.rating,
            country=item.country,
            genre=item.genre,
            content_type=item.content_type,
            original_title=getattr(item, "original_title", None),
            titles_by_lang=getattr(item, "titles_by_lang", {}) or {},
            already_added=bool(getattr(item, "already_added", False)),
            existing_show_id=getattr(item, "existing_show_id", None),
            match_score=round(score, 3),
            type_mismatch=_is_type_mismatch(content_type, item.content_type),
        )
        for item, score in ranked[: max(1, min(limit, 50))]
    ]

    auto_selected = None
    existing: Optional[LookupCandidateOut] = None
    for cand in candidates:
        if cand.match_score < AUTO_SELECT_THRESHOLD:
            continue
        if cand.type_mismatch:
            # Категория — жёсткое условие, а не просто штраф к оценке. Одноимённый
            # сериал легко перебивает порог за счёт совпадения названия и года
            # (0.8 + 0.2 − 0.25 = 0.75), и при недоступном источнике фильмов папка
            # молча уезжала в медиатеку сериалом. Такой вариант остаётся в списке,
            # но выбрать его может только человек.
            continue
        if cand.already_added:
            # Запоминаем, но перебор продолжаем: рядом может оказаться столь же
            # уверенный кандидат, которого в медиатеке ещё нет.
            if existing is None:
                existing = cand
            continue
        auto_selected = cand.external_id
        break

    return LookupOut(
        folder=folder,
        parsed_title=parsed.title,
        parsed_year=parsed.year,
        query=terms[0],
        candidates=candidates,
        auto_selected_id=auto_selected,
        existing_match_id=existing.external_id if existing else None,
        existing_show_id=existing.existing_show_id if existing else None,
        existing_title=existing.title if existing else None,
    )


@router.post("/item", response_model=ImportItemOut)
async def import_folder_item(
    payload: ImportItemIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Импортирует одну папку: создаёт карточку по её пути и подтягивает файлы.

    Импорт делается по одной папке, чтобы интерфейс показывал прогресс построчно
    и длинная очередь не упиралась в таймаут одного запроса.
    """
    from app.api.metadata_routes import ImportShowRequest, import_show
    from app.api.shows import sync_show_disk

    folder = _normalize_root(payload.path)
    if not os.path.isdir(folder):
        return ImportItemOut(path=payload.path, success=False, error=f"Папка не найдена: {folder}")

    existing = _existing_paths(db).get(_normalize_for_compare(folder))
    if existing:
        return ImportItemOut(
            path=folder,
            success=False,
            show_id=existing.id,
            title=existing.title,
            error=f"Папка уже привязана к тайтлу «{existing.title}»",
        )

    # Проверка выше открыла читающую транзакцию, а дальше — поход в источник
    # метаданных на десятки секунд. Держать снимок всё это время нельзя.
    _release_read_lock(db)

    try:
        result = await import_show(
            payload=ImportShowRequest(
                source_id=payload.source_id,
                external_id=payload.external_id,
                path=folder,
                content_type=payload.content_type,
                title=payload.title,
            ),
            db=db,
            current_user=current_user,
        )
    except HTTPException as exc:
        return ImportItemOut(path=folder, success=False, error=str(exc.detail))
    except Exception as exc:  # pragma: no cover - защита от сбоя источника
        logger.error("Импорт папки «%s» не удался: %s", folder, exc, exc_info=True)
        return ImportItemOut(path=folder, success=False, error=str(exc))

    show_id = result.get("show_id")
    show = db.get(Show, show_id) if show_id else None
    if not show:
        return ImportItemOut(path=folder, success=False, error="Тайтл не создан")

    # С этого места карточка уже существует и занимает папку. Любой сбой ниже —
    # это «импортировано частично», а не «не импортировано»: иначе пользователь
    # считает папку потерянной, хотя повторно её предложить уже нельзя.
    episodes_imported = int(result.get("episodes_imported") or 0)
    show_title = show.title

    # Путь мог быть достроен подпапкой — при импорте из существующей папки
    # карточка обязана указывать ровно на неё.
    if _normalize_for_compare(show.path or "") != _normalize_for_compare(folder):
        show.path = folder
    show.monitored = payload.monitored
    if payload.quality_profile_id is not None:
        show.quality_profile_id = payload.quality_profile_id
    db.add(show)
    try:
        _commit_with_retry(db, f"доводка карточки «{show_title}»")
    except OperationalError as exc:
        logger.error("Не удалось дописать карточку «%s» после импорта: %s", show_title, exc)
        return ImportItemOut(
            path=folder,
            success=False,
            partial=True,
            show_id=show_id,
            title=show_title,
            episodes_imported=episodes_imported,
            error=(
                "Карточка создана, но профиль, мониторинг и путь не сохранились: "
                "база была занята. Проверьте тайтл в медиатеке и при необходимости "
                "поправьте его вручную."
            ),
        )
    db.refresh(show)

    files_synced = 0
    if payload.sync_disk:
        try:
            # sync_show_disk синхронная и долгая: обходит папку, читает MediaInfo
            # и пишет в базу. На цикле событий она блокирует весь сервер, поэтому
            # уводим её в поток.
            sync_result = await asyncio.to_thread(
                sync_show_disk, show_id=show.id, db=db, current_user=current_user
            )
            files_synced = int((sync_result or {}).get("imported_count") or 0)
        except HTTPException as exc:
            logger.info("Синхронизация с диском для «%s» пропущена: %s", show_title, exc.detail)
        except OperationalError as exc:
            _release_read_lock(db)
            logger.warning("Синхронизация с диском для «%s» не удалась: %s", show_title, exc)
            return ImportItemOut(
                path=folder,
                success=True,
                partial=True,
                show_id=show_id,
                title=show_title,
                episodes_imported=episodes_imported,
                error=(
                    "Тайтл добавлен, но файлы на диске не привязаны: база была занята. "
                    "Запустите синхронизацию с диском в карточке тайтла."
                ),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Синхронизация с диском для «%s» не удалась: %s", show_title, exc)

    return ImportItemOut(
        path=folder,
        success=True,
        show_id=show.id,
        title=show.title,
        episodes_imported=episodes_imported,
        files_synced=files_synced,
    )
