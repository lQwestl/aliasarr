"""Модуль индексаторов (Torznab, Newznab, Nyaa.si, Torrent RSS, IPTorrents, TorrentLeech).
Предоставляет единый асинхронный интерфейс поиска релизов для Aliasarr.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional
from xml.etree import ElementTree

try:
    import httpx
except ImportError:
    httpx = None

import datetime as dt
from app.services.torznab import TorznabRelease

logger = logging.getLogger("aliasarr.indexer_service")

TORZNAB_NS = {"torznab": "http://torznab.com/schemas/2015/feed"}
NEWZNAB_NS = {"newznab": "http://newznab.com/schemas/2010/feed"}
NYAA_NS = {"nyaa": "https://nyaa.si/xmlns/nyaa"}


def _parse_release_age_and_date(pub_date_raw: Any) -> tuple[Optional[str], Optional[float]]:
    """Парсит дату публикации (RFC 2822, ISO, строки) и вычисляет возраст в днях (Sonarr ReleaseResource.Age)."""
    if not pub_date_raw:
        return None, None

    parsed_dt = None
    if isinstance(pub_date_raw, dt.datetime):
        parsed_dt = pub_date_raw.replace(tzinfo=None)
    elif isinstance(pub_date_raw, str):
        raw_str = pub_date_raw.strip()
        # 1. RFC 2822 (Torznab: "Wed, 19 Aug 2026 12:00:00 +0000")
        try:
            import email.utils
            p = email.utils.parsedate_to_datetime(raw_str)
            if p:
                parsed_dt = p.replace(tzinfo=None)
        except Exception:
            pass

        # 2. ISO 8601
        if not parsed_dt:
            try:
                clean_iso = raw_str.replace("Z", "+00:00").split("+")[0].strip()
                parsed_dt = dt.datetime.fromisoformat(clean_iso)
            except Exception:
                pass

        # 3. Custom date formats
        if not parsed_dt:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                try:
                    parsed_dt = dt.datetime.strptime(raw_str, fmt)
                    break
                except Exception:
                    pass

    if parsed_dt:
        delta = dt.datetime.utcnow() - parsed_dt
        age_days = max(0.0, round(delta.total_seconds() / 86400.0, 2))
        return parsed_dt.isoformat(), age_days

    return str(pub_date_raw), None


async def _fetch_text_async(url: str, params: Optional[dict] = None, timeout: int = 30) -> str:
    if params:
        encoded = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{encoded}"
    if httpx is not None:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    else:
        def _sync_get():
            req = urllib.request.Request(url, headers={"User-Agent": "Aliasarr/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        return await asyncio.to_thread(_sync_get)


class BaseIndexerClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def search(self, query: str, categories: Optional[list[int]] = None) -> list[TorznabRelease]:
        raise NotImplementedError


class TorznabIndexerClient(BaseIndexerClient):
    """Клиент Torznab (Jackett, Prowlarr, трекеры с Torznab API)."""

    async def search(self, query: str, categories: Optional[list[int]] = None) -> list[TorznabRelease]:
        params = {"t": "search", "q": query}
        if self.api_key:
            params["apikey"] = self.api_key
        if categories:
            params["cat"] = ",".join(str(c) for c in categories)

        url = f"{self.base_url}/api" if not self.base_url.endswith("/api") else self.base_url
        xml_text = await _fetch_text_async(url, params=params, timeout=self.timeout)
        return self._parse_xml(xml_text)

    def _parse_xml(self, xml_text: str) -> list[TorznabRelease]:
        releases: list[TorznabRelease] = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return releases

        for item in root.iter("item"):
            title_el = item.find("title")
            guid_el = item.find("guid")
            link_el = item.find("link")
            comments_el = item.find("comments")
            pub_date_el = item.find("pubDate")
            if title_el is None:
                continue

            size = 0
            seeders = 0
            peers = 0
            infohash = None
            categories: list[int] = []
            for attr in item.findall("torznab:attr", TORZNAB_NS):
                name = attr.get("name")
                value = attr.get("value")
                if name == "size" and value:
                    try:
                        size = int(value)
                    except ValueError:
                        pass
                elif name == "seeders" and value:
                    try:
                        seeders = int(value)
                    except ValueError:
                        pass
                elif name == "peers" and value:
                    try:
                        peers = int(value)
                    except ValueError:
                        pass
                elif name == "infohash" and value:
                    infohash = value
                elif name == "category" and value:
                    try:
                        categories.append(int(value))
                    except ValueError:
                        pass

            guid_text = (guid_el.text if guid_el is not None else "") or ""
            comments_text = comments_el.text if comments_el is not None else None
            page_url = comments_text or (guid_text if guid_text.startswith("http") else None)
            download_url = link_el.text if link_el is not None else None

            # Если размер не найден в атрибутах torznab, проверяем enclosure
            if size == 0:
                enclosure = item.find("enclosure")
                if enclosure is not None and enclosure.get("length"):
                    try:
                        size = int(enclosure.get("length"))
                    except ValueError:
                        pass
                if not download_url and enclosure is not None:
                    download_url = enclosure.get("url")

            releases.append(
                TorznabRelease(
                    title=title_el.text or "",
                    guid=guid_text or download_url or "",
                    download_url=download_url,
                    page_url=page_url,
                    size_bytes=size,
                    seeders=seeders,
                    peers=peers,
                    pub_date=pub_date_el.text if pub_date_el is not None else None,
                    infohash=infohash,
                    categories=categories,
                )
            )
        return releases


class NewznabIndexerClient(BaseIndexerClient):
    """Клиент Newznab для Usenet-индексаторов."""

    async def search(self, query: str, categories: Optional[list[int]] = None) -> list[TorznabRelease]:
        params = {"t": "search", "q": query}
        if self.api_key:
            params["apikey"] = self.api_key
        if categories:
            params["cat"] = ",".join(str(c) for c in categories)

        url = f"{self.base_url}/api" if not self.base_url.endswith("/api") else self.base_url
        xml_text = await _fetch_text_async(url, params=params, timeout=self.timeout)
        return self._parse_xml(xml_text)

    def _parse_xml(self, xml_text: str) -> list[TorznabRelease]:
        releases: list[TorznabRelease] = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return releases

        for item in root.iter("item"):
            title_el = item.find("title")
            guid_el = item.find("guid")
            link_el = item.find("link")
            comments_el = item.find("comments")
            pub_date_el = item.find("pubDate")
            if title_el is None:
                continue

            size = 0
            categories: list[int] = []
            for attr in item.findall("newznab:attr", NEWZNAB_NS):
                name = attr.get("name")
                value = attr.get("value")
                if name == "size" and value:
                    try:
                        size = int(value)
                    except ValueError:
                        pass
                elif name == "category" and value:
                    try:
                        categories.append(int(value))
                    except ValueError:
                        pass

            enclosure = item.find("enclosure")
            download_url = link_el.text if link_el is not None else None
            if enclosure is not None:
                if not download_url:
                    download_url = enclosure.get("url")
                if size == 0 and enclosure.get("length"):
                    try:
                        size = int(enclosure.get("length"))
                    except ValueError:
                        pass

            guid_text = (guid_el.text if guid_el is not None else "") or ""
            page_url = comments_el.text if comments_el is not None else (guid_text if guid_text.startswith("http") else None)

            releases.append(
                TorznabRelease(
                    title=title_el.text or "",
                    guid=guid_text or download_url or "",
                    download_url=download_url,
                    page_url=page_url,
                    size_bytes=size,
                    seeders=100,  # Usenet retention full speed
                    peers=0,
                    pub_date=pub_date_el.text if pub_date_el is not None else None,
                    infohash=None,
                    categories=categories,
                )
            )
        return releases


class NyaaIndexerClient(BaseIndexerClient):
    """Прямой RSS/Search клиент для аниме-трекера Nyaa.si."""

    async def search(self, query: str, categories: Optional[list[int]] = None) -> list[TorznabRelease]:
        base = self.base_url or "https://nyaa.si"
        params = {"page": "rss", "q": query}
        # Категория по умолчанию 1_2 (Anime - English-translated) или 1_0 (Anime all)
        if categories and len(categories) > 0:
            params["c"] = str(categories[0])
        else:
            params["c"] = "0_0"

        xml_text = await _fetch_text_async(base, params=params, timeout=self.timeout)
        return self._parse_nyaa_xml(xml_text)

    def _parse_nyaa_xml(self, xml_text: str) -> list[TorznabRelease]:
        releases: list[TorznabRelease] = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return releases

        for item in root.iter("item"):
            title_el = item.find("title")
            guid_el = item.find("guid")
            link_el = item.find("link")
            pub_date_el = item.find("pubDate")
            if title_el is None:
                continue

            seeders_el = item.find("nyaa:seeders", NYAA_NS)
            leechers_el = item.find("nyaa:leechers", NYAA_NS)
            infohash_el = item.find("nyaa:infoHash", NYAA_NS)
            size_el = item.find("nyaa:size", NYAA_NS)

            seeders = int(seeders_el.text) if seeders_el is not None and seeders_el.text and seeders_el.text.isdigit() else 0
            peers = int(leechers_el.text) if leechers_el is not None and leechers_el.text and leechers_el.text.isdigit() else 0
            infohash = infohash_el.text if infohash_el is not None else None

            # Парсинг размера (напр. "1.4 GiB" или "550.2 MiB")
            size_bytes = 0
            if size_el is not None and size_el.text:
                size_bytes = self._parse_human_size(size_el.text)

            guid_text = (guid_el.text if guid_el is not None else "") or ""
            link_text = link_el.text if link_el is not None else ""

            # У Nyaa: <link> это ссылка на скачивание .torrent, <guid> — страница релиза
            page_url = guid_text if guid_text.startswith("http") else None
            download_url = link_text or guid_text

            releases.append(
                TorznabRelease(
                    title=title_el.text or "",
                    guid=guid_text or download_url,
                    download_url=download_url,
                    page_url=page_url,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    peers=peers,
                    pub_date=pub_date_el.text if pub_date_el is not None else None,
                    infohash=infohash,
                    categories=[5070],  # Anime category ID
                )
            )
        return releases

    @staticmethod
    def _parse_human_size(text: str) -> int:
        match = re.match(r"^([\d.]+)\s*([KMGT]?i?B)$", text.strip(), re.IGNORECASE)
        if not match:
            return 0
        num = float(match.group(1))
        unit = match.group(2).upper()
        multipliers = {
            "B": 1,
            "KB": 1024, "KIB": 1024,
            "MB": 1024**2, "MIB": 1024**2,
            "GB": 1024**3, "GIB": 1024**3,
            "TB": 1024**4, "TIB": 1024**4,
        }
        return int(num * multipliers.get(unit, 1))


class TorrentRssIndexerClient(BaseIndexerClient):
    """Универсальный парсер стандартных Torrent RSS-лент."""

    async def search(self, query: str, categories: Optional[list[int]] = None) -> list[TorznabRelease]:
        url = self.base_url
        if self.api_key and "passkey=" not in url and "apikey=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}passkey={self.api_key}"

        xml_text = await _fetch_text_async(url, timeout=self.timeout)
        releases = self._parse_rss(xml_text)

        # Фильтруем по запросу, если передан (для ручного поиска)
        if query and query.strip().lower() != "test":
            q_terms = [t.lower() for t in query.split() if len(t) > 1]
            if q_terms:
                releases = [r for r in releases if any(term in r.title.lower() for term in q_terms)]
        return releases

    def _parse_rss(self, xml_text: str) -> list[TorznabRelease]:
        releases: list[TorznabRelease] = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return releases

        for item in root.iter("item"):
            title_el = item.find("title")
            guid_el = item.find("guid")
            link_el = item.find("link")
            comments_el = item.find("comments")
            pub_date_el = item.find("pubDate")
            enclosure = item.find("enclosure")
            if title_el is None:
                continue

            download_url = None
            size_bytes = 0
            if enclosure is not None:
                download_url = enclosure.get("url")
                if enclosure.get("length"):
                    try:
                        size_bytes = int(enclosure.get("length"))
                    except ValueError:
                        pass

            if not download_url and link_el is not None:
                download_url = link_el.text

            guid_text = (guid_el.text if guid_el is not None else "") or download_url or ""
            page_url = comments_el.text if comments_el is not None else (guid_text if guid_text.startswith("http") else None)

            releases.append(
                TorznabRelease(
                    title=title_el.text or "",
                    guid=guid_text,
                    download_url=download_url,
                    page_url=page_url,
                    size_bytes=size_bytes,
                    seeders=1,
                    peers=0,
                    pub_date=pub_date_el.text if pub_date_el is not None else None,
                    infohash=None,
                    categories=[],
                )
            )
        return releases


class IPTorrentsIndexerClient(TorrentRssIndexerClient):
    """Клиент для RSS-фида IPTorrents."""
    pass


class TorrentLeechIndexerClient(TorrentRssIndexerClient):
    """Клиент для RSS-фида TorrentLeech."""
    pass


def get_indexer_client(indexer_row) -> BaseIndexerClient:
    """Фабрика создания подходящего клиента индексатора по его типу."""
    itype = str(getattr(indexer_row, "type", "torznab")).lower()
    base_url = getattr(indexer_row, "base_url", "")
    api_key = getattr(indexer_row, "api_key", None)
    timeout = getattr(indexer_row, "timeout_seconds", 30)

    if itype == "torznab":
        return TorznabIndexerClient(base_url=base_url, api_key=api_key, timeout=timeout)
    elif itype == "newznab":
        return NewznabIndexerClient(base_url=base_url, api_key=api_key, timeout=timeout)
    elif itype == "nyaa":
        return NyaaIndexerClient(base_url=base_url, api_key=api_key, timeout=timeout)
    elif itype == "torrent_rss":
        return TorrentRssIndexerClient(base_url=base_url, api_key=api_key, timeout=timeout)
    elif itype == "iptorrents":
        return IPTorrentsIndexerClient(base_url=base_url, api_key=api_key, timeout=timeout)
    elif itype == "torrentleech":
        return TorrentLeechIndexerClient(base_url=base_url, api_key=api_key, timeout=timeout)
    return TorznabIndexerClient(base_url=base_url, api_key=api_key, timeout=timeout)
