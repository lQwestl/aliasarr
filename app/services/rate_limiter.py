"""Модуль централизованного контроля частоты запросов и обработки HTTP 429 (Rate Limiter).
Реализует архитектурные принципы Sonarr (RateLimitService + ProviderStatusService + EscalationBackOff):
1. Межзапросные паузы per-host (по умолчанию 2.0 секунды на хост).
2. Обработка заголовка Retry-After (целые секунды и RFC 2822 / HTTP-Date).
3. Лестница эскалации кулдауна при повторных ошибках 429 (EscalationBackOff).
4. Автоматическое восстановление статуса хоста при успешных ответах.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import email.utils
import logging
import re
import time
import urllib.parse
from typing import Optional

logger = logging.getLogger("aliasarr.rate_limiter")


class RateLimitExceededError(Exception):
    """Исключение, выбрасываемое при превышении лимита запросов (HTTP 429) или попытке обращения к заблокированному хосту."""

    def __init__(self, host: str, retry_after: float, message: Optional[str] = None):
        self.host = host
        self.retry_after = round(max(1.0, float(retry_after)), 1)
        self.status_code = 429
        default_msg = f"Хост '{host}' превысил лимит запросов (HTTP 429). Запросы приостановлены на {self.retry_after}с"
        super().__init__(message or default_msg)


class AsyncRateLimiter:
    """Асинхронный менеджер частоты запросов и статуса доступности внешних хостов/индексаторов."""

    # Лестница эскалации задержек в секундах (соответствует стандарту Sonarr/Radarr):
    # 1-я ошибка: 1мин, 2-я: 5мин, 3-я: 15мин, 4-я: 30мин (максимум)
    ESCALATION_PERIODS = [
        0,
        60,          # 1 мин
        5 * 60,      # 5 мин
        15 * 60,     # 15 мин
        30 * 60,     # 30 мин (максимальный потолок)
    ]
    MAX_BACKOFF_CAP: float = 30 * 60.0  # 1800с (30 минут)

    def __init__(self):
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._last_request_times: dict[str, float] = {}
        self._disabled_until: dict[str, float] = {}
        self._escalation_levels: dict[str, int] = {}
        self._init_lock = asyncio.Lock()

    @staticmethod
    def extract_host(url_or_key: str) -> str:
        """Извлекает нормализованный ключ хоста/индексатора из URL или строки-ключа.
        Для прокси-серверов (Prowlarr, Jackett) сохраняет уникальный путь трекера (например, 'prowlarr:9696/1' или 'jackett:9117/api/v2.0/indexers/rutracker'),
        чтобы блокировка одного трекера не распространялась на остальные.
        """
        if not url_or_key:
            return "unknown_host"
        url_str = str(url_or_key).strip()
        if url_str.startswith(("http://", "https://", "ftp://")):
            try:
                parsed = urllib.parse.urlparse(url_str)
                netloc = (parsed.netloc or "").lower()
                path = (parsed.path or "").rstrip("/")
                clean_path = path
                for _ in range(2):
                    clean_path = re.sub(r"/(?:api|results/torznab)(?:/)?$", "", clean_path, flags=re.IGNORECASE).rstrip("/")
                if clean_path and clean_path not in ("", "/api"):
                    return f"{netloc}{clean_path}".lower()
                return (netloc or parsed.path or url_str).lower()
            except Exception:
                pass
        return url_str.lower().rstrip("/")

    @staticmethod
    def parse_retry_after(header_value: Optional[str]) -> Optional[float]:
        """Парсит заголовок HTTP Retry-After (в секундах или формате RFC 2822 / HTTP-date)."""
        if not header_value:
            return None

        val_str = str(header_value).strip()
        if not val_str:
            return None

        # 1. Формат целых/дробных секунд (например "60" или "120")
        try:
            sec = float(val_str)
            return max(1.0, sec)
        except ValueError:
            pass

        # 2. Формат даты HTTP-date (например "Wed, 21 Oct 2026 07:28:00 GMT")
        try:
            parsed_dt = email.utils.parsedate_to_datetime(val_str)
            if parsed_dt is not None:
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=dt.timezone.utc)
                now = dt.datetime.now(dt.timezone.utc)
                delta = (parsed_dt - now).total_seconds()
                return max(1.0, delta)
        except Exception:
            pass

        return None

    def is_blocked(self, host_or_key: str) -> tuple[bool, float]:
        """Проверяет, находится ли хост в режиме временной блокировки/кулдауна.
        Возвращает (is_blocked, remaining_seconds).
        """
        host = self.extract_host(host_or_key)
        disabled_time = self._disabled_until.get(host)
        if disabled_time is None:
            return False, 0.0

        now = time.monotonic()
        remaining = disabled_time - now
        if remaining > 0.0:
            return True, round(remaining, 1)

        # Кулдаун истек — очищаем запись блокировки
        self._disabled_until.pop(host, None)
        return False, 0.0

    async def _get_host_lock(self, host: str) -> asyncio.Lock:
        if host not in self._host_locks:
            async with self._init_lock:
                if host not in self._host_locks:
                    self._host_locks[host] = asyncio.Lock()
        return self._host_locks[host]

    async def acquire(self, host_or_key: str, min_interval_seconds: float = 2.0, is_probe: bool = False) -> None:
        """Ожидает своей очереди и выдерживает межзапросный интервал к заданному хосту.
        Если хост заблокирован по 429 и is_probe=False, выбрасывает RateLimitExceededError.
        Если is_probe=True (фоновый Health Check), запрос пропускается для проверки доступности.
        """
        host = self.extract_host(host_or_key)

        # 1. Проверяем блокировку перед взятием лока (для обычных запросов)
        if not is_probe:
            blocked, remaining = self.is_blocked(host)
            if blocked:
                raise RateLimitExceededError(host=host, retry_after=remaining)

        lock = await self._get_host_lock(host)
        async with lock:
            # 2. Повторная проверка блокировки после взятия лока
            if not is_probe:
                blocked, remaining = self.is_blocked(host)
                if blocked:
                    raise RateLimitExceededError(host=host, retry_after=remaining)

            now = time.monotonic()
            last_time = self._last_request_times.get(host, 0.0)
            elapsed = now - last_time

            if min_interval_seconds > 0.0 and elapsed < min_interval_seconds:
                delay = min_interval_seconds - elapsed
                logger.debug("Rate Limit: задержка к '%s' на %.3f сек", host, delay)
                await asyncio.sleep(delay)

            self._last_request_times[host] = time.monotonic()

    def record_429(self, host_or_key: str, retry_after: Optional[float] = None) -> float:
        """Регистрирует получение ответа HTTP 429 от хоста, вычисляет длительность паузы
        (ограниченную потолком MAX_BACKOFF_CAP = 30 минут) и активирует кулдаун для данного хоста.
        """
        host = self.extract_host(host_or_key)
        now = time.monotonic()

        current_level = self._escalation_levels.get(host, 0)
        next_level = min(len(self.ESCALATION_PERIODS) - 1, current_level + 1)
        self._escalation_levels[host] = next_level

        if retry_after is not None and retry_after > 0:
            backoff = min(float(retry_after), self.MAX_BACKOFF_CAP)
        else:
            backoff = float(self.ESCALATION_PERIODS[next_level] if next_level > 0 else 60)

        self._disabled_until[host] = now + backoff
        logger.warning(
            "Превышен лимит запросов (HTTP 429) для хоста '%s'. Запросы приостановлены на %.1f сек (уровень эскалации: %d)",
            host, backoff, next_level,
        )
        return backoff

    def record_success(self, host_or_key: str) -> None:
        """Регистрирует успешный ответ от хоста, немедленно снимая блокировку и сбрасывая эскалацию."""
        host = self.extract_host(host_or_key)
        self._disabled_until.pop(host, None)
        self._escalation_levels[host] = 0

    def reset(self, host_or_key: Optional[str] = None) -> None:
        """Сбрасывает состояние rate limiter для конкретного хоста или для всех хостов (для тестов)."""
        if host_or_key:
            host = self.extract_host(host_or_key)
            self._disabled_until.pop(host, None)
            self._escalation_levels.pop(host, None)
            self._last_request_times.pop(host, None)
        else:
            self._disabled_until.clear()
            self._escalation_levels.clear()
            self._last_request_times.clear()
            self._host_locks.clear()


_global_rate_limiter: Optional[AsyncRateLimiter] = None


def get_rate_limiter() -> AsyncRateLimiter:
    """Возвращает глобальный экземпляр AsyncRateLimiter."""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = AsyncRateLimiter()
    return _global_rate_limiter
