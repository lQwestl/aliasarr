#!/usr/bin/env python3
"""
Скрипт автоматического сбора и анализа заголовков раздач из Jackett / Prowlarr.

Использование:
  1. Автоматически из базы данных Aliasarr (берет настроенные индексаторы и тайтлы):
     python3 scripts/harvest_jackett_titles.py

  2. Напрямую с параметрами Jackett:
     python3 scripts/harvest_jackett_titles.py --jackett-url http://localhost:9117 --api-key YOUR_API_KEY --preset anime

  3. По списку собственных запросов:
     python3 scripts/harvest_jackett_titles.py --jackett-url http://localhost:9117 --api-key YOUR_API_KEY --query "Re:Zero, Bleach, Клеватесс"

Результат сохраняется в jackett_titles_dump.json с полным отчётом о качестве распознавания.
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

# Добавляем корень проекта в sys.path для импорта сервисов Aliasarr
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from app.services.parser import parse_episode, detect_season_label, ReleaseKind
    from app.services.matcher import is_non_video_release
    ALIASARR_SERVICES_AVAILABLE = True
except Exception:
    ALIASARR_SERVICES_AVAILABLE = False


PRESET_ANIME = [
    "Re:Zero",
    "Клеватесс",
    "Табакошка",
    "Цугаи загробного мира",
    "Bleach",
    "Attack on Titan",
    "Mushoku Tensei",
    "Jujutsu Kaisen",
    "Sousou no Frieren",
    "Kimetsu no Yaiba",
    "Solo Leveling",
    "Oshi no Ko",
    "Chainsaw Man",
    "Vinland Saga",
    "Spy x Family",
    "One Piece",
    "Naruto",
    "Death Note",
    "Fate/stay night",
    "Monogatari",
    "Gintama",
    "Boku no Hero Academia",
    "Dungeon Meshi",
    "Hunter x Hunter",
    "Fullmetal Alchemist",
    "Overlord",
    "Konosuba",
    "Kaguya-sama",
    "Steins;Gate",
    "Code Geass",
]

PRESET_SERIES = [
    "Breaking Bad",
    "Game of Thrones",
    "The Boys",
    "House of the Dragon",
    "Stranger Things",
    "Fargo",
    "True Detective",
    "The Last of Us",
    "Severance",
    "Shogun",
    "Fallout",
    "Avatar: The Last Airbender",
    "Better Call Saul",
    "Dark",
    "Sherlock",
    "Peaky Blinders",
    "The Mandalorian",
    "Loki",
    "Succession",
    "The Witcher",
]


def fetch_torznab(base_url: str, api_key: str, query: str, timeout: int = 15) -> list[dict]:
    """Выполняет поиск через Torznab API (Jackett / Prowlarr) и возвращает список раздач."""
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/api") and "/torznab/" not in base_url:
        endpoint = f"{base_url}/torznab/all/api"
    else:
        endpoint = base_url

    params = {
        "t": "search",
        "q": query,
        "apikey": api_key,
    }
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Aliasarr-TitleHarvester/1.0"}
    )

    results = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            root = ET.fromstring(content)
            
            for item in root.findall("./channel/item"):
                title_elem = item.find("title")
                title = title_elem.text if title_elem is not None else ""
                
                size_elem = item.find("size")
                size = int(size_elem.text) if size_elem is not None and size_elem.text.isdigit() else 0
                
                cat_elems = item.findall("./category")
                cats = [c.text for c in cat_elems if c.text]

                for attr in item.findall("{http://torznab.com/schemas/2015/feed}attr"):
                    if attr.get("name") == "size" and not size:
                        try:
                            size = int(attr.get("value", 0))
                        except Exception:
                            pass
                    if attr.get("name") == "category":
                        cats.append(attr.get("value"))

                if title:
                    results.append({
                        "title": title.strip(),
                        "size_bytes": size,
                        "categories": cats,
                        "query": query,
                    })
    except Exception as exc:
        print(f"  [Ошибка Torznab '{query}']: {exc}")

    return results


def fetch_jackett_json_api(base_url: str, api_key: str, query: str, timeout: int = 15) -> list[dict]:
    """Выполняет поиск через нативный Jackett JSON API v2.0."""
    base_url = base_url.rstrip("/")
    endpoint = f"{base_url}/api/v2.0/indexers/all/results"
    params = {
        "apikey": api_key,
        "Query": query,
    }
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Aliasarr-TitleHarvester/1.0", "Accept": "application/json"}
    )
    results = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("Results", [])
            for item in items:
                title = item.get("Title", "")
                size = item.get("Size", 0)
                cats = item.get("CategoryDesc", [])
                indexer = item.get("Tracker", "")
                if title:
                    results.append({
                        "title": title.strip(),
                        "size_bytes": size,
                        "categories": cats,
                        "indexer": indexer,
                        "query": query,
                    })
    except Exception:
        return fetch_torznab(base_url, api_key, query, timeout=timeout)

    return results


def load_from_db():
    """Загружает индексаторы и тайтлы из локальной БД Aliasarr."""
    try:
        from app.core.database import SessionLocal
        from app.models.db import Indexer, Show
        db = SessionLocal()
        indexers = db.query(Indexer).filter_by(enabled=True).all()
        shows = db.query(Show).all()
        return indexers, shows
    except Exception as exc:
        return [], []


def analyze_titles(records: list[dict]) -> dict:
    """Анализирует все собранные заголовки через парсер и матчер Aliasarr."""
    if not ALIASARR_SERVICES_AVAILABLE:
        return {"error": "Aliasarr services not available for local analysis"}

    total = len(records)
    parsed_ok = 0
    season_pack = 0
    episode_range = 0
    single_episode = 0
    absolute_anime = 0
    non_video_count = 0
    multi_part_count = 0
    unknown_titles = []

    seen_titles = set()
    deduped_records = []

    for r in records:
        t = r["title"]
        if t in seen_titles:
            continue
        seen_titles.add(t)
        deduped_records.append(r)

        is_nv = is_non_video_release(t)
        if is_nv:
            non_video_count += 1
            r["analysis"] = {"kind": "non_video", "filtered": True}
            continue

        p = parse_episode(t)
        s_lbl = detect_season_label(t)

        info = {
            "kind": p.kind.value,
            "season": p.season,
            "episodes": p.episodes,
            "part": p.part,
            "season_label": s_lbl,
        }
        r["analysis"] = info

        if p.part and p.part >= 2:
            multi_part_count += 1

        if p.kind == ReleaseKind.SEASON_PACK:
            season_pack += 1
            parsed_ok += 1
        elif p.kind == ReleaseKind.EPISODE:
            if p.is_range or len(p.episodes) > 1:
                episode_range += 1
            else:
                single_episode += 1
            parsed_ok += 1
        elif p.kind == ReleaseKind.ABSOLUTE:
            absolute_anime += 1
            parsed_ok += 1
        elif s_lbl.get("type") in ("numbered", "range", "complete", "final"):
            parsed_ok += 1
        else:
            unknown_titles.append(t)

    video_total = len(deduped_records) - non_video_count
    accuracy = (parsed_ok / video_total * 100) if video_total > 0 else 100.0

    return {
        "total_fetched": total,
        "unique_titles": len(deduped_records),
        "video_titles": video_total,
        "non_video_filtered": non_video_count,
        "multi_part_detected": multi_part_count,
        "parsed_success": parsed_ok,
        "parsing_accuracy_pct": round(accuracy, 2),
        "season_packs": season_pack,
        "episode_ranges": episode_range,
        "single_episodes": single_episode,
        "absolute_episodes": absolute_anime,
        "unknown_sample": unknown_titles[:30],
        "unknown_total": len(unknown_titles),
    }


def main():
    parser = argparse.ArgumentParser(description="Сбор и анализ заголовков раздач из Jackett/Prowlarr")
    parser.add_argument("--jackett-url", help="URL Jackett (напр. http://localhost:9117)")
    parser.add_argument("--api-key", help="API ключ Jackett")
    parser.add_argument("--preset", choices=["anime", "series", "all", "db"], default="anime", help="Набор запросов")
    parser.add_argument("--query", help="Свои поисковые запросы через запятую")
    parser.add_argument("--output", default="jackett_titles_dump.json", help="Файл для сохранения результата")
    parser.add_argument("--threads", type=int, default=6, help="Количество параллельных потоков")
    args = parser.parse_args()

    jackett_url = args.jackett_url
    api_key = args.api_key
    queries = []

    if not jackett_url or not api_key:
        print("[*] Попытка загрузить настройки индексаторов из базы данных Aliasarr...")
        indexers, shows = load_from_db()
        if indexers:
            jackett_url = indexers[0].base_url
            api_key = indexers[0].api_key
            print(f"[+] Найден индексатор: {indexers[0].name} ({jackett_url})")
            if args.preset == "db" and shows:
                queries = [s.title for s in shows]
        else:
            print("[-] Индексаторы в БД не найдены. Укажите --jackett-url и --api-key.")
            if not jackett_url or not api_key:
                sys.exit(1)

    if args.query:
        queries = [q.strip() for q in args.query.split(",") if q.strip()]
    elif not queries:
        if args.preset == "anime":
            queries = PRESET_ANIME
        elif args.preset == "series":
            queries = PRESET_SERIES
        elif args.preset == "all":
            queries = PRESET_ANIME + PRESET_SERIES

    print("\n=======================================================")
    print(f" Сбор заголовков из Jackett ({jackett_url})")
    print(f" Запросов: {len(queries)} | Потоков: {args.threads}")
    print("=======================================================\n")

    all_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {
            executor.submit(fetch_jackett_json_api, jackett_url, api_key, q): q
            for q in queries
        }
        done_count = 0
        for future in concurrent.futures.as_completed(futures):
            q = futures[future]
            done_count += 1
            try:
                res = future.result()
                all_results.extend(res)
                print(f"[{done_count}/{len(queries)}] Запрос '{q}': получено {len(res)} раздач")
            except Exception as exc:
                print(f"[{done_count}/{len(queries)}] Запрос '{q}': ошибка {exc}")

    print(f"\n[+] Всего собрано заголовков: {len(all_results)}")
    print("[*] Анализ через парсер и матчер Aliasarr...")

    stats = analyze_titles(all_results)

    output_data = {
        "stats": stats,
        "records": all_results,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"[+] Результаты сохранены в файл: {args.output}\n")
    print("================ ИТОГОВЫЙ ОТЧЁТ ================")
    print(f" Уникальных заголовков:   {stats.get('unique_titles')}")
    print(f" Не-видео (отфильтровано): {stats.get('non_video_filtered')} (саундтреки, манга, аудиокниги, игры)")
    print(f" Видео-релизов:           {stats.get('video_titles')}")
    print(f" Успешно распознано:      {stats.get('parsed_success')} ({stats.get('parsing_accuracy_pct')}%)")
    print(f"   - Сезон-паки:          {stats.get('season_packs')}")
    print(f"   - Диапазоны серий:     {stats.get('episode_ranges')}")
    print(f"   - Одиночные серии:     {stats.get('single_episodes')}")
    print(f"   - Аниме абсолютные:    {stats.get('absolute_episodes')}")
    print(f"   - Multi-Part (куры):   {stats.get('multi_part_detected')}")
    print(f" Нераспознано / Прочие:   {stats.get('unknown_total')}")
    print("================================================")

    if stats.get("unknown_sample"):
        print("\nПримеры нераспознанных названий для дообучения:")
        for idx, unk in enumerate(stats["unknown_sample"][:10], 1):
            print(f"  {idx}. {unk}")


if __name__ == "__main__":
    main()
