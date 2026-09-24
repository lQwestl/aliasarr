"""Preflight checks and crash-safe filesystem primitives for media operations."""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.services.path_security import UnsafeMediaPathError, require_descendant


class OperationMode(str, Enum):
    COPY = "copy"
    MOVE = "move"
    HARDLINK = "hardlink"
    REPLACE = "replace"
    DELETE = "delete"
    RENAME = "rename"
    DOWNLOAD = "download"
    MERGE = "merge"


class ConflictPolicy(str, Enum):
    ERROR = "error"
    REPLACE = "replace"
    SKIP = "skip"


@dataclass(frozen=True)
class FileIntent:
    source: str | os.PathLike[str] | None
    destination: str | os.PathLike[str] | None
    mode: OperationMode | str
    size_bytes: int | None = None
    conflict_policy: ConflictPolicy | str = ConflictPolicy.ERROR


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str
    severity: str = "error"
    path: str | None = None


@dataclass(frozen=True)
class PreflightDecision:
    intent: FileIntent
    source: Path | None
    destination: Path | None
    requested_mode: OperationMode
    effective_mode: OperationMode
    size_bytes: int
    device: int | None


class FilePreflightError(RuntimeError):
    def __init__(self, report: PreflightReport):
        self.report = report
        messages = "; ".join(issue.message for issue in report.errors)
        super().__init__(messages or "Файловая операция не прошла предварительную проверку")


