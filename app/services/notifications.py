"""Отправка уведомлений о событиях (grab/import/health) в различные каналы:
Telegram, Discord, Gotify, Ntfy, Pushover, Slack, Webhook.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Optional, Any

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger("aliasarr.notifications")


def _strip_html(text: str) -> str:
    """Удаляет все HTML-теги, оставляя чистый текст."""
    if not text:
        return ""
    clean = re.sub(r"<a\s+(?:[^>]*?\s+)?href=([\"'])(.*?)\1[^>]*>(.*?)</a>", r"\3 (\2)", text, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", "", clean)
    return clean.strip()


def _html_to_markdown(text: str) -> str:
    """Преобразует базовую HTML-разметку в Markdown для Discord / Gotify / Ntfy."""
    if not text:
        return ""
    res = text
    # Ссылки <a href="url">text</a> -> [text](url)
    res = re.sub(r"<a\s+(?:[^>]*?\s+)?href=([\"'])(.*?)\1[^>]*>(.*?)</a>", r"[\3](\2)", res, flags=re.IGNORECASE)
    # Жирный шрифт
    res = re.sub(r"<(?:b|strong)>(.*?)</(?:b|strong)>", r"**\1**", res, flags=re.IGNORECASE)
    # Курсив
    res = re.sub(r"<(?:i|em)>(.*?)</(?:i|em)>", r"*\1*", res, flags=re.IGNORECASE)
    # Код
    res = re.sub(r"<code>(.*?)</code>", r"`\1`", res, flags=re.IGNORECASE)
    # Удаляем оставшиеся HTML-теги
    res = re.sub(r"<[^>]+>", "", res)
    return res.strip()


def _html_to_slack_mrkdwn(text: str) -> str:
    """Преобразует HTML-разметку в Slack mrkdwn."""
    if not text:
        return ""
    res = text
    # Жирный шрифт в Slack это *text*
    res = re.sub(r"<(?:b|strong)>(.*?)</(?:b|strong)>", r"*\1*", res, flags=re.IGNORECASE)
    # Курсив в Slack это _text_
    res = re.sub(r"<(?:i|em)>(.*?)</(?:i|em)>", r"_\1_", res, flags=re.IGNORECASE)
    # Код
    res = re.sub(r"<code>(.*?)</code>", r"`\1`", res, flags=re.IGNORECASE)
    # Ссылки <a href="url">text</a> -> <url|text>
    res = re.sub(r"<a\s+(?:[^>]*?\s+)?href=([\"'])(.*?)\1[^>]*>(.*?)</a>", r"<\g<2>|\g<3>>", res, flags=re.IGNORECASE)
    # Удаляем только оставшиеся HTML теги (не трогая Slack <url|text>)
    res = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s+[^>]*)?>", "", res)
    return res.strip()


def format_notification_message(message: str, lang: str = "ru") -> str:
    """Переводит сообщение уведомления на английский язык, если в настройках выбран 'en'."""
    if not message or lang != "en":
        return message

    text = str(message)
    # Test notifications
    text = text.replace("🔔 Тестовое уведомление от Aliasarr — всё работает!", "🔔 Test notification from Aliasarr — everything works!")

    # Grab notifications
    text = text.replace("Обнаружено лучшее качество и начато скачивание для", "Better quality detected and download started for")
    text = text.replace("Захвачен релиз для", "Grabbed release for")
    text = text.replace(", сиды:", ", seeds:")

    # Import notifications
    text = text.replace("Релиз скачан и произведена замена старого на новый:", "Release downloaded and upgraded (replaced previous):")
    text = text.replace("Релиз скачан и перенесен:", "Release downloaded and imported:")
    text = text.replace("Файл импортирован:", "File imported:")
    text = text.replace("\nФайл:", "\nFile:")
    text = text.replace("\nФайлы:", "\nFiles:")
    text = text.replace("• ...и ещё ", "• ...and ")
    text = text.replace(" файлов", " more files")

    # Backup notifications
    text = text.replace("📦 Создана резервная копия Aliasarr:", "📦 Aliasarr backup created:")
    text = text.replace("Создан бэкап", "Backup created")
    text = text.replace("Размер:", "Size:")

    # Series & File notifications
    text = text.replace("🎬 В библиотеку добавлен тайтл:", "🎬 Title added to library:")
    text = text.replace("🗑 Удалён тайтл «", "🗑 Deleted title '").replace("🗑 Удален тайтл «", "🗑 Deleted title '")
    text = text.replace("🗑 Удалена карточка тайтла «", "🗑 Deleted title card '").replace("🗑 Удалена карточка «", "🗑 Deleted card '")
    text = text.replace("» (вместе с файлами на диске)", "' (along with files on disk)").replace(" (вместе с файлами на диске)", " (along with files on disk)")
    text = text.replace("» (файлы сохранены на диске)", "' (files kept on disk)").replace(" (файлы сохранены)", " (files kept)")
    text = text.replace("»", "'")
    text = text.replace("🗑 Удалён файл для", "🗑 Deleted file for").replace("🗑 Удален файл для", "🗑 Deleted file for")
    text = text.replace("✏️ Переименован файл для", "✏️ Renamed file for")

    return text


def _apply_title(settings: dict, message: str) -> str:
    """Галочка "Включить Aliasarr в заголовок" — добавляет префикс приложения к тексту."""
    if settings.get("include_app_name"):
        return f"Aliasarr: {message}"
    return message


# -----------------------------------------------------------------------------
# Провайдеры отправки уведомлений
# -----------------------------------------------------------------------------

async def _send_telegram(settings: dict, message: str, event_type: str = "general") -> None:
    bot_token = settings.get("bot_token")
    chat_id = settings.get("chat_id")
    if not bot_token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": _apply_title(settings, message),
        "parse_mode": "HTML",
        "disable_web_page_preview": not bool(settings.get("link_preview", False)),
    }

    message_thread_id = settings.get("message_thread_id") or settings.get("topic_id")
    if message_thread_id:
        try:
            payload["message_thread_id"] = int(message_thread_id)
        except (ValueError, TypeError):
            pass

    if settings.get("silent"):
        payload["disable_notification"] = True

    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


async def _send_discord(settings: dict, message: str, event_type: str = "general") -> None:
    webhook_url = settings.get("webhook_url")
    if not webhook_url:
        return

    # Цветовая кодировка embed
    color_map = {
        "import": 0x2ECC71,  # Зелёный
        "grab": 0x3498DB,    # Синий
        "health": 0xE74C3C,  # Красный
        "test": 0x9B59B6,    # Фиолетовый
    }
    color = color_map.get(event_type, 0x1ABC9C)

    event_titles = {
        "import": "Файл скачан и импортирован",
        "grab": "Захвачен новый релиз",
        "health": "Внимание: Проблема системы",
        "test": "Тестовое уведомление",
    }
    title = event_titles.get(event_type, "Уведомление")
    if settings.get("include_app_name"):
        title = f"Aliasarr • {title}"

    embed = {
        "title": title,
        "description": _html_to_markdown(message),
        "color": color,
        "footer": {"text": "Aliasarr"},
        "timestamp": dt.datetime.utcnow().isoformat(),
    }

    payload: dict[str, Any] = {
        "username": settings.get("username") or "Aliasarr",
        "embeds": [embed],
    }
    if settings.get("avatar_url"):
        payload["avatar_url"] = settings["avatar_url"]

    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()


async def _send_gotify(settings: dict, message: str, event_type: str = "general") -> None:
    server_url = (settings.get("server_url") or "").rstrip("/")
    app_token = settings.get("app_token")
    if not server_url or not app_token:
        return

    default_priority = 5
    if event_type == "health":
        default_priority = 8
    try:
        priority = int(settings.get("priority", default_priority))
    except (ValueError, TypeError):
        priority = default_priority

    title = "Aliasarr" if settings.get("include_app_name") else event_type.capitalize()
    payload = {
        "title": title,
        "message": _strip_html(message),
        "priority": priority,
        "extras": {
            "client::display": {
                "contentType": "text/plain"
            }
        },
    }

    url = f"{server_url}/message"
    headers = {"X-Gotify-Key": app_token}

    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()


async def _send_ntfy(settings: dict, message: str, event_type: str = "general") -> None:
    server_url = (settings.get("server_url") or "https://ntfy.sh").rstrip("/")
    topic = (settings.get("topic") or "").strip().lstrip("/")
    if not topic:
        return

    url = f"{server_url}/{topic}"
    headers: dict[str, str] = {
        "Title": "Aliasarr" if settings.get("include_app_name") else event_type.capitalize(),
        "Priority": str(settings.get("priority") or ("4" if event_type == "health" else "3")),
    }

    if settings.get("access_token"):
        headers["Authorization"] = f"Bearer {settings['access_token']}"

    tags = settings.get("tags")
    if not tags:
        tag_map = {"import": "arrow_down,film_projector", "grab": "magnet", "health": "warning", "test": "bell"}
        tags = tag_map.get(event_type, "bell")
    headers["Tags"] = tags

    body = _strip_html(message)

    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, content=body.encode("utf-8"))
        resp.raise_for_status()


async def _send_pushover(settings: dict, message: str, event_type: str = "general") -> None:
    user_key = settings.get("user_key")
    api_token = settings.get("api_token")
    if not user_key or not api_token:
        return

    url = "https://api.pushover.net/1/messages.json"
    try:
        priority = int(settings.get("priority", 0))
    except (ValueError, TypeError):
        priority = 0

    data: dict[str, Any] = {
        "token": api_token,
        "user": user_key,
        "title": "Aliasarr" if settings.get("include_app_name") else event_type.capitalize(),
        "message": message,
        "html": 1,
        "priority": priority,
    }
    if settings.get("sound"):
        data["sound"] = settings["sound"]

    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, data=data)
        resp.raise_for_status()


async def _send_slack(settings: dict, message: str, event_type: str = "general") -> None:
    webhook_url = settings.get("webhook_url")
    if not webhook_url:
        return

    text = _apply_title(settings, _html_to_slack_mrkdwn(message))
    payload: dict[str, Any] = {
        "text": text,
        "username": settings.get("username") or "Aliasarr",
    }
    if settings.get("channel"):
        payload["channel"] = settings["channel"]
    if settings.get("icon_emoji"):
        payload["icon_emoji"] = settings["icon_emoji"]

    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()


async def _send_generic_webhook(settings: dict, message: str, event_type: str = "general") -> None:
    webhook_url = settings.get("webhook_url")
    if not webhook_url:
        return

    method = (settings.get("http_method") or "POST").upper()
    payload = {
        "event": event_type,
        "app": "Aliasarr",
        "message": _apply_title(settings, message),
        "raw_message": message,
        "clean_message": _strip_html(message),
        "timestamp": dt.datetime.utcnow().isoformat(),
    }

    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        if method == "PUT":
            resp = await client.put(webhook_url, json=payload)
        else:
            resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()


async def _send_email(settings: dict, message: str, event_type: str = "general") -> None:
    import asyncio
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    server = settings.get("server")
    if not server:
        return
    try:
        port = int(settings.get("port") or 587)
    except (ValueError, TypeError):
        port = 587
    from_addr = settings.get("from_address")
    to_addr = settings.get("to_address")
    if not from_addr or not to_addr:
        return

    subject_prefix = settings.get("subject_prefix") or "[Aliasarr]"
    event_titles = {
        "grab": "Release Grabbed",
        "import": "File Imported",
        "upgrade": "Quality Upgraded",
        "rename": "File Renamed",
        "series_add": "Series Added",
        "series_delete": "Series Deleted",
        "episode_file_delete": "Episode File Deleted",
        "episode_file_delete_for_upgrade": "Episode File Deleted for Upgrade",
        "health": "System Health Issue",
        "health_restored": "System Health Restored",
        "app_update": "Application Updated",
        "manual_interaction": "Manual Interaction Required",
        "backup": "Backup Created",
        "test": "Test Notification",
    }
    subject = f"{subject_prefix} {event_titles.get(event_type, event_type.capitalize())}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    plain_text = _strip_html(message)
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(message, "html", "utf-8"))

    use_ssl = bool(settings.get("use_ssl"))
    use_tls = bool(settings.get("use_tls", True))
    username = settings.get("username")
    password = settings.get("password")

    def _sync_send():
        if use_ssl:
            smtp = smtplib.SMTP_SSL(server, port, timeout=15)
        else:
            smtp = smtplib.SMTP(server, port, timeout=15)
        try:
            if not use_ssl and use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())
        finally:
            try:
                smtp.quit()
            except Exception:
                pass

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync_send)


async def _send_pushbullet(settings: dict, message: str, event_type: str = "general") -> None:
    api_key = settings.get("api_key")
    if not api_key:
        return
    url = "https://api.pushbullet.com/v2/pushes"
    headers = {"Access-Token": api_key}
    payload: dict[str, Any] = {
        "type": "note",
        "title": "Aliasarr" if settings.get("include_app_name") else event_type.capitalize(),
        "body": _strip_html(message),
    }
    if settings.get("device_iden") or settings.get("device_id"):
        payload["device_iden"] = settings.get("device_iden") or settings.get("device_id")
    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()


async def _send_apprise(settings: dict, message: str, event_type: str = "general") -> None:
    server_url = (settings.get("server_url") or "").rstrip("/")
    if not server_url:
        return
    url = f"{server_url}/notify" if not server_url.endswith("/notify") else server_url
    payload: dict[str, Any] = {
        "title": "Aliasarr" if settings.get("include_app_name") else event_type.capitalize(),
        "body": _strip_html(message),
    }
    if settings.get("tag"):
        payload["tag"] = settings["tag"]
    if settings.get("urls"):
        payload["urls"] = settings["urls"]
    if httpx is None:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


async def _send_custom_script(settings: dict, message: str, event_type: str = "general") -> None:
    import asyncio
    import os
    script_path = settings.get("path")
    if not script_path or not os.path.exists(script_path):
        return
    args = settings.get("arguments") or ""
    cmd = [script_path] + ([args] if args else [])
    env = {
        **os.environ,
        "ALIASARR_EVENT_TYPE": event_type,
        "ALIASARR_MESSAGE": message,
        "ALIASARR_PLAIN_MESSAGE": _strip_html(message),
    }
    proc = await asyncio.create_subprocess_exec(*cmd, env=env)
    await proc.communicate()


# Реестр доступных диспетчеров
_NOTIFICATION_DISPATCHERS = {
    "telegram": _send_telegram,
    "discord": _send_discord,
    "gotify": _send_gotify,
    "ntfy": _send_ntfy,
    "pushover": _send_pushover,
    "slack": _send_slack,
    "webhook": _send_generic_webhook,
    "email": _send_email,
    "pushbullet": _send_pushbullet,
    "apprise": _send_apprise,
    "script": _send_custom_script,
}

REQUIRED_NOTIFICATION_FIELDS = {
    "telegram": ["bot_token", "chat_id"],
    "discord": ["webhook_url"],
    "gotify": ["server_url", "app_token"],
    "ntfy": ["topic"],
    "pushover": ["user_key", "api_token"],
    "slack": ["webhook_url"],
    "webhook": ["webhook_url"],
    "email": ["server", "from_address", "to_address"],
    "pushbullet": ["api_key"],
    "apprise": ["server_url"],
    "script": ["path"],
}


async def send_notification(config_row, message: str, event_type: str, db=None) -> None:
    """config_row: модель NotificationConfig из БД (или совместимый объект для ad-hoc теста)."""
    try:
        lang = "ru"
        if db is not None:
            try:
                from app.models.db import AppSettings
                settings_row = db.query(AppSettings).first()
                if settings_row and settings_row.language:
                    lang = settings_row.language.lower()
            except Exception:
                pass
        localized_msg = format_notification_message(message, lang)

        cfg_type = getattr(config_row, "type", "").lower()
        dispatcher = _NOTIFICATION_DISPATCHERS.get(cfg_type)

        if dispatcher:
            await dispatcher(config_row.settings or {}, localized_msg, event_type)
        else:
            logger.warning("Неизвестный тип уведомлений: %s", getattr(config_row, "type", "unknown"))
    except Exception as exc:  # уведомления не должны ронять основной процесс
        logger.warning("Не удалось отправить уведомление %s: %s", getattr(config_row, "name", "unknown"), exc)
        raise exc


async def notify_all(db=None, event_type: str = "import", message: str = "") -> None:
    close_db = False
    if db is None:
        try:
            from app.database import SessionLocal
            db = SessionLocal()
            close_db = True
        except Exception as e:
            logger.warning("Не удалось открыть сессию БД для уведомлений: %s", e)
            return

    try:
        from app.models.db import NotificationConfig, AppSettings
    except ImportError:
        NotificationConfig = type("NotificationConfig", (), {"enabled": True})
        AppSettings = object

    try:
        lang = "ru"
        try:
            settings_row = db.query(AppSettings).first()
            if settings_row and settings_row.language:
                lang = settings_row.language.lower()
        except Exception:
            pass

        localized_message = format_notification_message(message, lang)

        field_map = {
            "grab": "on_grab",
            "import": "on_import",
            "download": "on_import",
            "upgrade": "on_upgrade",
            "rename": "on_rename",
            "series_add": "on_series_add",
            "series_delete": "on_series_delete",
            "episode_file_delete": "on_episode_file_delete",
            "episode_file_delete_for_upgrade": "on_episode_file_delete_for_upgrade",
            "health": "on_health_issue",
            "health_issue": "on_health_issue",
            "health_restored": "on_health_restored",
            "app_update": "on_application_update",
            "application_update": "on_application_update",
            "manual_interaction": "on_manual_interaction_required",
            "manual_interaction_required": "on_manual_interaction_required",
            "backup": "on_backup",
        }
        field_name = field_map.get(event_type)

        query = db.query(NotificationConfig).filter(NotificationConfig.enabled == True)  # noqa: E712
        configs = list(query.all())
    except Exception as exc:
        logger.warning("Ошибка при получении конфигурации уведомлений: %s", exc)
        configs = []
    finally:
        if close_db:
            db.close()

    for config_row in configs:
        if field_name and not getattr(config_row, field_name, True):
            continue
        try:
            await send_notification(config_row, localized_message, event_type)
        except Exception:
            pass


def notify_all_sync(db=None, event_type: str = "import", message: str = "") -> None:
    """Синхронный запуск notify_all в фоновом потоке или текущем event loop."""
    import asyncio
    import threading

    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.create_task(notify_all(db=None, event_type=event_type, message=message))
            return
    except RuntimeError:
        pass

    def _run():
        try:
            asyncio.run(notify_all(db=None, event_type=event_type, message=message))
        except Exception as err:
            logger.warning("Ошибка в фоновом notify_all_sync: %s", err)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

