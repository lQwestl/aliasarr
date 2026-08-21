"""
Простой клиент Torznab (используется Jackett, Prowlarr и напрямую трекерами
с Torznab-совместимым API).

Формирует запрос вида:
  {base_url}/api?apikey={key}&t=search&q={query}&cat={categories}

и парсит RSS/XML ответ в список releases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree

try:
    import httpx
except ImportError:
    httpx = None

TORZNAB_NS = {"torznab": "http://torznab.com/schemas/2015/feed"}


@dataclass
class TorznabRelease:
    title: str
    guid: str
    download_url: Optional[str]     # прямая ссылка на .torrent для загрузчика
    page_url: Optional[str] = None  # ссылка на страницу темы/раздачи на трекере
    size_bytes: int = 0
    seeders: int = 0
    peers: int = 0
    pub_date: Optional[str] = None
    infohash: Optional[str] = None
    categories: list[int] = None


class TorznabClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def search(self, query: str, categories: Optional[list[int]] = None) -> list[TorznabRelease]:
        params = {"t": "search", "q": query}
        if self.api_key:
            params["apikey"] = self.api_key
        if categories:
            params["cat"] = ",".join(str(c) for c in categories)

        url = f"{self.base_url}/api"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return self._parse_response(resp.text)

    def _parse_response(self, xml_text: str) -> list[TorznabRelease]:
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
                    size = int(value)
                elif name == "seeders" and value:
                    seeders = int(value)
                elif name == "peers" and value:
                    peers = int(value)
                elif name == "infohash" and value:
                    infohash = value
                elif name == "category" and value:
                    try:
                        categories.append(int(value))
                    except ValueError:
                        pass

            # Ссылка на страницу раздачи на трекере (тег <comments> или guid)
            guid_text = (guid_el.text if guid_el is not None else "") or ""
            comments_text = comments_el.text if comments_el is not None else None
            page_url = comments_text or (guid_text if guid_text.startswith("http") else None)

            releases.append(
                TorznabRelease(
                    title=title_el.text or "",
                    guid=guid_text or (link_el.text if link_el is not None else ""),
                    download_url=link_el.text if link_el is not None else None,
                    page_url=page_url,
                    size_bytes=size,
                    seeders=seeders,
                    peers=peers,
                    infohash=infohash,
                    categories=categories,
                )
            )
        return releases