@dataclass
class PreflightReport:
    decisions: list[PreflightDecision] = field(default_factory=list)
    issues: list[PreflightIssue] = field(default_factory=list)
    required_bytes_by_device: dict[int, int] = field(default_factory=dict)
    free_bytes_by_device: dict[int, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def conflicts(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.code in {"destination_exists", "duplicate_destination"}]

    def raise_for_errors(self) -> PreflightReport:
        if not self.ok:
            raise FilePreflightError(self)
        return self


@dataclass(frozen=True)
class QuarantineRecord:
    original_path: Path
    quarantined_path: Path
    operation: str
    size_bytes: int


def _mode(value: OperationMode | str) -> OperationMode:
    return value if isinstance(value, OperationMode) else OperationMode(str(value).lower())


def _policy(value: ConflictPolicy | str) -> ConflictPolicy:
    return value if isinstance(value, ConflictPolicy) else ConflictPolicy(str(value).lower())


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path if path.exists() and path.is_dir() else path.parent
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise FileNotFoundError(f"Не найден существующий родитель для {path}")
        candidate = parent
    if not candidate.is_dir():
        raise NotADirectoryError(str(candidate))
    return candidate


def _issue(report: PreflightReport, code: str, message: str, path: Path | None = None, severity: str = "error") -> None:
    report.issues.append(PreflightIssue(code, message, severity, str(path) if path else None))


def _probe_writable(directory: Path) -> None:
    fd, probe = tempfile.mkstemp(prefix=".aliasarr-write-probe-", dir=directory)
    try:
        os.close(fd)
    finally:
        try:
            os.unlink(probe)
        except FileNotFoundError:
            pass


def preflight_file_operation(
    intents: Iterable[FileIntent],
    *,
    source_roots: Iterable[str | os.PathLike[str]] = (),
    destination_roots: Iterable[str | os.PathLike[str]] = (),
    reserve_bytes: int = 0,
    reserve_fraction: float = 0.0,
    allow_hardlink_fallback: bool = True,
    probe_write: bool = False,
) -> PreflightReport:
    """Validate a batch and calculate the real space required on each device."""
    report = PreflightReport()
    src_roots = tuple(source_roots)
    dst_roots = tuple(destination_roots)
    seen_destinations: set[Path] = set()
    device_parents: dict[int, Path] = {}

    for intent in intents:
        try:
            requested = _mode(intent.mode)
        except ValueError:
            _issue(report, "invalid_mode", f"Неизвестный режим файловой операции: {intent.mode}")
            continue

        source = Path(intent.source).expanduser().resolve(strict=False) if intent.source else None
        destination = Path(intent.destination).expanduser().resolve(strict=False) if intent.destination else None
        source_stat = None

        needs_source = requested not in {OperationMode.DOWNLOAD}
        needs_destination = requested not in {OperationMode.DELETE}
        if needs_source and source is None:
            _issue(report, "source_missing", "Не указан исходный путь")
            continue
        if needs_destination and destination is None:
            _issue(report, "destination_missing", "Не указан целевой путь")
            continue

        if source is not None:
            if not source.exists():
                _issue(report, "source_not_found", f"Исходный путь не найден: {source}", source)
            else:
                try:
                    source_stat = source.stat()
                except OSError as exc:
                    _issue(report, "source_stat_failed", f"Не удалось проверить {source}: {exc}", source)
                if requested != OperationMode.DELETE and not source.is_file():
                    _issue(report, "source_not_file", f"Источник не является обычным файлом: {source}", source)
                if not os.access(source, os.R_OK):
                    _issue(report, "source_not_readable", f"Нет доступа на чтение: {source}", source)
            if src_roots:
                try:
                    require_descendant(source, src_roots)
                except UnsafeMediaPathError as exc:
                    _issue(report, "source_outside_roots", str(exc), source)

        parent = None
        device = None
        if destination is not None:
            if dst_roots:
                try:
                    require_descendant(destination, dst_roots, allow_root=requested == OperationMode.DOWNLOAD)
                except UnsafeMediaPathError as exc:
                    _issue(report, "destination_outside_roots", str(exc), destination)
            if source is not None and source == destination:
                _issue(report, "same_path", f"Источник и цель совпадают: {source}", destination)
            if destination in seen_destinations:
                _issue(report, "duplicate_destination", f"Несколько операций используют одну цель: {destination}", destination)
            seen_destinations.add(destination)

            try:
                parent = _nearest_existing_parent(destination)
                parent_stat = parent.stat()
                device = parent_stat.st_dev
                device_parents.setdefault(device, parent)
                if not os.access(parent, os.W_OK | os.X_OK):
                    _issue(report, "destination_not_writable", f"Нет доступа на запись в {parent}", parent)
                elif probe_write:
                    try:
                        _probe_writable(parent)
                    except OSError as exc:
                        _issue(report, "destination_probe_failed", f"Проверка записи в {parent} не пройдена: {exc}", parent)
            except OSError as exc:
                _issue(report, "destination_parent_invalid", f"Целевая папка недоступна: {exc}", destination)

            if destination.exists():
                policy = _policy(intent.conflict_policy)
                if policy == ConflictPolicy.ERROR:
                    _issue(report, "destination_exists", f"Целевой путь уже существует: {destination}", destination)
                elif policy == ConflictPolicy.SKIP:
                    _issue(report, "destination_exists", f"Целевой путь будет пропущен: {destination}", destination, "warning")

        size = max(0, int(intent.size_bytes if intent.size_bytes is not None else (source_stat.st_size if source_stat else 0)))
        effective = requested
        required = 0
        if requested == OperationMode.HARDLINK and source_stat is not None and device is not None:
            if source_stat.st_dev != device:
                if allow_hardlink_fallback:
                    effective = OperationMode.COPY
                    required = size
                    _issue(report, "hardlink_fallback", f"Hardlink между разными файловыми системами невозможен; будет копирование: {source} -> {destination}", destination, "warning")
                else:
                    _issue(report, "hardlink_cross_device", f"Hardlink между разными файловыми системами невозможен: {source} -> {destination}", destination)
        elif requested in {
            OperationMode.COPY,
            OperationMode.REPLACE,
            OperationMode.DOWNLOAD,
            OperationMode.MERGE,
        } or (
            requested in {OperationMode.MOVE, OperationMode.RENAME}
            and source_stat is not None
            and device is not None
            and source_stat.st_dev != device
        ):
            required = size

        if device is not None and required:
            report.required_bytes_by_device[device] = report.required_bytes_by_device.get(device, 0) + required
        report.decisions.append(PreflightDecision(intent, source, destination, requested, effective, size, device))

    for device, required in report.required_bytes_by_device.items():
        parent = device_parents[device]
        try:
            usage = shutil.disk_usage(parent)
        except OSError as exc:
            _issue(report, "disk_usage_failed", f"Не удалось проверить свободное место для {parent}: {exc}", parent)
            continue
        report.free_bytes_by_device[device] = usage.free
        reserve = max(max(0, reserve_bytes), int(max(0.0, reserve_fraction) * usage.total))
        if required + reserve > usage.free:
            _issue(
                report,
                "insufficient_space",
                f"Недостаточно места на {parent}: нужно {required} байт и резерв {reserve} байт, свободно {usage.free} байт",
                parent,
            )

    return report


def _fsync_directory(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def quarantine_path(
    path: str | os.PathLike[str],
    quarantine_root: str | os.PathLike[str],
    *,
    operation: str = "delete",
) -> QuarantineRecord:
    """Atomically move a file or directory to a same-filesystem quarantine."""
    source = Path(path).expanduser().resolve(strict=True)
    q_root = Path(quarantine_root).expanduser().resolve(strict=False)
    try:
        q_root.relative_to(source)
    except ValueError:
        pass
    else:
        raise UnsafeMediaPathError("Карантин нельзя размещать внутри удаляемого пути")

    q_root.mkdir(parents=True, exist_ok=True)
    if source.stat().st_dev != q_root.stat().st_dev:
        raise OSError(errno.EXDEV, "Карантин должен находиться на той же файловой системе", str(source))

    bucket = q_root / uuid.uuid4().hex
    bucket.mkdir(mode=0o700)
    quarantined = bucket / source.name
    size = _path_size(source)
    try:
        os.replace(source, quarantined)
        _fsync_directory(source.parent)
        _fsync_directory(bucket)
    except Exception:
        try:
            bucket.rmdir()
        except OSError:
            pass
        raise
    return QuarantineRecord(source, quarantined, operation, size)


def restore_quarantined(record: QuarantineRecord, *, overwrite: bool = False) -> Path:
    """Restore an item previously returned by :func:`quarantine_path`."""
    source = record.quarantined_path
    destination = record.original_path
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)

    backup = None
    if destination.exists():
        backup = destination.parent / f".aliasarr-restore-backup-{uuid.uuid4().hex}"
        os.replace(destination, backup)
    try:
        os.replace(source, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if backup is not None and backup.exists():
            os.replace(backup, destination)
        raise
    if backup is not None and backup.exists():
        if backup.is_dir():
            shutil.rmtree(backup)
        else:
            backup.unlink()
    try:
        source.parent.rmdir()
    except OSError:
        pass
    return destination


def atomic_transfer(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    mode: OperationMode | str = OperationMode.COPY,
    replace: bool = True,
    callback: Callable[[int, int], None] | None = None,
    chunk_size: int = 4 * 1024 * 1024,
    quarantine_root: str | os.PathLike[str] | None = None,
) -> str:
    """Publish a copied, moved or hardlinked file without exposing partial data.

    An existing destination is retained until the replacement is ready. On any
    publish failure it is restored. For cross-device moves the source is removed
    only after the destination has been completely published.
    """
    src = Path(source).expanduser().resolve(strict=True)
    dst = Path(destination).expanduser().resolve(strict=False)
    requested = _mode(mode)
    if requested not in {OperationMode.COPY, OperationMode.MOVE, OperationMode.RENAME, OperationMode.HARDLINK, OperationMode.REPLACE}:
        raise ValueError(f"Режим {requested.value} не поддерживается atomic_transfer")
    if not src.is_file():
        raise ValueError(f"Источник не является файлом: {src}")
    if src == dst:
        return "none"

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not replace:
        raise FileExistsError(dst)

    src_stat = src.stat()
    same_device = src_stat.st_dev == dst.parent.stat().st_dev
    effective = requested
    if requested == OperationMode.HARDLINK and not same_device:
        effective = OperationMode.COPY
    if requested in {OperationMode.MOVE, OperationMode.RENAME} and not same_device:
        effective = OperationMode.COPY

    temp = dst.parent / f".{dst.name}.aliasarr-part-{uuid.uuid4().hex}"
    backup = None
    quarantined = None
    source_was_moved = False
    total = src_stat.st_size

    def copy_source_to_temp() -> None:
        copied = 0
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with open(src, "rb") as input_file, os.fdopen(fd, "wb") as output_file:
                while True:
                    chunk = input_file.read(chunk_size)
                    if not chunk:
                        break
                    output_file.write(chunk)
                    copied += len(chunk)
                    if callback:
                        callback(copied, total)
                output_file.flush()
                os.fsync(output_file.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        if temp.stat().st_size != total:
            raise OSError(errno.EIO, "Размер временной копии не совпадает с источником")
        try:
            shutil.copystat(src, temp)
        except OSError:
            pass

    try:
        if callback:
            callback(0, total)
        if effective == OperationMode.HARDLINK:
            os.link(src, temp)
        elif effective in {OperationMode.COPY, OperationMode.REPLACE}:
            copy_source_to_temp()
        else:  # same-filesystem move/rename
            try:
                os.replace(src, temp)
                source_was_moved = True
            except OSError as exc:
                # Separate bind mounts can report the same st_dev but still reject
                # a rename across mount boundaries. Keep the source intact until
                # the copied destination has been published successfully.
                if exc.errno != errno.EXDEV:
                    raise
                effective = OperationMode.COPY
                copy_source_to_temp()

        if dst.exists():
            if quarantine_root is not None:
                quarantined = quarantine_path(dst, quarantine_root, operation="replace")
            else:
                backup = dst.parent / f".{dst.name}.aliasarr-backup-{uuid.uuid4().hex}"
                os.replace(dst, backup)

        try:
            os.replace(temp, dst)
            _fsync_directory(dst.parent)
        except Exception:
            if source_was_moved and temp.exists():
                os.replace(temp, src)
                source_was_moved = False
            if quarantined is not None:
                restore_quarantined(quarantined)
            elif backup is not None and backup.exists():
                os.replace(backup, dst)
            raise

        if requested in {OperationMode.MOVE, OperationMode.RENAME} and not source_was_moved:
            src.unlink()
            _fsync_directory(src.parent)
        if backup is not None and backup.exists():
            backup.unlink()
        if callback:
            callback(total, total)
        if requested in {OperationMode.MOVE, OperationMode.RENAME}:
            return requested.value
        return "copy" if effective in {OperationMode.COPY, OperationMode.REPLACE} else effective.value
    except Exception:
        if temp.exists():
            try:
                if source_was_moved and not src.exists():
                    os.replace(temp, src)
                else:
                    temp.unlink()
            except OSError:
                pass
        if backup is not None and backup.exists() and not dst.exists():
            try:
                os.replace(backup, dst)
            except OSError:
                pass
        raise
