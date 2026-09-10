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

    # Лестница эскалации задержек в секундах (соответствует Sonarr EscalationBackOff.Periods)
    # [0с, 1мин, 5мин, 15мин, 30мин, 1час, 3часа, 6часов, 12часов, 24часа]
    ESCALATION_PERIODS = [
        0,
        60,
        5 * 60,
        15 * 60,
        30 * 60,
        60 * 60,
        3 * 60 * 60,
        6 * 60 * 60,
        12 * 60 * 60,
        24 * 60 * 60,
    ]

    def __init__(self):
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._last_request_times: dict[str, float] = {}
        self._disabled_until: dict[str, float] = {}
        self._escalation_levels: dict[str, int] = {}
        self._init_lock = asyncio.Lock()

    @staticmethod
    def extract_host(url_or_key: str) -> str:
        """Извлекает нормализованное имя хоста с портом из URL или строки-ключа."""
        if not url_or_key:
            return "unknown_host"
        url_str = str(url_or_key).strip()
        if url_str.startswith(("http://", "https://", "ftp://")):
            try:
                parsed = urllib.parse.urlparse(url_str)
                return (parsed.netloc or parsed.path or url_str).lower()
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

    async def acquire(self, host_or_key: str, min_interval_seconds: float = 2.0) -> None:
        """Ожидает своей очереди и выдерживает межзапросный интервал к заданному хосту.
        Если хост заблокирован по 429, выбрасывает RateLimitExceededError.
        """
        host = self.extract_host(host_or_key)

        # 1. Проверяем блокировку перед взятием лока
        blocked, remaining = self.is_blocked(host)
        if blocked:
            raise RateLimitExceededError(host=host, retry_after=remaining)

        lock = await self._get_host_lock(host)
        async with lock:
            # 2. Повторная проверка блокировки после взятия лока
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
        и активирует кулдаун для данного хоста.
        """
        host = self.extract_host(host_or_key)
        now = time.monotonic()

        current_level = self._escalation_levels.get(host, 0)
        next_level = min(len(self.ESCALATION_PERIODS) - 1, current_level + 1)
        self._escalation_levels[host] = next_level

        if retry_after is not None and retry_after > 0:
            backoff = float(retry_after)
        else:
            backoff = float(self.ESCALATION_PERIODS[next_level] if next_level > 0 else 60)

        self._disabled_until[host] = now + backoff
        logger.warning(
            "Превышен лимит запросов (HTTP 429) для хоста '%s'. Запросы приостановлены на %.1f сек (уровень эскалации: %d)",
            host, backoff, next_level,
        )
        return backoff

    def record_success(self, host_or_key: str) -> None:
        """Регистрирует успешный ответ от хоста, постепенно снижая уровень эскалации."""
        host = self.extract_host(host_or_key)

        # Очищаем блокировку, если истекла
        disabled_time = self._disabled_until.get(host)
        if disabled_time is not None and time.monotonic() >= disabled_time:
            self._disabled_until.pop(host, None)

        cur_level = self._escalation_levels.get(host, 0)
        if cur_level > 0:
            self._escalation_levels[host] = cur_level - 1

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
