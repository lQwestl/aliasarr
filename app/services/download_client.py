"""Унифицированный интерфейс загрузчиков (qBittorrent, Transmission, Deluge, rTorrent, Aria2, Blackhole, SABnzbd, NZBGet).

Единый набор методов, используемых приложением:
- add_torrent(url_or_magnet, category, save_path) -> torrent_hash
- list_torrents() -> list[TorrentInfo]
- get_torrent(hash) -> TorrentInfo | None
- set_file_priorities(hash, file_indices, priority) -> selective download
- remove_torrent(hash, delete_files)
- resume_torrent(hash)

Реализации создаются через фабрику get_client(download_client_row).
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger("aliasarr.download_client")


@dataclass
class TorrentFile:
    index: int
    name: str
    size: int
    progress: float  # 0..1
    priority: int  # 0 = не скачивать, 1+ = скачивать


@dataclass
class TorrentInfo:
    hash: str
    name: str
    progress: float  # 0..1
    state: str  # downloading|seeding|paused|error|completed
    save_path: str
    size: int
    content_path: str = ""
    download_speed: int = 0  # bytes/s
    upload_speed: int = 0    # bytes/s
    eta: Optional[int] = None # seconds
    seeding_time: int = 0    # seconds
    ratio: float = 0.0
    protocol: str = "torrent"
    files: list[TorrentFile] = field(default_factory=list)
    left_until_done: Optional[int] = None


class BaseDownloadClient:
    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        raise NotImplementedError

    async def list_torrents(self) -> list[TorrentInfo]:
        raise NotImplementedError

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        raise NotImplementedError

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        raise NotImplementedError

    async def set_files_wanted_unwanted(self, torrent_hash: str, wanted_indices: list[int], unwanted_indices: list[int]) -> None:
        if unwanted_indices:
            await self.set_file_priorities(torrent_hash, unwanted_indices, 0)
        if wanted_indices:
            await self.set_file_priorities(torrent_hash, wanted_indices, 1)

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        raise NotImplementedError

    async def pause_torrent(self, torrent_hash: str) -> None:
        raise NotImplementedError

    async def resume_torrent(self, torrent_hash: str) -> None:
        raise NotImplementedError

    async def recheck_torrent(self, torrent_hash: str) -> None:
        """Принудительно запускает перепроверку целостности и наличия файлов торрента (hash check / verify)."""
        pass

    async def get_client_logs(self, limit: int = 100) -> list[dict]:
        """Возвращает список недавних записей журнала демона/приложения загрузчика."""
        return []

    async def get_client_diagnostics(self) -> dict:
        """Возвращает диагностические данные загрузчика (версия, сессия, активные торренты)."""
        return {}


def _normalize_client_url(host: str, port: int, default_port: int = 8080) -> str:
    host_str = (host or "localhost").strip()
    if not host_str.startswith(("http://", "https://")):
        host_str = f"http://{host_str}"
    parsed = urllib.parse.urlparse(host_str)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    if ":" in netloc:
        return f"{scheme}://{netloc}"
    actual_port = port or default_port
    return f"{scheme}://{netloc}:{actual_port}"


def extract_info_hash_from_url_or_magnet(url_or_magnet: str) -> str:
    if not url_or_magnet:
        return ""
    m = re.search(r"xt=urn:btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})", url_or_magnet, re.IGNORECASE)
    if m:
        h = m.group(1)
        if len(h) == 32:
            try:
                raw = base64.b32decode(h.upper())
                return raw.hex().lower()
            except Exception:
                pass
        return h.lower()
    return ""


def extract_info_hash_from_torrent_bytes(torrent_bytes: bytes) -> str:
    if not torrent_bytes:
        return ""
    try:
        info_marker = b"4:info"
        idx = torrent_bytes.index(info_marker)
        start_idx = idx + len(info_marker)

        def get_dict_end(pos):
            char = torrent_bytes[pos:pos+1]
            if char == b"i":
                return torrent_bytes.index(b"e", pos + 1) + 1
            elif char.isdigit():
                colon = torrent_bytes.index(b":", pos)
                length = int(torrent_bytes[pos:colon])
                return colon + 1 + length
            elif char in (b"l", b"d"):
                pos += 1
                while torrent_bytes[pos:pos+1] != b"e":
                    pos = get_dict_end(pos)
                return pos + 1
            raise ValueError(f"Invalid char {char}")

        end_idx = get_dict_end(start_idx)
        raw_info = torrent_bytes[start_idx:end_idx]
        return hashlib.sha1(raw_info).hexdigest().lower()
    except Exception:
        return ""


async def _fetch_torrent_content_if_url(url_or_magnet: str) -> tuple[Optional[bytes], str]:
    """
    Если передан HTTP/HTTPS URL, скачивает содержимое торрент-файла или разрешает редирект в magnet-ссылку.
    Возвращает (torrent_bytes, magnet_or_url).
    """
    if not url_or_magnet or not url_or_magnet.startswith(("http://", "https://")):
        return None, url_or_magnet

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Aliasarr/1.0",
        "Accept": "application/x-bittorrent, application/octet-stream, */*",
    }

    current_url = url_or_magnet
    last_err = ""
    for _ in range(5):
        if current_url.startswith("magnet:"):
            return None, current_url

        try:
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=False, verify=False, headers=headers) as client:
                resp = await client.get(current_url)

                # Обработка редиректов (301, 302, 303, 307, 308)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location") or resp.headers.get("location") or ""
                    if location:
                        if location.startswith("magnet:"):
                            return None, location
                        current_url = urllib.parse.urljoin(current_url, location)
                        continue

                if resp.status_code == 200 and resp.content:
                    content = resp.content
                    if content.startswith(b"\x1f\x8b"):
                        try:
                            content = gzip.decompress(content)
                        except Exception:
                            pass

                    text_preview = ""
                    try:
                        text_preview = content[:200].decode("utf-8", errors="ignore").strip()
                    except Exception:
                        pass

                    if text_preview.startswith("magnet:"):
                        return None, text_preview
                    if content.startswith(b"d") or b"4:info" in content:
                        return content, current_url
                    else:
                        last_err = f"Ответ индексатора не является торрент-файлом (длина {len(content)}, начало: {text_preview[:60]})"
                        logger.warning("%s: %s", last_err, current_url)
                else:
                    last_err = f"HTTP {resp.status_code}"
                    logger.warning("Ошибка скачивания торрента по URL %s: %s", current_url, last_err)
                break
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            logger.warning("Ошибка запроса торрента по URL (%s): %s", current_url, exc)
            break

    if last_err:
        raise RuntimeError(f"Не удалось скачать .torrent файл с индексатора ({last_err})")
    return None, url_or_magnet


class QBittorrentClient(BaseDownloadClient):
    """Асинхронный клиент qBittorrent Web API v2 через httpx с поддержкой qbittorrentapi."""

    def __init__(self, host: str, port: int, username: str, password: str):
        self._base_url = _normalize_client_url(host, port, default_port=8080).rstrip("/")
        self._username = username or ""
        self._password = password or ""
        self._cookies: dict[str, str] = {}
        try:
            import qbittorrentapi
            self._sync_client = qbittorrentapi.Client(
                host=self._base_url, username=self._username, password=self._password,
            )
        except ImportError:
            self._sync_client = None

    async def _ensure_auth(self, client: httpx.AsyncClient) -> None:
        if self._cookies.get("SID"):
            return
        if not self._username and not self._password:
            return
        try:
            resp = await client.post(
                f"{self._base_url}/api/v2/auth/login",
                data={"username": self._username, "password": self._password},
                timeout=8.0,
            )
            if resp.status_code == 200:
                for k, v in resp.cookies.items():
                    self._cookies[k] = v
        except Exception as exc:
            logger.debug("qBittorrent login attempt: %s", exc)

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        torrent_bytes, resolved_url = await _fetch_torrent_content_if_url(url_or_magnet)
        expected_hash = extract_info_hash_from_url_or_magnet(resolved_url)
        if torrent_bytes and not expected_hash:
            expected_hash = extract_info_hash_from_torrent_bytes(torrent_bytes)

        try:
            async with httpx.AsyncClient(timeout=15.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                before_resp = await client.get(f"{self._base_url}/api/v2/torrents/info", cookies=self._cookies, timeout=8.0)
                before_hashes = {t.get("hash") for t in (before_resp.json() if before_resp.status_code == 200 else [])}

                add_data = {
                    "category": category or "",
                    "autoTMM": "false",
                }
                if save_path:
                    add_data["savepath"] = save_path

                if torrent_bytes:
                    files = {"torrents": ("release.torrent", torrent_bytes, "application/x-bittorrent")}
                    resp = await client.post(f"{self._base_url}/api/v2/torrents/add", data=add_data, files=files, cookies=self._cookies, timeout=12.0)
                else:
                    add_data["urls"] = resolved_url
                    resp = await client.post(f"{self._base_url}/api/v2/torrents/add", data=add_data, cookies=self._cookies, timeout=12.0)

                if resp.status_code in (401, 403):
                    self._cookies.clear()
                    await self._ensure_auth(client)
                    if torrent_bytes:
                        files = {"torrents": ("release.torrent", torrent_bytes, "application/x-bittorrent")}
                        resp = await client.post(f"{self._base_url}/api/v2/torrents/add", data=add_data, files=files, cookies=self._cookies, timeout=12.0)
                    else:
                        resp = await client.post(f"{self._base_url}/api/v2/torrents/add", data=add_data, cookies=self._cookies, timeout=12.0)

                resp.raise_for_status()

                # Проверяем хэш добавленного торрента
                await asyncio.sleep(0.5)
                after_resp = await client.get(f"{self._base_url}/api/v2/torrents/info", cookies=self._cookies, timeout=8.0)
                if after_resp.status_code == 200:
                    after_torrents = after_resp.json()
                    new = [t for t in after_torrents if t.get("hash") not in before_hashes]
                    if new:
                        return new[0].get("hash", "").lower()
                    if expected_hash:
                        return expected_hash
                    if after_torrents:
                        return after_torrents[-1].get("hash", "").lower()

                if expected_hash:
                    return expected_hash
                return ""
        except Exception as exc:
            logger.warning("Ошибка добавления торрента через httpx в qBittorrent (%s): %s", self._base_url, exc)
            if self._sync_client:
                sync_res = await asyncio.to_thread(self._add_torrent_sync, resolved_url, category, save_path)
                if sync_res:
                    return sync_res
            if expected_hash:
                return expected_hash
            raise RuntimeError(f"Ошибка qBittorrent при добавлении торрента: {exc}")

    def _add_torrent_sync(self, url_or_magnet: str, category: Optional[str], save_path: Optional[str]) -> str:
        try:
            self._sync_client.auth_log_in()
            before = {t.hash for t in self._sync_client.torrents_info()}
            add_kwargs = {"urls": url_or_magnet, "category": category}
            if save_path:
                add_kwargs["save_path"] = save_path
                add_kwargs["use_auto_torrent_management"] = False
            self._sync_client.torrents_add(**add_kwargs)
            after = self._sync_client.torrents_info()
            new = [t for t in after if t.hash not in before]
            if new:
                return new[0].hash
            return after[-1].hash if after else ""
        except Exception as exc:
            logger.error("Ошибка _add_torrent_sync: %s", exc)
            return ""

    async def list_torrents(self) -> list[TorrentInfo]:
        try:
            async with httpx.AsyncClient(timeout=8.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                resp = await client.get(f"{self._base_url}/api/v2/torrents/info", cookies=self._cookies, timeout=8.0)
                if resp.status_code in (401, 403):
                    self._cookies.clear()
                    await self._ensure_auth(client)
                    resp = await client.get(f"{self._base_url}/api/v2/torrents/info", cookies=self._cookies, timeout=8.0)
                resp.raise_for_status()
                data = resp.json()
                result = []
                for t in data:
                    dlspeed = t.get("dlspeed", 0) or 0
                    upspeed = t.get("upspeed", 0) or 0
                    eta = t.get("eta")
                    if eta and (eta < 0 or eta >= 8640000):
                        eta = None
                    result.append(
                        TorrentInfo(
                            hash=t.get("hash", ""),
                            name=t.get("name", ""),
                            progress=float(t.get("progress", 0) or 0),
                            state=t.get("state", "").lower(),
                            save_path=t.get("save_path", ""),
                            size=int(t.get("total_size", t.get("size", 0)) or 0),
                            content_path=t.get("content_path", "") or "",
                            download_speed=int(dlspeed),
                            upload_speed=int(upspeed),
                            eta=int(eta) if eta is not None else None,
                            seeding_time=int(t.get("seeding_time", 0) or t.get("time_active", 0) or 0),
                            ratio=float(t.get("ratio", 0.0) or 0.0),
                        )
                    )
                return result
        except Exception as exc:
            logger.warning("Ошибка list_torrents в qBittorrent (%s): %s", self._base_url, exc)
            if self._sync_client:
                return await asyncio.to_thread(self._list_torrents_sync)
            return []

    def _list_torrents_sync(self) -> list[TorrentInfo]:
        try:
            self._sync_client.auth_log_in()
            result = []
            for t in self._sync_client.torrents_info():
                dlspeed = getattr(t, "dlspeed", 0) or 0
                upspeed = getattr(t, "upspeed", 0) or 0
                eta = getattr(t, "eta", None)
                if eta and (eta < 0 or eta >= 8640000):
                    eta = None
                result.append(
                    TorrentInfo(
                        hash=t.hash, name=t.name, progress=t.progress,
                        state=t.state, save_path=t.save_path, size=t.size,
                        content_path=getattr(t, "content_path", "") or "",
                        download_speed=dlspeed, upload_speed=upspeed, eta=eta,
                        seeding_time=int(getattr(t, "seeding_time", 0) or getattr(t, "time_active", 0) or 0),
                        ratio=float(getattr(t, "ratio", 0.0) or 0.0),
                    )
                )
            return result
        except Exception:
            return []

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        try:
            async with httpx.AsyncClient(timeout=8.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                resp = await client.get(f"{self._base_url}/api/v2/torrents/info?hashes={torrent_hash}", cookies=self._cookies, timeout=8.0)
                if resp.status_code in (401, 403):
                    self._cookies.clear()
                    await self._ensure_auth(client)
                    resp = await client.get(f"{self._base_url}/api/v2/torrents/info?hashes={torrent_hash}", cookies=self._cookies, timeout=8.0)
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    return None
                t = data[0]

                # Запрашиваем файлы
                files_resp = await client.get(f"{self._base_url}/api/v2/torrents/files?hash={torrent_hash}", cookies=self._cookies, timeout=8.0)
                files_data = files_resp.json() if files_resp.status_code == 200 else []
                file_infos = [
                    TorrentFile(
                        index=f.get("index", idx),
                        name=f.get("name", ""),
                        size=int(f.get("size", 0) or 0),
                        progress=float(f.get("progress", 0) or 0),
                        priority=int(f.get("priority", 1) or 1),
                    )
                    for idx, f in enumerate(files_data)
                ]

                dlspeed = t.get("dlspeed", 0) or 0
                upspeed = t.get("upspeed", 0) or 0
                eta = t.get("eta")
                if eta and (eta < 0 or eta >= 8640000):
                    eta = None
                return TorrentInfo(
                    hash=t.get("hash", ""),
                    name=t.get("name", ""),
                    progress=float(t.get("progress", 0) or 0),
                    state=t.get("state", "").lower(),
                    save_path=t.get("save_path", ""),
                    size=int(t.get("total_size", t.get("size", 0)) or 0),
                    content_path=t.get("content_path", "") or "",
                    download_speed=int(dlspeed),
                    upload_speed=int(upspeed),
                    eta=int(eta) if eta is not None else None,
                    seeding_time=int(t.get("seeding_time", 0) or t.get("time_active", 0) or 0),
                    ratio=float(t.get("ratio", 0.0) or 0.0),
                    files=file_infos,
                )
        except Exception as exc:
            logger.warning("Ошибка get_torrent в qBittorrent (%s): %s", torrent_hash, exc)
            return None

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        try:
            async with httpx.AsyncClient(timeout=8.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                data = {"hash": torrent_hash, "id": "|".join(str(i) for i in file_indices), "priority": str(priority)}
                await client.post(f"{self._base_url}/api/v2/torrents/filePrio", data=data, cookies=self._cookies, timeout=8.0)
        except Exception as exc:
            logger.warning("Ошибка set_file_priorities в qBittorrent: %s", exc)

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        try:
            async with httpx.AsyncClient(timeout=8.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                data = {"hashes": torrent_hash, "deleteFiles": "true" if delete_files else "false"}
                await client.post(f"{self._base_url}/api/v2/torrents/delete", data=data, cookies=self._cookies, timeout=8.0)
        except Exception as exc:
            logger.warning("Ошибка remove_torrent в qBittorrent: %s", exc)

    async def pause_torrent(self, torrent_hash: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=8.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                await client.post(f"{self._base_url}/api/v2/torrents/pause", data={"hashes": torrent_hash}, cookies=self._cookies, timeout=8.0)
        except Exception as exc:
            logger.warning("Ошибка pause_torrent в qBittorrent: %s", exc)

    async def resume_torrent(self, torrent_hash: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=8.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                await client.post(f"{self._base_url}/api/v2/torrents/resume", data={"hashes": torrent_hash}, cookies=self._cookies, timeout=8.0)
        except Exception as exc:
            logger.warning("Ошибка resume_torrent в qBittorrent: %s", exc)

    async def recheck_torrent(self, torrent_hash: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=8.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                await client.post(f"{self._base_url}/api/v2/torrents/recheck", data={"hashes": torrent_hash}, cookies=self._cookies, timeout=8.0)
        except Exception as exc:
            logger.warning("Ошибка recheck_torrent в qBittorrent (%s): %s", torrent_hash, exc)
            if self._sync_client:
                try:
                    await asyncio.to_thread(self._sync_client.torrents_recheck, torrent_hashes=torrent_hash)
                except Exception:
                    pass

    async def get_client_logs(self, limit: int = 100) -> list[dict]:
        """Получает журнал работы qBittorrent через /api/v2/log/main."""
        logs = []
        try:
            async with httpx.AsyncClient(timeout=10.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                resp = await client.get(
                    f"{self._base_url}/api/v2/log/main",
                    params={"normal": "true", "info": "true", "warning": "true", "critical": "true", "last_known_id": "-1"},
                    cookies=self._cookies,
                )
                if resp.status_code == 200:
                    raw_logs = resp.json()
                    for item in raw_logs:
                        t_val = item.get("type", 1)
                        lvl = "error" if t_val >= 8 else ("warning" if t_val >= 4 else "info")
                        ts = item.get("timestamp")
                        ts_str = ""
                        if ts:
                            try:
                                import datetime as dt
                                ts_sec = ts / 1000.0 if ts > 10**11 else float(ts)
                                ts_str = dt.datetime.fromtimestamp(ts_sec, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                ts_str = str(ts)
                        logs.append({
                            "id": item.get("id"),
                            "timestamp": ts_str,
                            "level": lvl,
                            "message": item.get("message", ""),
                            "category": "qbittorrent",
                        })
        except Exception as exc:
            logger.debug("qBittorrent get_client_logs failed: %s", exc)
        return logs[-limit:]

    async def get_client_diagnostics(self) -> dict:
        """Возвращает диагностические данные qBittorrent."""
        diag = {"client_type": "qbittorrent", "connected": False}
        try:
            async with httpx.AsyncClient(timeout=10.0, cookies=self._cookies) as client:
                await self._ensure_auth(client)
                ver_resp = await client.get(f"{self._base_url}/api/v2/app/version", cookies=self._cookies)
                api_resp = await client.get(f"{self._base_url}/api/v2/app/webapiVersion", cookies=self._cookies)
                torrents = await self.list_torrents()
                diag.update({
                    "connected": True,
                    "version": ver_resp.text.strip() if ver_resp.status_code == 200 else "unknown",
                    "webapi_version": api_resp.text.strip() if api_resp.status_code == 200 else "unknown",
                    "total_torrent_count": len(torrents),
                    "torrents": [
                        {
                            "hash": t.hash,
                            "name": t.name,
                            "state": t.state,
                            "progress": round(t.progress * 100, 1),
                            "left_until_done": t.left_until_done,
                            "size": t.size,
                            "download_speed": t.download_speed,
                            "upload_speed": t.upload_speed,
                        }
                        for t in torrents
                    ],
                })
        except Exception as exc:
            diag["error"] = str(exc)
        return diag


class TransmissionClient(BaseDownloadClient):
    """Асинхронный клиент Transmission RPC через httpx с поддержкой transmission_rpc."""

    def __init__(self, host: str, port: int, username: str, password: str):
        self._rpc_url = _normalize_client_url(host, port, default_port=9091).rstrip("/") + "/transmission/rpc"
        self._auth = (username, password) if (username or password) else None
        self._session_id: Optional[str] = None
        try:
            import transmission_rpc
            self._sync_client = transmission_rpc.Client(
                host=host, port=port, username=username, password=password,
            )
        except ImportError:
            self._sync_client = None

    async def _rpc_call(self, method: str, arguments: Optional[dict] = None) -> dict:
        headers = {}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id

        async with httpx.AsyncClient(timeout=30.0, auth=self._auth, verify=False) as client:
            resp = await client.post(self._rpc_url, json={"method": method, "arguments": arguments or {}}, headers=headers)
            if resp.status_code == 409:
                self._session_id = resp.headers.get("X-Transmission-Session-Id")
                headers["X-Transmission-Session-Id"] = self._session_id
                resp = await client.post(self._rpc_url, json={"method": method, "arguments": arguments or {}}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            result_str = data.get("result", "")
            if result_str and result_str not in ("success", "duplicate torrent"):
                raise RuntimeError(f"Transmission RPC вернул ошибку: '{result_str}'")
            return data.get("arguments", {})

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        torrent_bytes, resolved_url = await _fetch_torrent_content_if_url(url_or_magnet)
        expected_hash = extract_info_hash_from_url_or_magnet(resolved_url)
        if torrent_bytes and not expected_hash:
            expected_hash = extract_info_hash_from_torrent_bytes(torrent_bytes)

        try:
            if torrent_bytes:
                metainfo_b64 = base64.b64encode(torrent_bytes).decode("ascii")
                args = {"metainfo": metainfo_b64}
            else:
                args = {"filename": resolved_url}

            if category:
                args["labels"] = [category]
            if save_path:
                args["download-dir"] = save_path
            args["paused"] = False

            res = await self._rpc_call("torrent-add", args)
            torrent_added = res.get("torrent-added") or res.get("torrent-duplicate") or {}
            hash_str = str(torrent_added.get("hashString", "")).strip().lower()
            if hash_str:
                if res.get("torrent-duplicate"):
                    try:
                        await self._rpc_call("torrent-start", {"ids": [hash_str]})
                        await self._rpc_call("torrent-verify", {"ids": [hash_str]})
                    except Exception as e:
                        logger.debug("Не удалось перезапустить duplicate torrent в Transmission: %s", e)
                return hash_str
            if expected_hash:
                return expected_hash
            raise RuntimeError(f"Transmission не подтвердил получение торрента (ответ: {res})")
        except Exception as exc:
            logger.warning("Ошибка add_torrent в Transmission: %s", exc)
            if self._sync_client:
                sync_res = await asyncio.to_thread(self._add_torrent_sync, resolved_url, category, save_path)
                if sync_res:
                    return sync_res
            exc_desc = str(exc).strip()
            if not exc_desc:
                if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
                    exc_desc = "таймаут ответа от Transmission RPC (более 30 сек)"
                elif isinstance(exc, httpx.NetworkError):
                    exc_desc = f"сетевая ошибка подключения к Transmission ({type(exc).__name__})"
                else:
                    exc_desc = f"{type(exc).__name__}"
            raise RuntimeError(f"Ошибка Transmission при добавлении торрента: {exc_desc}")

    def _add_torrent_sync(self, url_or_magnet: str, category: Optional[str], save_path: Optional[str]) -> str:
        try:
            kwargs = {}
            if category:
                kwargs["labels"] = [category]
            if save_path:
                kwargs["download_dir"] = save_path
            torrent = self._sync_client.add_torrent(url_or_magnet, **kwargs)
            return str(getattr(torrent, "hashString", "") or "")
        except Exception:
            return ""

    TRANSMISSION_STATUS_MAP = {
        0: "stopped",
        1: "check_wait",
        2: "checking",
        3: "download_wait",
        4: "downloading",
        5: "seed_wait",
        6: "seeding",
    }

    async def list_torrents(self) -> list[TorrentInfo]:
        try:
            fields = [
                "id", "hashString", "name", "percentDone", "leftUntilDone", "sizeWhenDone",
                "isFinished", "status", "downloadDir", "totalSize", "rateDownload", "rateUpload",
                "eta", "secondsSeeding", "uploadRatio"
            ]
            res = await self._rpc_call("torrent-get", {"fields": fields})
            torrents = res.get("torrents", [])
            result = []
            for t in torrents:
                dlspeed = t.get("rateDownload", 0) or 0
                upspeed = t.get("rateUpload", 0) or 0
                eta = t.get("eta")
                if eta and (eta < 0 or eta >= 8640000):
                    eta = None

                left_until_done = t.get("leftUntilDone")
                size_when_done = t.get("sizeWhenDone", 0) or 0
                is_finished = bool(t.get("isFinished", False))
                status_val = t.get("status")

                if is_finished or status_val in (5, 6) or (left_until_done is not None and left_until_done == 0 and size_when_done > 0):
                    progress = 1.0
                elif size_when_done > 0 and left_until_done is not None:
                    progress = max(0.0, min(1.0, float(size_when_done - left_until_done) / float(size_when_done)))
                else:
                    progress = float(t.get("percentDone", 0) or 0)

                status_str = self.TRANSMISSION_STATUS_MAP.get(status_val, str(status_val if status_val is not None else "downloading")).lower()
                if status_val == 0 and progress >= 0.999:
                    status_str = "pausedup"

                result.append(
                    TorrentInfo(
                        hash=t.get("hashString", ""),
                        name=t.get("name", ""),
                        progress=progress,
                        state=status_str,
                        save_path=t.get("downloadDir", ""),
                        size=int(t.get("totalSize", 0) or 0),
                        download_speed=int(dlspeed),
                        upload_speed=int(upspeed),
                        eta=int(eta) if eta is not None else None,
                        seeding_time=int(t.get("secondsSeeding", 0) or 0),
                        ratio=float(t.get("uploadRatio", 0.0) or 0.0),
                        left_until_done=int(left_until_done) if left_until_done is not None else None,
                    )
                )
            return result
        except Exception as exc:
            logger.warning("Ошибка list_torrents в Transmission: %s", exc)
            if self._sync_client:
                return await asyncio.to_thread(self._list_torrents_sync)
            return []

    def _list_torrents_sync(self) -> list[TorrentInfo]:
        try:
            result = []
            for t in self._sync_client.get_torrents():
                dlspeed = getattr(t, "rate_download", 0) or 0
                upspeed = getattr(t, "rate_upload", 0) or 0
                eta = getattr(t, "eta", None)
                if eta and (eta < 0 or eta >= 8640000):
                    eta = None

                left_until_done = getattr(t, "left_until_done", None)
                if left_until_done is None:
                    left_until_done = getattr(t, "leftUntilDone", None)
                size_when_done = getattr(t, "size_when_done", 0) or getattr(t, "sizeWhenDone", 0) or 0
                is_finished = getattr(t, "is_finished", False) or getattr(t, "isFinished", False)
                status_raw = getattr(t, "status", "downloading")
                status_str = str(status_raw).lower()

                if is_finished or status_str in ("seeding", "seed_wait", "seed", "5", "6") or (left_until_done is not None and left_until_done == 0 and size_when_done > 0):
                    progress = 1.0
                elif size_when_done > 0 and left_until_done is not None:
                    progress = max(0.0, min(1.0, float(size_when_done - left_until_done) / float(size_when_done)))
                else:
                    progress = (t.progress or 0) / 100

                if status_str in ("stopped", "paused", "0") and progress >= 0.999:
                    status_str = "pausedup"

                result.append(
                    TorrentInfo(
                        hash=t.hashString, name=t.name, progress=progress,
                        state=status_str, save_path=t.download_dir, size=t.total_size,
                        download_speed=dlspeed, upload_speed=upspeed, eta=eta,
                        seeding_time=int(getattr(t, "seconds_seeding", 0) or getattr(t, "secondsSeeding", 0) or 0),
                        ratio=float(getattr(t, "ratio", 0.0) or getattr(t, "upload_ratio", 0.0) or 0.0),
                        left_until_done=int(left_until_done) if left_until_done is not None else None,
                    )
                )
            return result
        except Exception:
            return []

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        try:
            fields = [
                "id", "hashString", "name", "percentDone", "leftUntilDone", "sizeWhenDone",
                "isFinished", "status", "downloadDir", "totalSize", "rateDownload", "rateUpload",
                "eta", "secondsSeeding", "uploadRatio", "files", "fileStats"
            ]
            res = await self._rpc_call("torrent-get", {"fields": fields, "ids": [torrent_hash]})
            torrents = res.get("torrents", [])
            if not torrents:
                res_all = await self._rpc_call("torrent-get", {"fields": fields})
                all_torrents = res_all.get("torrents", [])
                torrents = [t for t in all_torrents if str(t.get("hashString", "")).lower() == torrent_hash.lower()]
            if not torrents:
                if self._sync_client:
                    return await asyncio.to_thread(self._get_torrent_sync, torrent_hash)
                return None
            t = torrents[0]
            files_raw = t.get("files", [])
            stats_raw = t.get("fileStats", [])
            file_infos = []
            for i, f in enumerate(files_raw):
                stat = stats_raw[i] if i < len(stats_raw) else {}
                file_size = f.get("length", 0) or 0
                bytes_completed = f.get("bytesCompleted", 0) or 0
                file_infos.append(
                    TorrentFile(
                        index=i,
                        name=f.get("name", ""),
                        size=file_size,
                        progress=(bytes_completed / file_size) if file_size else 0.0,
                        priority=1 if stat.get("wanted", True) else 0,
                    )
                )
            dlspeed = t.get("rateDownload", 0) or 0
            upspeed = t.get("rateUpload", 0) or 0
            eta = t.get("eta")
            if eta and (eta < 0 or eta >= 8640000):
                eta = None

            left_until_done = t.get("leftUntilDone")
            size_when_done = t.get("sizeWhenDone", 0) or 0
            is_finished = bool(t.get("isFinished", False))
            status_val = t.get("status")

            if is_finished or status_val in (5, 6) or (left_until_done is not None and left_until_done == 0 and size_when_done > 0):
                progress = 1.0
            elif size_when_done > 0 and left_until_done is not None:
                progress = max(0.0, min(1.0, float(size_when_done - left_until_done) / float(size_when_done)))
            else:
                progress = float(t.get("percentDone", 0) or 0)

            status_str = self.TRANSMISSION_STATUS_MAP.get(status_val, str(status_val if status_val is not None else "downloading")).lower()
            if status_val == 0 and progress >= 0.999:
                status_str = "pausedup"

            return TorrentInfo(
                hash=t.get("hashString", ""),
                name=t.get("name", ""),
                progress=progress,
                state=status_str,
                save_path=t.get("downloadDir", ""),
                size=int(t.get("totalSize", 0) or 0),
                download_speed=int(dlspeed),
                upload_speed=int(upspeed),
                eta=int(eta) if eta is not None else None,
                seeding_time=int(t.get("secondsSeeding", 0) or 0),
                ratio=float(t.get("uploadRatio", 0.0) or 0.0),
                files=file_infos,
                left_until_done=int(left_until_done) if left_until_done is not None else None,
            )
        except Exception as exc:
            logger.warning("Ошибка get_torrent в Transmission: %s", exc)
            if self._sync_client:
                return await asyncio.to_thread(self._get_torrent_sync, torrent_hash)
            return None

    def _get_torrent_sync(self, torrent_hash: str) -> Optional[TorrentInfo]:
        try:
            t = self._sync_client.get_torrent(torrent_hash)
            file_infos = []
            files = getattr(t, "files", []) or []
            for i, f in enumerate(files):
                file_infos.append(
                    TorrentFile(
                        index=i,
                        name=getattr(f, "name", ""),
                        size=getattr(f, "size", 0) or 0,
                        progress=(getattr(f, "completed", 0) / f.size) if getattr(f, "size", 0) else 0.0,
                        priority=1 if getattr(f, "selected", True) else 0,
                    )
                )
            dlspeed = getattr(t, "rate_download", 0) or 0
            upspeed = getattr(t, "rate_upload", 0) or 0
            eta = getattr(t, "eta", None)
            if eta and (eta < 0 or eta >= 8640000):
                eta = None

            left_until_done = getattr(t, "left_until_done", None)
            if left_until_done is None:
                left_until_done = getattr(t, "leftUntilDone", None)
            size_when_done = getattr(t, "size_when_done", 0) or getattr(t, "sizeWhenDone", 0) or 0
            is_finished = getattr(t, "is_finished", False) or getattr(t, "isFinished", False)
            status_raw = getattr(t, "status", "downloading")
            status_str = str(status_raw).lower()

            if is_finished or status_str in ("seeding", "seed_wait", "seed", "5", "6") or (left_until_done is not None and left_until_done == 0 and size_when_done > 0):
                progress = 1.0
            elif size_when_done > 0 and left_until_done is not None:
                progress = max(0.0, min(1.0, float(size_when_done - left_until_done) / float(size_when_done)))
            else:
                progress = (t.progress or 0) / 100

            if status_str in ("stopped", "paused", "0") and progress >= 0.999:
                status_str = "pausedup"

            return TorrentInfo(
                hash=t.hashString,
                name=t.name,
                progress=progress,
                state=status_str,
                save_path=t.download_dir,
                size=t.total_size,
                download_speed=dlspeed,
                upload_speed=upspeed,
                eta=eta,
                seeding_time=int(getattr(t, "seconds_seeding", 0) or 0),
                ratio=float(getattr(t, "ratio", 0.0) or 0.0),
                files=file_infos,
                left_until_done=int(left_until_done) if left_until_done is not None else None,
            )
        except Exception:
            return None

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        try:
            if priority == 0:
                await self._rpc_call("torrent-set", {"ids": [torrent_hash], "files-unwanted": file_indices})
            else:
                await self._rpc_call("torrent-set", {"ids": [torrent_hash], "files-wanted": file_indices})
        except Exception as exc:
            logger.warning("Ошибка set_file_priorities в Transmission: %s", exc)
            if self._sync_client:
                await asyncio.to_thread(self._set_file_priorities_sync, torrent_hash, file_indices, priority)

    def _set_file_priorities_sync(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        try:
            torrent = self._sync_client.get_torrent(torrent_hash)
            if priority == 0:
                self._sync_client.change_torrent(torrent.id, files_unwanted=file_indices)
            else:
                self._sync_client.change_torrent(torrent.id, files_wanted=file_indices)
        except Exception:
            pass

    async def set_files_wanted_unwanted(self, torrent_hash: str, wanted_indices: list[int], unwanted_indices: list[int]) -> None:
        try:
            # Получаем реальный числовой ID торрента в Transmission для корректной работы torrent-set
            t_id = None
            try:
                res = await self._rpc_call("torrent-get", {"fields": ["id", "hashString"], "ids": [torrent_hash]})
                torrents = res.get("torrents", [])
                if not torrents:
                    res_all = await self._rpc_call("torrent-get", {"fields": ["id", "hashString"]})
                    torrents = [t for t in res_all.get("torrents", []) if str(t.get("hashString", "")).lower() == torrent_hash.lower()]
                if torrents:
                    t_id = torrents[0].get("id")
            except Exception as e:
                logger.debug("Не удалось получить числовой ID торрента в Transmission: %s", e)

            target_ids = [t_id] if t_id is not None else [torrent_hash]

            # Вызываем сначала отключение нежелательных файлов, затем включение нужных
            if unwanted_indices:
                await self._rpc_call("torrent-set", {"ids": target_ids, "files-unwanted": unwanted_indices})
            if wanted_indices:
                await self._rpc_call("torrent-set", {"ids": target_ids, "files-wanted": wanted_indices})

            # Если доступен sync_client transmission_rpc, дублируем вызов через нативный python-клиент
            if self._sync_client:
                target_ref = t_id if t_id is not None else torrent_hash
                try:
                    await asyncio.to_thread(self._set_files_wanted_unwanted_sync, str(target_ref), wanted_indices, unwanted_indices)
                except Exception as sync_exc:
                    logger.debug("Дублирование через sync transmission_rpc: %s", sync_exc)
        except Exception as exc:
            logger.warning("Ошибка set_files_wanted_unwanted в Transmission: %s", exc)
            if self._sync_client:
                await asyncio.to_thread(self._set_files_wanted_unwanted_sync, torrent_hash, wanted_indices, unwanted_indices)

    def _set_files_wanted_unwanted_sync(self, torrent_hash: str, wanted_indices: list[int], unwanted_indices: list[int]) -> None:
        try:
            torrent = None
            try:
                torrent = self._sync_client.get_torrent(int(torrent_hash))
            except Exception:
                torrent = self._sync_client.get_torrent(torrent_hash)
            if not torrent:
                return
            if unwanted_indices:
                self._sync_client.change_torrent(torrent.id, files_unwanted=unwanted_indices)
            if wanted_indices:
                self._sync_client.change_torrent(torrent.id, files_wanted=wanted_indices)
        except Exception as e:
            logger.debug("Ошибка в _set_files_wanted_unwanted_sync: %s", e)

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        try:
            await self._rpc_call("torrent-remove", {"ids": [torrent_hash], "delete-local-data": delete_files})
        except Exception as exc:
            logger.warning("Ошибка remove_torrent в Transmission: %s", exc)

    async def pause_torrent(self, torrent_hash: str) -> None:
        try:
            await self._rpc_call("torrent-stop", {"ids": [torrent_hash]})
        except Exception as exc:
            logger.warning("Ошибка pause_torrent в Transmission: %s", exc)

    async def resume_torrent(self, torrent_hash: str) -> None:
        try:
            await self._rpc_call("torrent-start", {"ids": [torrent_hash]})
        except Exception as exc:
            logger.warning("Ошибка resume_torrent в Transmission: %s", exc)

    async def recheck_torrent(self, torrent_hash: str) -> None:
        try:
            await self._rpc_call("torrent-verify", {"ids": [torrent_hash]})
        except Exception as exc:
            logger.warning("Ошибка recheck_torrent в Transmission (%s): %s", torrent_hash, exc)
            if self._sync_client:
                try:
                    await asyncio.to_thread(self._sync_client.verify_torrent, torrent_hash)
                except Exception:
                    pass

    async def get_client_logs(self, limit: int = 100) -> list[dict]:
        """Получает журнал работы Transmission через RPC message-get."""
        logs = []
        try:
            res = await self._rpc_call("message-get", {})
            raw_msgs = res.get("messages", []) if isinstance(res, dict) else []
            for m in raw_msgs:
                level_num = m.get("level", 2)
                lvl = "error" if level_num == 1 else ("info" if level_num == 2 else "debug")
                ts = m.get("timestamp")
                ts_str = ""
                if ts:
                    try:
                        import datetime as dt
                        ts_str = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        ts_str = str(ts)
                logs.append({
                    "id": m.get("id"),
                    "timestamp": ts_str,
                    "level": lvl,
                    "message": m.get("message", ""),
                    "category": m.get("category", "") or m.get("name", "transmission"),
                })
        except Exception as exc:
            logger.debug("Transmission get_client_logs failed: %s", exc)
        return logs[-limit:]

    async def get_client_diagnostics(self) -> dict:
        """Возвращает диагностические данные Transmission."""
        diag = {"client_type": "transmission", "connected": False}
        try:
            session_info = await self._rpc_call("session-get", {})
            stats_info = await self._rpc_call("session-stats", {})
            torrents = await self.list_torrents()
            diag.update({
                "connected": True,
                "version": session_info.get("version", "unknown"),
                "rpc_version": session_info.get("rpc-version", "unknown"),
                "download_dir": session_info.get("download-dir", ""),
                "active_torrent_count": stats_info.get("activeTorrentCount", 0),
                "total_torrent_count": stats_info.get("torrentCount", len(torrents)),
                "download_speed": stats_info.get("downloadSpeed", 0),
                "upload_speed": stats_info.get("uploadSpeed", 0),
                "torrents": [
                    {
                        "hash": t.hash,
                        "name": t.name,
                        "state": t.state,
                        "progress": round(t.progress * 100, 1),
                        "left_until_done": t.left_until_done,
                        "size": t.size,
                        "download_speed": t.download_speed,
                        "upload_speed": t.upload_speed,
                    }
                    for t in torrents
                ],
            })
        except Exception as exc:
            diag["error"] = str(exc)
        return diag


class DelugeClient(BaseDownloadClient):
    """Асинхронный клиент Deluge Web JSON-RPC."""

    def __init__(self, host: str, port: int, password: str):
        schema = "http" if not host.startswith("http") else ""
        host_clean = host if not schema else f"{schema}://{host}"
        self._url = f"{host_clean}:{port}/json" if ":" not in host_clean.split("/")[-1] else f"{host_clean}/json"
        self._password = password
        self._msg_id = 0
        self._session_cookies: dict[str, str] = {}

    async def _rpc_call(self, method: str, params: list) -> Any:
        self._msg_id += 1
        payload = {"method": method, "params": params, "id": self._msg_id}
        async with httpx.AsyncClient(timeout=15, cookies=self._session_cookies) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
            for k, v in resp.cookies.items():
                self._session_cookies[k] = v
            res_json = resp.json()
            if res_json.get("error"):
                raise ValueError(f"Deluge RPC error: {res_json['error']}")
            return res_json.get("result")

    async def _auth(self) -> None:
        auth_ok = await self._rpc_call("auth.login", [self._password])
        if not auth_ok:
            raise PermissionError("Deluge login failed (invalid password)")

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        await self._auth()
        opts: dict[str, Any] = {}
        if save_path:
            opts["download_location"] = save_path

        if url_or_magnet.startswith("magnet:"):
            res = await self._rpc_call("core.add_torrent_magnet", [url_or_magnet, opts])
            return str(res or "")
        else:
            # Скачиваем .torrent и передаём base64
            async with httpx.AsyncClient(timeout=15) as http_client:
                torrent_resp = await http_client.get(url_or_magnet)
                torrent_resp.raise_for_status()
                b64 = base64.b64encode(torrent_resp.content).decode("ascii")
            res = await self._rpc_call("core.add_torrent_file", ["release.torrent", b64, opts])
            return str(res or "")

    async def list_torrents(self) -> list[TorrentInfo]:
        await self._auth()
        fields = ["name", "progress", "state", "save_path", "total_size"]
        res = await self._rpc_call("web.get_torrents_status", [{}, fields])
        torrents = []
        if isinstance(res, dict):
            for t_hash, data in res.items():
                torrents.append(
                    TorrentInfo(
                        hash=t_hash,
                        name=data.get("name", ""),
                        progress=(data.get("progress", 0) or 0) / 100,
                        state=data.get("state", "").lower(),
                        save_path=data.get("save_path", ""),
                        size=data.get("total_size", 0),
                    )
                )
        return torrents

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        await self._auth()
        fields = ["name", "progress", "state", "save_path", "total_size", "files", "file_progress", "file_priorities"]
        res = await self._rpc_call("web.get_torrents_status", [{"id": torrent_hash}, fields])
        if not res or torrent_hash not in res:
            return None
        data = res[torrent_hash]
        files_data = data.get("files", [])
        file_prio = data.get("file_priorities", [])
        file_prog = data.get("file_progress", [])

        files = []
        for idx, f in enumerate(files_data):
            files.append(
                TorrentFile(
                    index=f.get("index", idx),
                    name=f.get("path", f.get("name", "")),
                    size=f.get("size", 0),
                    progress=file_prog[idx] if idx < len(file_prog) else 0.0,
                    priority=file_prio[idx] if idx < len(file_prio) else 1,
                )
            )
        return TorrentInfo(
            hash=torrent_hash,
            name=data.get("name", ""),
            progress=(data.get("progress", 0) or 0) / 100,
            state=data.get("state", "").lower(),
            save_path=data.get("save_path", ""),
            size=data.get("total_size", 0),
            files=files,
        )

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        t = await self.get_torrent(torrent_hash)
        if not t or not t.files:
            return
        prios = [1] * len(t.files)
        for idx in file_indices:
            if idx < len(prios):
                prios[idx] = priority
        await self._rpc_call("core.set_torrent_file_priorities", [torrent_hash, prios])

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        await self._auth()
        await self._rpc_call("core.remove_torrent", [torrent_hash, delete_files])

    async def pause_torrent(self, torrent_hash: str) -> None:
        await self._auth()
        await self._rpc_call("core.pause_torrent", [[torrent_hash]])

    async def resume_torrent(self, torrent_hash: str) -> None:
        await self._auth()
        await self._rpc_call("core.resume_torrent", [[torrent_hash]])

    async def recheck_torrent(self, torrent_hash: str) -> None:
        try:
            await self._auth()
            await self._rpc_call("core.force_recheck", [[torrent_hash]])
        except Exception as exc:
            logger.warning("Ошибка recheck_torrent в Deluge: %s", exc)


class RTorrentClient(BaseDownloadClient):
    """Асинхронный клиент rTorrent XML-RPC."""

    def __init__(self, host: str, port: int, username: Optional[str] = None, password: Optional[str] = None):
        schema = "http" if not host.startswith("http") else ""
        host_clean = host if not schema else f"{schema}://{host}"
        if ":" not in host_clean.split("/")[-1]:
            self._url = f"{host_clean}:{port}/RPC2"
        else:
            self._url = f"{host_clean}/RPC2"
        self._auth = (username, password) if username and password else None

    async def _call(self, method: str, *args) -> Any:
        import xmlrpc.client
        xml_req = xmlrpc.client.dumps(args, methodname=method)
        async with httpx.AsyncClient(timeout=15, auth=self._auth) as client:
            resp = await client.post(self._url, content=xml_req, headers={"Content-Type": "text/xml"})
            resp.raise_for_status()
            params, _ = xmlrpc.client.loads(resp.content)
            return params[0] if params else None

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        extra_args = []
        if save_path:
            extra_args.append(f"d.directory.set={save_path}")
        if category:
            extra_args.append(f"d.custom1.set={category}")

        if url_or_magnet.startswith("magnet:"):
            await self._call("load.start", "", url_or_magnet, *extra_args)
            # Извлекаем хеш из magnet ссылки
            m = re.search(r"xt=urn:btih:([a-zA-Z0-9]+)", url_or_magnet, re.IGNORECASE)
            return m.group(1).lower() if m else ""
        else:
            async with httpx.AsyncClient(timeout=15) as http_client:
                r = await http_client.get(url_or_magnet)
                r.raise_for_status()
                await self._call("load.raw_start", "", xmlrpc.client.Binary(r.content), *extra_args)
            return ""

    async def list_torrents(self) -> list[TorrentInfo]:
        try:
            res = await self._call("d.multicall2", "", "main", "d.hash=", "d.name=", "d.bytes_done=", "d.size_bytes=", "d.is_active=", "d.directory=")
        except Exception:
            return []
        torrents = []
        if isinstance(res, list):
            for row in res:
                if len(row) >= 6:
                    t_hash, name, bytes_done, size_bytes, is_active, directory = row[0], row[1], row[2], row[3], row[4], row[5]
                    prog = (bytes_done / size_bytes) if size_bytes else 0
                    state = "seeding" if prog >= 1.0 else ("downloading" if is_active else "paused")
                    torrents.append(
                        TorrentInfo(
                            hash=str(t_hash).lower(),
                            name=str(name),
                            progress=prog,
                            state=state,
                            save_path=str(directory),
                            size=int(size_bytes),
                        )
                    )
        return torrents

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        try:
            torrents = await self.list_torrents()
            found = [t for t in torrents if t.hash.lower() == torrent_hash.lower()]
            return found[0] if found else None
        except Exception:
            return None

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        for idx in file_indices:
            try:
                await self._call("f.priority.set", f"{torrent_hash}:f{idx}", priority)
            except Exception:
                pass
        try:
            await self._call("d.update_priorities", torrent_hash)
        except Exception:
            pass

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        await self._call("d.erase", torrent_hash)

    async def pause_torrent(self, torrent_hash: str) -> None:
        await self._call("d.stop", torrent_hash)

    async def resume_torrent(self, torrent_hash: str) -> None:
        await self._call("d.start", torrent_hash)

    async def recheck_torrent(self, torrent_hash: str) -> None:
        try:
            await self._call("d.check_hash", torrent_hash)
        except Exception as exc:
            logger.warning("Ошибка recheck_torrent в rTorrent: %s", exc)


class Aria2Client(BaseDownloadClient):
    """Асинхронный клиент Aria2 JSON-RPC."""

    def __init__(self, host: str, port: int, secret_token: Optional[str] = None):
        schema = "http" if not host.startswith("http") else ""
        host_clean = host if not schema else f"{schema}://{host}"
        if ":" not in host_clean.split("/")[-1]:
            self._url = f"{host_clean}:{port}/jsonrpc"
        else:
            self._url = f"{host_clean}/jsonrpc"
        self._secret = secret_token
        self._msg_id = 0

    async def _call(self, method: str, params: list) -> Any:
        self._msg_id += 1
        full_params = []
        if self._secret:
            full_params.append(f"token:{self._secret}")
        full_params.extend(params)
        payload = {"jsonrpc": "2.0", "id": str(self._msg_id), "method": method, "params": full_params}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
            res_json = resp.json()
            if res_json.get("error"):
                raise ValueError(f"Aria2 error: {res_json['error']}")
            return res_json.get("result")

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        opts: dict[str, str] = {}
        if save_path:
            opts["dir"] = save_path
        gid = await self._call("aria2.addUri", [[url_or_magnet], opts])
        return str(gid or "")

    async def list_torrents(self) -> list[TorrentInfo]:
        keys = ["gid", "status", "totalLength", "completedLength", "dir", "bittorrent", "files"]
        active = await self._call("aria2.tellActive", [keys]) or []
        waiting = await self._call("aria2.tellWaiting", [0, 100, keys]) or []
        stopped = await self._call("aria2.tellStopped", [0, 100, keys]) or []
        all_items = active + waiting + stopped
        torrents = []
        for item in all_items:
            bt = item.get("bittorrent") or {}
            info = bt.get("info") or {}
            name = info.get("name") or (item.get("files", [{}])[0].get("path", "") if item.get("files") else item.get("gid", ""))
            total = int(item.get("totalLength", 0))
            completed = int(item.get("completedLength", 0))
            prog = (completed / total) if total else 0
            infohash = bt.get("infoHash", item.get("gid", ""))
            torrents.append(
                TorrentInfo(
                    hash=infohash,
                    name=name,
                    progress=prog,
                    state=item.get("status", "unknown"),
                    save_path=item.get("dir", ""),
                    size=total,
                )
            )
        return torrents

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        torrents = await self.list_torrents()
        found = [t for t in torrents if t.hash.lower() == torrent_hash.lower()]
        return found[0] if found else None

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        if priority > 0:
            selected_str = ",".join(str(i + 1) for i in file_indices)
            try:
                await self._call("aria2.changeOption", [torrent_hash, {"select-file": selected_str}])
            except Exception:
                pass

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        try:
            await self._call("aria2.remove", [torrent_hash])
        except Exception:
            await self._call("aria2.removeDownloadResult", [torrent_hash])

    async def pause_torrent(self, torrent_hash: str) -> None:
        try:
            await self._call("aria2.pause", [torrent_hash])
        except Exception:
            pass

    async def resume_torrent(self, torrent_hash: str) -> None:
        await self._call("aria2.unpause", [torrent_hash])


class BlackholeClient(BaseDownloadClient):
    """Клиент Torrent Blackhole (сохраняет .torrent / .magnet в папку наблюдения)."""

    def __init__(self, watch_dir: str):
        self._watch_dir = watch_dir
        try:
            os.makedirs(self._watch_dir, exist_ok=True)
        except Exception:
            pass

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        if url_or_magnet.startswith("magnet:"):
            m = re.search(r"xt=urn:btih:([a-zA-Z0-9]+)", url_or_magnet, re.IGNORECASE)
            infohash = m.group(1).lower() if m else hashlib.sha1(url_or_magnet.encode()).hexdigest()
            fname = f"{infohash}.magnet"
            fpath = os.path.join(self._watch_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(url_or_magnet)
            return infohash
        else:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url_or_magnet)
                resp.raise_for_status()
                infohash = hashlib.sha1(resp.content).hexdigest()[:40]
                fname = f"{infohash}.torrent"
                fpath = os.path.join(self._watch_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(resp.content)
                return infohash

    async def list_torrents(self) -> list[TorrentInfo]:
        return []

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        return None

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        pass

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        pass

    async def pause_torrent(self, torrent_hash: str) -> None:
        pass

    async def resume_torrent(self, torrent_hash: str) -> None:
        pass


class SabnzbdClient(BaseDownloadClient):
    """Асинхронный клиент SABnzbd REST API."""

    def __init__(self, host: str, port: int, api_key: str):
        schema = "http" if not host.startswith("http") else ""
        host_clean = host if not schema else f"{schema}://{host}"
        self._url = f"{host_clean}:{port}/api" if ":" not in host_clean.split("/")[-1] else f"{host_clean}/api"
        self._api_key = api_key

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        params = {
            "mode": "addurl",
            "name": url_or_magnet,
            "apikey": self._api_key,
            "output": "json",
        }
        if category:
            params["cat"] = category
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(self._url, params=params)
            resp.raise_for_status()
            data = resp.json()
            nzo_ids = data.get("nzo_ids", [])
            return nzo_ids[0] if nzo_ids else ""

    async def list_torrents(self) -> list[TorrentInfo]:
        params = {"mode": "queue", "apikey": self._api_key, "output": "json"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(self._url, params=params)
            resp.raise_for_status()
            data = resp.json()
            queue = data.get("queue", {}).get("slots", [])
            results = []
            for item in queue:
                total = float(item.get("mb", 0)) * 1024 * 1024
                left = float(item.get("mbleft", 0)) * 1024 * 1024
                prog = 1.0 - (left / total) if total else 0
                results.append(
                    TorrentInfo(
                        hash=item.get("nzo_id", ""),
                        name=item.get("filename", ""),
                        progress=max(0.0, min(1.0, prog)),
                        state=item.get("status", "downloading").lower(),
                        save_path="",
                        size=int(total),
                    )
                )
            return results

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        torrents = await self.list_torrents()
        found = [t for t in torrents if t.hash == torrent_hash]
        return found[0] if found else None

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        pass

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        params = {"mode": "queue", "name": "delete", "value": torrent_hash, "apikey": self._api_key, "output": "json"}
        if delete_files:
            params["del_files"] = "1"
        async with httpx.AsyncClient(timeout=15) as client:
            await client.get(self._url, params=params)

    async def pause_torrent(self, torrent_hash: str) -> None:
        params = {"mode": "queue", "name": "pause", "value": torrent_hash, "apikey": self._api_key, "output": "json"}
        async with httpx.AsyncClient(timeout=15) as client:
            await client.get(self._url, params=params)

    async def resume_torrent(self, torrent_hash: str) -> None:
        params = {"mode": "queue", "name": "resume", "value": torrent_hash, "apikey": self._api_key, "output": "json"}
        async with httpx.AsyncClient(timeout=15) as client:
            await client.get(self._url, params=params)


class NZBGetClient(BaseDownloadClient):
    """Асинхронный клиент NZBGet JSON-RPC."""

    def __init__(self, host: str, port: int, username: str, password: str):
        schema = "http" if not host.startswith("http") else ""
        host_clean = host if not schema else f"{schema}://{host}"
        self._url = f"{host_clean}:{port}/jsonrpc" if ":" not in host_clean.split("/")[-1] else f"{host_clean}/jsonrpc"
        self._auth = (username, password) if username and password else None

    async def _call(self, method: str, params: list) -> Any:
        payload = {"method": method, "params": params}
        async with httpx.AsyncClient(timeout=15, auth=self._auth) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
            return resp.json().get("result")

    async def add_torrent(self, url_or_magnet: str, category: Optional[str] = None, save_path: Optional[str] = None) -> str:
        # NZBGet method: append(NZBFilename, Content, Category, Priority, AddToTop, AddPaused, DupeKey, DupeScore, DupeMode)
        res = await self._call("append", ["release.nzb", url_or_magnet, category or "", 0, False, False, "", 0, "SCORE"])
        return str(res or "")

    async def list_torrents(self) -> list[TorrentInfo]:
        groups = await self._call("listgroups", [0]) or []
        results = []
        for g in groups:
            total = int(g.get("FileSizeMB", 0)) * 1024 * 1024
            rem = int(g.get("RemainingSizeMB", 0)) * 1024 * 1024
            prog = 1.0 - (rem / total) if total else 0
            results.append(
                TorrentInfo(
                    hash=str(g.get("NZBID", "")),
                    name=g.get("NZBName", ""),
                    progress=max(0.0, min(1.0, prog)),
                    state=g.get("Status", "downloading").lower(),
                    save_path=g.get("DestDir", ""),
                    size=total,
                )
            )
        return results

    async def get_torrent(self, torrent_hash: str) -> Optional[TorrentInfo]:
        torrents = await self.list_torrents()
        found = [t for t in torrents if t.hash == torrent_hash]
        return found[0] if found else None

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        pass

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        try:
            nzb_id = int(torrent_hash)
            await self._call("editqueue", ["GroupDelete", 0, "", [nzb_id]])
        except Exception:
            pass

    async def pause_torrent(self, torrent_hash: str) -> None:
        try:
            nzb_id = int(torrent_hash)
            await self._call("editqueue", ["GroupPause", 0, "", [nzb_id]])
        except Exception:
            pass

    async def resume_torrent(self, torrent_hash: str) -> None:
        try:
            nzb_id = int(torrent_hash)
            await self._call("editqueue", ["GroupResume", 0, "", [nzb_id]])
        except Exception:
            pass


def get_client(download_client_row) -> BaseDownloadClient:
    """Фабрика создания клиента загрузчика по модели DownloadClient."""
    ctype = getattr(download_client_row, "type", "qbittorrent").lower()
    host = getattr(download_client_row, "host", "localhost")
    port = getattr(download_client_row, "port", 8080)
    username = getattr(download_client_row, "username", None) or ""
    password = getattr(download_client_row, "password", None) or ""

    if ctype == "qbittorrent":
        return QBittorrentClient(host=host, port=port, username=username, password=password)
    elif ctype == "transmission":
        return TransmissionClient(host=host, port=port, username=username, password=password)
    elif ctype == "deluge":
        return DelugeClient(host=host, port=port, password=password)
    elif ctype == "rtorrent":
        return RTorrentClient(host=host, port=port, username=username, password=password)
    elif ctype == "aria2":
        return Aria2Client(host=host, port=port, secret_token=password or username)
    elif ctype == "blackhole":
        return BlackholeClient(watch_dir=host)
    elif ctype == "sabnzbd":
        return SabnzbdClient(host=host, port=port, api_key=password or username)
    elif ctype == "nzbget":
        return NZBGetClient(host=host, port=port, username=username, password=password)

    raise ValueError(f"Неизвестный тип загрузчика: {ctype}")

