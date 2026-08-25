// ---------------------------------------------------------------------------
// Aliasarr — фронтенд (vanilla JS, без сборки)
// ---------------------------------------------------------------------------

const API_BASE = "";
// Сервер сам встраивает актуальный API-ключ в страницу при отдаче "/", если
// логин по паролю не включён — так браузеру не нужно спрашивать ключ вручную.
let API_KEY = window.__ALIASARR_BOOTSTRAP_KEY__ || localStorage.getItem("aliasarr_api_key") || "";
if (window.__ALIASARR_BOOTSTRAP_KEY__) {
  localStorage.setItem("aliasarr_api_key", API_KEY);
}
let CACHED_SHOWS = [];
let CACHED_QUALITY_PROFILES = [];
let CACHED_METADATA_SOURCES = [];
const QUALITY_OPTIONS = [
  "CAM-480p", "Telesync-480p", "Telecine-480p", "Workprint-480p",
  "SDTV-480p", "TVRip-480p", "DVD-480p", "DVDRip-480p",
  "HDTV-480p", "WEBRip-480p", "WEBDL-480p", "Bluray-480p",
  "HDTV-720p", "WEBRip-720p", "WEBDL-720p", "Bluray-720p",
  "HDTV-1080p", "WEBRip-1080p", "WEBDL-1080p", "Bluray-1080p", "Remux-1080p",
  "HDTV-2160p", "WEBRip-2160p", "WEBDL-2160p", "Bluray-2160p", "Remux-2160p",
];

// ---------- ТЕМА (dark/light) ----------
function applyTheme(theme) {
  const t = theme || "dark";
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("vbeacon_theme", t); } catch (e) {}
}

// ---------- ЯЗЫК (ru/en) ----------
const TRANSLATIONS = {
  ru: {
    // Navigation & Tabs
    "nav.dashboard": "Дашборд",
    "nav.library": "Библиотека",
    "nav.activity": "Активность",
    "nav.calendar": "Календарь",
    "nav.history": "История",
    "nav.audit": "Аудит",
    "nav.settings": "Настройки",
    "nav.events": "События",
    "nav.journal": "Журнал",
    "nav.release_logs": "Релиз логи",
    "nav.backup": "Бэкап",
    "nav.wiki": "Wiki",
    "nav.wiki_tooltip": "База знаний и руководство пользователя",
    "nav.add_video": "+ Добавить видео",
    "tab.dashboard": "Дашборд",
    "tab.library": "Библиотека",
    "tab.activity": "Активность",
    "tab.calendar": "Календарь",
    "tab.history": "История",
    "tab.audit": "Аудит",
    "tab.settings": "Настройки",
    "tab.events": "События",
    "tab.journal": "Журнал",
    "tab.release_logs": "Релиз логи",
    "tab.backup": "Бэкап",

    // Subtitles
    "subtitle.dashboard": "Общая картина и мониторинг библиотеки",
    "subtitle.library": "Все ваши фильмы, сериалы и аниме, с алиасами на всех языках",
    "subtitle.activity": "Текущие загрузки во всех download clients",
    "subtitle.calendar": "Даты выхода серий и премьер фильмов",
    "subtitle.history": "Журнал захваченных релизов",
    "subtitle.audit": "Журнал всех действий пользователей и событий безопасности",
    "subtitle.events": "Информация, предупреждения и ошибки приложения",
    "subtitle.journal": "Логи приложения (info / warn / debug). Записи старше срока хранения удаляются автоматически.",
    "subtitle.release_logs": "Диагностический журнал работы движка релизов: поиск, сопоставление, парсинг серий, принятие решений, вызовы загрузчика и импорт.",
    "subtitle.backup": "Резервное копирование настроек приложения (индексаторы, загрузчики, профили качества, шаблоны и т.д.)",

    // Release Logs
    "release_logs.filter_all_stages": "Все этапы",
    "release_logs.filter_all_levels": "Все статусы",
    "release_logs.search_placeholder": "Поиск по тайтлу или раздаче…",
    "release_logs.col_time": "Время",
    "release_logs.col_stage": "Этап",
    "release_logs.col_level": "Статус",
    "release_logs.col_show": "Тайтл",
    "release_logs.col_message": "Сообщение и принятое решение",
    "release_logs.modal_title": "Детали обработки релиза",

    // Common actions & words
    "common.save": "Сохранить",
    "common.details": "Подробнее",
    "common.cancel": "Отмена",
    "common.delete": "Удалить",
    "common.add": "Добавить",
    "common.edit": "Изменить",
    "common.close": "Закрыть",
    "common.search": "Искать",
    "common.confirm": "Подтвердить",
    "common.refresh": "Обновить",
    "common.browse": "Обзор",
    "common.test": "Тест",
    "common.apply": "Применить",
    "common.copy": "Копировать",
    "common.create": "Создать",
    "common.restore": "Восстановить",
    "common.clear": "Очистить",
    "common.actions": "Действия",
    "common.name": "Название",
    "common.type": "Тип",
    "common.status": "Статус",
    "common.date": "Дата",
    "common.size": "Размер",
    "common.priority": "Приоритет",
    "common.enabled": "Включено",
    "common.importing": "Импорт",
    "common.disabled": "Отключено",
    "common.default": "По умолчанию",
    "common.menu": "Меню",
    "common.host": "Хост",
    "common.port": "Порт",
    "common.username": "Логин",
    "common.password": "Пароль",
    "common.loading": "Загрузка…",
    "common.none": "Нет",
    "common.all": "Все",
    "common.yes": "Да",
    "common.no": "Нет",
    "common.page": "Стр.",
    "common.of": "из",
    "common.total": "всего",
    "common.prev": "Назад",
    "common.next": "Вперёд",
    "common.any_quality": "Любое качество (без ограничений)",

    // Statuses
    "status.monitored": "мониторится",
    "status.monitored_title": "Статус отслеживания",
    "status.unmonitored": "не мониторится",
    "status.missing": "отсутствует",
    "status.wanted": "в поиске",
    "status.downloading": "скачивается",
    "status.upgrading": "ожидает обновление",
    "status.upgrading_title": "Скачивается обновление качества",
    "status.downloaded": "скачано",
    "status.ignored": "игнорируется",
    "status.unaired": "ещё не вышло",
    "status.on_air": "в эфире",
    "status.ended": "завершён",
    "status.continuing": "продолжается",
    "status.aired": "вышло",
    "status.available": "доступен",
    "status.unavailable": "недоступен",
    "status.unknown": "неизвестно",

    // Actions
    "action.monitor": "Мониторить",
    "action.unmonitor": "Снять мониторинг",
    "action.monitor_season": "Мониторить весь сезон",
    "action.unmonitor_season": "Снять мониторинг с сезона",

    // Dashboard
    "dash.btn_refresh": "Обновить",
    "dash.btn_search_wanted": "Поиск Wanted",
    "dash.card_media": "Медиатека",
    "dash.series": "Сериалы",
    "dash.movies": "Фильмы",
    "dash.anime": "Аниме",
    "dash.total": "Всего",
    "dash.card_title_status": "Статус тайтлов",
    "dash.monitored": "Отслеживается",
    "dash.unmonitored": "Не отслеж.",
    "dash.ended": "Завершён",
    "dash.continuing": "Продолжается",
    "dash.card_episodes_status": "Эпизоды и статус",
    "dash.wanted": "В поиске",
    "dash.downloading": "Качается",
    "dash.downloaded": "Скачано",
    "dash.unaired": "Не вышло",
    "dash.card_files_disk": "Файлы и Диск",
    "dash.files": "Файлы",
    "dash.total_size": "Объем",
    "dash.indexers": "Индексаторы",
    "dash.download_clients": "Загрузчики",
    "dash.upcoming_releases": "Ближайшие выходы",
    "dash.full_calendar": "Весь календарь →",
    "dash.recent_grabs": "Последние захваты",
    "dash.full_history": "Вся история →",
    "dash.about_title": "О программе",
    "dash.system_health": "Здоровье системы",
    "health.status_ok": "В норме",
    "dash.video_count": "видео",
    "dash.episodes_count": "серий",
    "dash.no_upcoming": "Ближайших выходов не найдено",
    "dash.no_grabs": "Пока ничего не захвачено",

    // Library
    "library.search_placeholder": "Найти в библиотеке…",
    "library.filter_all": "Все",
    "library.filter_movies": "Фильмы",
    "library.filter_series": "Сериалы",
    "library.filter_anime": "Аниме",
    "library.filter_monitored": "Мониторится",
    "library.filter_unmonitored": "Не мониторится",
    "library.view_posters": "Постеры",
    "library.view_table": "Таблица",
    "library.view_overview": "Обзор",
    "library.view_label": "Просмотр:",
    "library.poster_options_title": "Опции постера",
    "library.empty": "Пока нет ни одного видео.",
    "library.add_first": "Добавить первое видео",
    "library.col_title": "Название",
    "library.col_network": "Сеть",
    "library.col_profile": "Профиль качества",
    "library.col_next_air": "Следующий эфир",
    "library.col_seasons": "Сезоны",
    "library.col_episodes": "Эпизоды",
    "library.no_results": "Ничего не найдено по запросу",
    "library.legend_continuing": "Продолжается (все эпизоды скачаны)",
    "library.legend_ended": "Завершено (все эпизоды скачаны)",
    "library.legend_missing_mon": "Отсутствующие эпизоды (сериал отслеживается)",
    "library.legend_missing_unmon": "Отсутствующие эпизоды (сериал не отслеживается)",
    "library.legend_downloading": "Загрузка (один или несколько эпизодов)",

    // Poster Options
    "poster_opt.title": "Опции постера",
    "poster_opt.size": "Размер постера",
    "poster_opt.small": "Маленький",
    "poster_opt.medium": "Средний",
    "poster_opt.large": "Большой",
    "poster_opt.progress_text": "Подробный индикатор выполнения",
    "poster_opt.progress_text_hint": "Показать текст на индикаторе выполнения",
    "poster_opt.show_title": "Показать название",
    "poster_opt.show_title_hint": "Показать название сериала под постером",
    "poster_opt.show_monitored": "Показать отслеживаемые",
    "poster_opt.show_monitored_hint": "Показывать статус отслеживания под постером",
    "poster_opt.show_quality": "Показать профиль качества",
    "poster_opt.show_quality_hint": "Показать профиль качества под постером",
    "poster_opt.show_tags": "Показать теги",
    "poster_opt.show_tags_hint": "Показать теги под постером",

    // Activity & History
    "activity.search_wanted": "Искать wanted-серии сейчас",
    "activity.check_and_import": "Проверить и перенести",
    "activity.col_name": "Имя",
    "activity.col_client": "Клиент",
    "activity.col_progress": "Прогресс",
    "activity.col_status": "Статус",
    "activity.col_size": "Размер",
    "activity.empty": "Очередь пуста",
    "activity.delete_title": "Удалить из активности и из загрузчика",
    "activity.delete_confirm": "Удалить «{name}» из активности и из загрузчика (Transmission/qBittorrent)?",
    "activity.deleted_toast": "Удалено из загрузчика",
    "history.col_date": "Дата",
    "history.col_show": "Видео",
    "history.col_release": "Релиз",
    "history.col_event": "Событие",
    "history.empty": "История пуста",
    "history.event.grabbed": "захвачено",
    "history.event.imported": "перенесено",
    "history.event.failed": "ошибка",

    // Calendar
    "calendar.today": "Сегодня",
    "calendar.view_month": "Месяц",
    "calendar.view_week": "Неделя",
    "calendar.view_forecast": "Прогноз",
    "calendar.view_day": "День",
    "calendar.view_agenda": "Повестка",
    "calendar.filter_all": "Все видео",
    "calendar.filter_monitored": "Только отслеживаемые",
    "calendar.cat_all": "Все категории",
    "calendar.cat_series": "Сериалы",
    "calendar.cat_movies": "Фильмы",
    "calendar.cat_anime": "Аниме",
    "calendar.status_all": "Все статусы",
    "calendar.status_unaired": "Не вышло",
    "calendar.status_on_air": "Сегодня в эфире",
    "calendar.status_downloading": "Скачивается",
    "calendar.status_missing": "Отсутствует",
    "calendar.status_downloaded": "Скачано",
    "calendar.btn_search_missing": "Поиск",
    "calendar.search_missing_title": "Поиск отсутствующих релизов за период календаря",
    "calendar.search_missing_confirm": "Запустить автопоиск для всех отсутствующих серий и фильмов за отображаемый период календаря?",
    "calendar.search_missing_started": "Автопоиск запущен для {count} тайтлов ({total} элементов)",
    "calendar.ical_title": "Календарная подписка iCal (.ics)",
    "calendar.ical_modal_title": "Календарная подписка (iCal Feed)",
    "calendar.ical_modal_hint": "Используйте эту ссылку для синхронизации расписания релизов Aliasarr с Google Calendar, Apple Calendar, Microsoft Outlook или Thunderbird.",
    "calendar.ical_feed_url": "Ссылка на календарь (.ics):",
    "calendar.ical_webcal_url": "Webcal ссылка (для Apple / Outlook):",
    "calendar.ical_instructions_title": "Как подключить:",
    "calendar.ical_copied": "Ссылка скопирована в буфер обмена",
    "calendar.show_cinema": "Релизы фильмов в кинотеатрах",
    "calendar.show_cinema_hint": "Отображать дату премьеры в кинотеатрах с бейджем «Кино»",
    "calendar.show_digital": "Цифровые релизы фильмов",
    "calendar.show_digital_hint": "Отображать дату цифрового релиза (WEB-DL / VOD) с бейджем «Цифра»",
    "calendar.badge_cinema": "Кино",
    "calendar.badge_digital": "Цифра",
    "calendar.badge_physical": "Диск",
    "calendar.btn_auto_search": "Автопоиск",
    "calendar.btn_manual_search": "Ручной поиск",
    "calendar.btn_open_card": "К карточке",
    "calendar.btn_edit_date": "Изменить дату",
    "calendar.events_count": "релиз(ов)",
    "calendar.no_events_in_period": "Нет запланированных релизов за выбранный период",
    "calendar.movie_premiere": "Премьера фильма",
    "calendar.badge_today": "Сегодня",
    "calendar.badge_tomorrow": "Завтра",
    "calendar.badge_yesterday": "Вчера",
    "calendar.no_releases_day": "Нет выходов",
    "calendar.settings_title": "Настройки календаря",
    "calendar.section_local": "Локальный",
    "calendar.collapse_multi": "Свернуть несколько эпизодов",
    "calendar.collapse_multi_hint": "Свернуть несколько серий, выходящих в эфир в один и тот же день",
    "calendar.show_info": "Показать информацию об эпизоде",
    "calendar.show_info_hint": "Показать название и номер эпизода",
    "calendar.finale_badge": "Значок для финала",
    "calendar.finale_badge_hint": "Показывать значок финала сериала/сезона на основе доступной информации об эпизоде",
    "calendar.unmet_badge": "Значок ожидания лучшего качества",
    "calendar.unmet_badge_hint": "Показывать значок на скачанных сериях, если целевое качество из профиля (Cutoff) ещё не достигнуто",
    "calendar.full_color": "Полноцветные события",
    "calendar.full_color_hint": "Изменен стиль, чтобы раскрасить все событие цветом статуса, а не только левый край. Не относится к повестке дня",
    "calendar.section_global": "Глобальный",
    "calendar.first_day": "Первый день недели",
    "calendar.monday": "Понедельник",
    "calendar.sunday": "Воскресенье",
    "calendar.week_header": "Заголовок столбца недели",
    "calendar.week_header_hint": "Отображается над каждым столбцом, когда неделя активна",
    "calendar.week_header_opt_mm_dd": "Вт 03/25",
    "calendar.week_header_opt_dd_mm": "Вт 25/03",
    "calendar.week_header_opt_d_m": "Вт 25/3",
    "calendar.week_header_opt_m_d": "Вт 3/25",
    "calendar.time_format": "Формат времени",
    "calendar.poll_enabled": "Опрашивать источник метаданных за датами выхода",
    "calendar.poll_interval": "Интервал опроса",
    "calendar.poll_interval_hint": "(минуты, только для видео, добавленных через поиск по метаданным)",
    "calendar.metadata_source": "Источник данных для Календаря",
    "calendar.metadata_source_hint": "(обновление дат выхода серий)",
    "calendar.metadata_source_series": "Источник данных для сериалов и аниме",
    "calendar.metadata_source_series_hint": "(обновление дат серий, по умолчанию Sonarr SkyHook)",
    "calendar.metadata_source_movie": "Источник данных для фильмов",
    "calendar.metadata_source_movie_hint": "(обновление дат премьер, по умолчанию Radarr Movie Cloud)",
    "calendar.source_auto": "Авто (источник шоу)",
    "calendar.premiere": "Премьера",
    "calendar.season_finale": "Финал сезона",
    "calendar.series_finale": "Финал сериала",
    "calendar.waiting_title": "В ожидании даты выхода",
    "calendar.waiting_col_video": "Видео",
    "calendar.waiting_col_category": "Категория",
    "calendar.waiting_col_expected": "Ожидается",
    "calendar.btn_refresh_date": "Поискать дату премьеры",
    "calendar.no_scheduled": "Нет запланированных выходов",
    "calendar.more_events": "+{count} ещё",

    // Settings
    "settingsnav.general": "Общие",
    "settingsnav.security": "Безопасность",
    "settingsnav.users": "Пользователи",
    "settingsnav.audit": "Аудит",
    "settingsnav.indexers": "Индексаторы",
    "settingsnav.download_clients": "Загрузчики",
    "settingsnav.quality_profiles": "Качество",
    "settingsnav.metadata": "Метаданные",
    "settingsnav.notifications": "Уведомления",
    "settings.apikey_title": "API-ключ",
    "settings.apikey_label": "API-ключ",
    "settings.apikey_hint": "используется этим интерфейсом и внешними клиентами для запросов к серверу",
    "settings.apikey_source_env": "Ключ задан через переменную окружения ALIASARR_API_KEY — измените её в docker-compose.yml, чтобы поменять ключ.",
    "settings.apikey_source_auto": "Ключ сгенерирован автоматически. Можно сгенерировать новый в любой момент.",
    "settings.btn_regenerate_key": "↻ Новый ключ",
    "settings.btn_api_docs": "Справочник API",
    "settings.interface_title": "Интерфейс",
    "settings.language": "Язык",
    "settings.theme": "Тема",
    "settings.theme_dark": "Неоновая полночь",
    "settings.theme_dracula": "Дракула",
    "settings.theme_light": "Полярный день",
    "settings.timezone": "Часовой пояс",
    "settings.timezone_hint": "(единый для календаря, журнала и событий)",
    "settings.folders_title": "Папки и переименование по категориям",
    "settings.btn_templates_cheatsheet": "Справочник шаблонов",
    "settings.folders_hint": "Категория контента (привязана к выбору «Категория» в карточке видео в Библиотеке) → папка, куда загрузчик сохраняет скачанное → папка, куда Aliasarr переносит и переименовывает готовое видео по шаблону справа. Кнопки «Обзор» открывают папки внутри контейнера и примонтированные тома.",
    "settings.col_category": "Категория",
    "settings.col_download_folder": "Папка куда скачается",
    "settings.col_root_folder": "Папка куда перенести",
    "settings.col_season_folder": "Папка сезона",
    "settings.col_rename_template": "Шаблон переименования",
    "settings.cat_movies": "Фильмы",
    "settings.cat_series": "Сериалы",
    "settings.cat_anime": "Аниме",
    "settings.autosearch_title": "Автопоиск и скачивание",
    "settings.min_seeds": "Минимальное число сидов для скачивания",
    "settings.min_seeds_hint": "(0 — без ограничения)",
    "settings.prefer_seeded": "Скачивать только самый популярный релиз (с наибольшим числом сидов)",
    "settings.monitor_interval": "Интервал автопоиска разыскиваемого (Wanted Search)",
    "settings.monitor_interval_hint": "(минуты)",
    "settings.download_check_interval": "Интервал проверки завершения загрузок",
    "settings.download_check_seconds_hint": "(секунды)",
    "settings.tracker_check_interval": "Интервал слежения за раздачами (Tracker Ongoing)",
    "settings.tracker_check_interval_hint": "(минуты)",
    "settings.unaired_check_interval": "Интервал активации премьер (Unaired → Wanted)",
    "settings.unaired_check_interval_hint": "(минуты)",
    "settings.security_title": "Безопасность и авторизация",
    "settings.security_hint": "Вход по логину и паролю защищает веб-интерфейс. Внешние API-запросы продолжают работать по X-Api-Key заголовку.",
    "settings.require_login": "Требовать вход по логину и паролю",
    "settings.auth_disabled_for_local": "Отключить авторизацию для локальных адресов (Disabled for Local Addresses)",
    "settings.auth_disabled_for_local_hint": "Разрешает доступ к веб-интерфейсу без ввода логина и пароля с локальных и приватных IP-адресов (localhost, 127.0.0.1, 192.168.x.x, 10.x.x.x, 172.16-31.x.x). Только главный администратор может изменять эту настройку.",
    "settings.current_ip": "Ваш текущий IP:",
    "settings.local_ip_badge": "Локальный (вход без пароля)",
    "settings.remote_ip_badge": "Внешний / WAN (требуется пароль)",
    "settings.login_username": "Логин",
    "settings.display_name": "Отображаемое имя администратора",
    "settings.login_password": "Пароль",
    "settings.login_password_hint": "оставьте пустым, чтобы не менять текущий",
    "settings.new_password_placeholder": "Новый пароль",
    "settings.session_timeout": "Таймаут сессии (автоматический выход)",
    "settings.docker_reset_title": "Сброс пароля Администратора в Docker",
    "settings.docker_reset_hint": "Если пароль утерян или забыт, вы можете сбросить его прямо из хост-системы одним из следующих способов:",
    "settings.docker_reset_m1_title": "1. Через команду терминала Docker (рекомендуется):",
    "settings.docker_reset_m1_hint": "Если опустить параметр <code class=\"mono\">--password</code>, система сгенерирует надёжный случайный пароль и выведет его в консоль.",
    "settings.docker_reset_m2_title": "2. Через переменную окружения в docker-compose.yml:",
    "settings.docker_reset_m3_title": "3. Через файл-триггер в примонтированной папке /config:",
    "settings.docker_reset_m3_hint": "Создайте файл <code class=\"mono\">/config/reset_admin_password.txt</code> с новым паролем. При следующем старте контейнера Aliasarr применит пароль и удалит файл.",

    // SSL / HTTPS
    "settings.ssl_title": "Безопасный протокол HTTPS (SSL)",
    "settings.ssl_hint": "Шифрование трафика веб-интерфейса через встроенный самоподписанный SSL-сертификат. Сертификат выпускается на 100 лет (36500 дней) и автоматически перевыпускается при истечении срока.",
    "settings.ssl_enable_label": "Включить HTTPS (SSL)",
    "settings.ssl_port": "Порт HTTPS",
    "settings.ssl_auto_renew_label": "Автоматический самовыпуск при истечении",
    "settings.ssl_cert_details": "Информация о сертификате",
    "settings.ssl_btn_regenerate": "Перевыпустить",
    "settings.ssl_btn_save": "Сохранить настройки SSL",
    "settings.ssl_valid_to": "Срок действия:",
    "settings.ssl_days_left": "Осталось:",
    "settings.ssl_subject": "Субъект (SAN):",
    "settings.ssl_fingerprint": "SHA-256 Отпечаток:",
    "settings.toast_ssl_saved": "Настройки SSL успешно сохранены",
    "settings.toast_ssl_regenerated": "SSL-сертификат успешно перевыпущен на 100 лет",

    // Users & RBAC
    "users.add_title": "Добавить пользователя",
    "users.edit_title": "Редактирование: {name}",
    "users.username_placeholder": "Логин",
    "users.display_name_placeholder": "Отображаемое имя",
    "users.password_placeholder": "Пароль (минимум 4 символа)",
    "users.is_admin_label": "Права Администратора (полный неограниченный доступ)",
    "users.custom_permissions": "Индивидуальные права доступа:",
    "users.col_username": "Пользователь",
    "users.col_role": "Роль",
    "users.col_status": "Статус",
    "users.col_last_login": "Последний вход",
    "users.col_actions": "Действия",
    "users.btn_reset_pwd": "Сбросить пароль",
    "users.modal_reset_title": "Сброс пароля пользователя",
    "users.active": "Активен",
    "users.disabled": "Отключен",
    "users.role_admin": "Администратор",
    "users.role_user": "Пользователь",
    "users.role_owner": "Главный админ",
    "users.never_logged_in": "Никогда",

    // Permissions
    "perm.view_dashboard": "Просмотр дашборда",
    "perm.view_library": "Просмотр библиотеки",
    "perm.manage_library": "Управление библиотекой",
    "perm.manual_search": "Ручной поиск и захват",
    "perm.view_calendar": "Просмотр календаря",
    "perm.manage_calendar": "Управление датами в календаре",
    "perm.view_activity": "Просмотр активности / загрузок",
    "perm.manage_activity": "Управление загрузками",
    "perm.view_history": "Просмотр истории",
    "perm.view_events": "Просмотр событий",
    "perm.view_journal": "Просмотр журнала",
    "perm.manage_journal": "Очистка и скачивание журнала",
    "perm.view_release_logs": "Просмотр логов релизов",
    "perm.manage_release_logs": "Управление логами релизов",
    "perm.view_audit": "Просмотр аудита",
    "perm.manage_settings": "Настройки приложения",
    "perm.manage_indexers": "Индексаторы / Трекеры",
    "perm.manage_downloaders": "Download Clients",
    "perm.manage_users": "Управление пользователями",
    "perm.manage_backups": "Управление бэкапами",
    "perm.use_api_key": "Персональный API-ключ",

    // Profile & Auth
    "auth.logout": "Выйти из системы",
    "profile.title": "Профиль пользователя",
    "profile.tab_general": "Профиль",
    "profile.tab_permissions": "Мои права",
    "profile.tab_apikey": "API-ключ",
    "profile.tab_change_password": "Смена пароля",
    "profile.display_name": "Отображаемое имя",
    "profile.display_name_placeholder": "Ваше имя (напр. Олег)",
    "profile.btn_change_avatar": "Сменить аватар",
    "profile.btn_remove_avatar": "Удалить аватар",
    "profile.btn_generate_key": "↻ Новый ключ",
    "profile.btn_revoke_key": "Отозвать",
    "profile.apikey_hint": "позволяет делать запросы к API с назначенными вам правами доступа (заголовок: X-Api-Key)",
    "profile.apikey_no_permission": "Использование API-ключа отключено для вашей учётной записи. Обратитесь к администратору для предоставления прав.",
    "profile.current_password": "Текущий пароль",
    "profile.new_password": "Новый пароль",
    "profile.confirm_password": "Подтвердите новый пароль",
    "profile.btn_save_password": "Обновить пароль",
    "profile.pwd_changed_toast": "Пароль успешно обновлён",
    "profile.pwd_mismatch": "Новый пароль и подтверждение не совпадают",
    "profile.pwd_too_short": "Пароль должен содержать минимум 4 символа",
    "profile.avatar_updated": "Аватар успешно обновлён",
    "profile.avatar_removed": "Аватар удалён",

    // Audit Log
    "audit.title": "Журнал аудита действий",
    "audit.all_actions": "Все действия",
    "audit.col_time": "Время",
    "audit.col_user": "Пользователь",
    "audit.col_action": "Действие",
    "audit.col_description": "Описание",
    "audit.col_ip": "IP-адрес",
    "audit.empty": "Записей аудита пока нет",

    // Indexers
    "indexers.add_title": "Добавить индексатор",
    "indexers.edit_title": "Редактирование: {name}",
    "indexers.name_placeholder": "Название, напр. Rutracker",
    "indexers.url_placeholder": "Base URL (Torznab endpoint)",
    "indexers.key_placeholder": "API key",
    "indexers.priority_placeholder": "Приоритет (0-1000, меньше = выше)",
    "indexers.info_hint": "Поддерживается только прямое подключение по Torznab-протоколу — сам трекер или любой другой сервис с Torznab API. Поиск по индексаторам идёт строго по приоритету (0 — самый приоритетный, 1000 — последний). Ограничение по категориям (Фильмы/Сериалы/Аниме) намеренно не используется — многие трекеры на torznab-уровне присваивают категории иначе, чем в интерфейсе Jackett/Prowlarr, из-за чего валидные релизы могли пропадать из поиска.",
    "indexers.check_settings_title": "Настройки проверки доступности",
    "indexers.auto_check": "Автоматически проверять доступность индексаторов",
    "indexers.check_interval": "Интервал проверки",
    "indexers.check_retries": "Число попыток перед тем, как отметить индексатор недоступным",
    "indexers.check_delay": "Пауза между попытками",
    "indexers.col_name": "Название",
    "indexers.col_type": "Тип",
    "indexers.col_url": "URL",
    "indexers.col_priority": "Приоритет",
    "indexers.col_availability": "Доступность",
    "indexers.empty": "Индексаторы не добавлены",

    // Download Clients
    "dc.add_title": "Добавить download client",
    "clients.add_title": "Добавить download client",
    "dc.edit_title": "Редактирование: {name}",
    "dc.host_placeholder": "Host (напр. qbittorrent или 192.168.1.10)",
    "dc.blackhole_hint": "Путь к папке наблюдения (Watch Directory на диске):",
    "dc.use_default": "Использовать по умолчанию",
    "dc.seed_time_limit_label": "Время раздачи (мин, 0 = сразу):",
    "dc.seed_ratio_limit_label": "Коэффициент раздачи (Ratio):",
    "dc.seed_time_placeholder": "0 (импорт сразу)",
    "dc.seed_ratio_placeholder": "0 (без ограничения)",
    "dc.col_name": "Название",
    "dc.col_type": "Тип",
    "dc.col_host": "Хост",
    "dc.col_availability": "Доступность",
    "dc.col_default": "По умолч.",
    "dc.status_available": "Доступно",
    "dc.status_unavailable": "Недоступно",
    "dc.status_untested": "Не проверено",
    "dc.empty": "Загрузчики не добавлены",

    // Quality Profiles & Quality Formats
    "quality.settings_title": "Профили и форматы качества",
    "quality.settings_subtitle": "Настройка предпочтительного качества, порогов апгрейда и скоринга релизов",
    "qp.add_title": "Добавить профиль качества",
    "quality.add_title": "Добавить профиль качества",
    "qp.edit_title": "Редактирование: {name}",
    "qp.name_placeholder": "Название, напр. HD-1080p",
    "qp.allowed_label": "Разрешённые качества (можно несколько)",
    "qp.cutoff_quality_label": "Порог качества (Cutoff Quality)",
    "qp.cutoff_score_label": "Порог очков формата (Cutoff Score)",
    "qp.upgrade_allowed_label": "Разрешить автоматический апгрейд качества / очков до достижения Cutoff",
    "qp.col_name": "Название",
    "qp.col_allowed": "Разрешено",
    "qp.col_cutoff": "Порог (Cutoff)",
    "qp.empty": "Профили не созданы",
    "cf.title": "Форматы качества",
    "cf.subtitle": "Правила распознавания и приоритезации релизов (HDR, TrueHD, Proper, Preferred Groups)",
    "cf.add_btn": "Добавить формат",
    "cf.guide_btn": "Справочник качества",
    "cf.guide_btn_title": "Открыть полное руководство по профилям качества, форматам качества и Release Title Regex в новой вкладке",
    "cf.col_score": "Очки (Score)",
    "cf.col_renaming": "В имени файла",
    "cf.modal_title": "Формат качества",
    "cf.score_label": "Очки (Score)",
    "cf.include_renaming": "Включать в имя файла при переименовании ({Custom Formats})",
    "cf.regex_pattern": "Regex шаблон названия (Release Title Regex)",
    "cf.builtin_badge": "Штатный",
    "cf.reset_btn": "Сбросить до заводских настроек",
    "cf.reset_confirm": "Сбросить этот формат качества до заводских настроек по умолчанию?",
    "cf.cannot_delete_builtin": "Штатные форматы качества нельзя удалять",
    "cf.reset_success": "Формат качества успешно сброшен до заводских настроек",

    // Metadata
    "md.add_title": "Добавить источник метаданных",
    "metadata.add_title": "Добавить источник метаданных",
    "md.edit_title": "Редактирование: {name}",
    "md.name_placeholder": "Название, напр. TMDB или TheTVDB",
    "md.tmdb_how_title": "Как получить ключ TMDB:",
    "md.tmdb_step1": "Зарегистрируйтесь на <a href=\"https://www.themoviedb.org\" target=\"_blank\" rel=\"noopener\">themoviedb.org</a>",
    "md.tmdb_step2": "Откройте <a href=\"https://www.themoviedb.org/settings/api\" target=\"_blank\" rel=\"noopener\">Settings → API</a>",
    "md.tmdb_step3": "Скопируйте <strong>Read Access Token (v4 auth)</strong> — это длинная строка <code>eyJ...</code>",
    "md.tmdb_important": "<strong>Важно:</strong> вставляйте именно <em>Read Access Token</em> (<code>eyJ...</code>), а не короткий API Key v3.",
    "md.thetvdb_title": "TheTVDB API v4:",
    "md.thetvdb_desc": "Для использования TheTVDB введите <strong>API Key v4</strong> из личного кабинета <a href=\"https://thetvdb.com/dashboard/account/api\" target=\"_blank\" rel=\"noopener\">thetvdb.com</a>. Если у вас подписка со Subscriber PIN, укажите PIN в поле ниже.",
    "md.pin_placeholder": "Subscriber PIN (опционально)",
    "md.tvmaze_title": "TVMaze:",
    "md.tvmaze_desc": "Если у вас есть аккаунт TVmaze, для Premium-функций введите <code>ваш_логин:ваш_API_ключ</code>. Ключ можно найти на <a href=\"https://www.tvmaze.com/dashboard\" target=\"_blank\" rel=\"noopener\">tvmaze.com/dashboard</a>.",
    "md.alias_filter_title": "Фильтр алиасов (альтернативных названий) по странам:",
    "md.alias_filter_hint": "Если ничего не выбрано — загружаются алиасы для всех стран мира.",
    "md.col_name": "Название",
    "md.col_type": "Тип",
    "md.empty": "Источники не добавлены",

    "md.auto_refresh_title": "Автоматическое обновление метаданных",
    "md.auto_refresh_desc": "Регулярная синхронизация со SkyHook/TMDB/TVDB: подтягивание официальных названий для невышедших серий (вместо «Episode N»), добавление новых анонсированных серий и обновление дат премьер.",
    "md.auto_refresh_checkbox": "Включить автоматическое обновление метаданных библиотеки",
    "md.refresh_interval_label": "Период обновления:",
    "md.interval_6h": "Каждые 6 часов",
    "md.interval_12h": "Каждые 12 часов",
    "md.interval_24h": "Каждые 24 часа (1 день)",
    "md.interval_3d": "Каждые 3 дня",
    "md.interval_7d": "Раз в 1 неделю (7 дней)",
    "md.btn_refresh_now": "Обновить метаданные всех тайтлов сейчас",
    "md.btn_refresh_now_title": "Запустить полное обновление метаданных всех тайтлов сейчас",
    "md.settings_saved": "Настройки обновления метаданных сохранены",
    "md.refresh_started": "Запущено фоновое обновление метаданных библиотеки...",
    "library.btn_refresh_all": "Обновить метаданные",
    "library.btn_refresh_all_title": "Обновить метаданные всех тайтлов из сети",

    // Countries
    "country.ru": "Россия (RU)",
    "country.us": "США (US)",
    "country.gb": "Великобритания (GB)",
    "country.jp": "Япония (JP)",
    "country.kr": "Юж. Корея (KR)",
    "country.cn": "Китай (CN)",
    "country.fr": "Франция (FR)",
    "country.de": "Германия (DE)",
    "country.es": "Испания (ES)",
    "country.it": "Италия (IT)",

    // Health
    "health.indexers_enabled": "Включённых индексаторов: {count}",
    "health.no_indexers": "Нет ни одного включённого индексатора — поиск релизов не будет работать",
    "health.dc_enabled": "Включённых download clients: {count}",
    "health.no_dc": "Нет ни одного download client — захваченные релизы не будут скачиваться",
    "health.shows_without_profile": "Видео без профиля качества: {count} (будет разрешено любое качество)",

    // Notifications
    "nt.add_title": "Добавить уведомление",
    "notifications.add_title": "Добавить уведомление",
    "nt.edit_title": "Редактирование: {name}",
    "nt.enabled": "Включить уведомление",
    "nt.bot_token_label": "Токен бота",
    "nt.bot_token_hint": "(получить у @BotFather)",
    "nt.chat_id_label": "Идентификатор чата",
    "nt.chat_id_placeholder": "-1001234567890 или 123456789",
    "nt.telegram_thread_id_label": "ID темы / топика (необязательно)",
    "nt.telegram_thread_id_placeholder": "1234",
    "nt.telegram_silent": "Без звука",
    "nt.discord_webhook_url_label": "URL вебхука Discord",
    "nt.discord_username_label": "Имя бота (необязательно)",
    "nt.discord_avatar_url_label": "URL аватара (необязательно)",
    "nt.gotify_server_url_label": "URL сервера Gotify",
    "nt.gotify_app_token_label": "App Token",
    "nt.gotify_priority_label": "Приоритет (1-10)",
    "nt.ntfy_server_url_label": "URL сервера Ntfy (по умолчанию https://ntfy.sh)",
    "nt.ntfy_topic_label": "Топик / Тема",
    "nt.ntfy_token_label": "Access Token (для приватных тем, необязательно)",
    "nt.ntfy_priority_label": "Приоритет (1-5)",
    "nt.pushover_user_key_label": "User Key",
    "nt.pushover_api_token_label": "App API Token",
    "nt.pushover_priority_label": "Приоритет (-2..2)",
    "nt.pushover_sound_label": "Звук (необязательно)",
    "nt.slack_webhook_url_label": "URL вебхука Slack",
    "nt.slack_channel_label": "Канал (необязательно, напр. #downloads)",
    "nt.webhook_url_label": "URL вебхука",
    "nt.webhook_method_label": "HTTP метод",
    "nt.include_app_name": "Включить Aliasarr в заголовок",
    "nt.triggers_title": "События уведомлений:",
    "nt.on_grab": "При захвате релиза",
    "nt.on_import": "При скачивании / импорте",
    "nt.on_upgrade": "При обновлении качества",
    "nt.on_rename": "При переименовании файлов",
    "nt.on_series_add": "При добавлении тайтла",
    "nt.on_series_delete": "При удалении тайтла",
    "nt.on_file_delete": "При удалении файла",
    "nt.on_backup": "При создании бэкапа",
    "nt.col_name": "Название",
    "nt.col_type": "Тип",
    "nt.col_status": "Статус",
    "nt.status_enabled": "Включено",
    "nt.status_disabled": "Отключено",
    "nt.empty": "Уведомления не настроены",
    "show.delete_modal_title": "Удаление карточки",
    "show.delete_files_label": "Удалить карточку вместе с файлами",
    "show.delete_files_hint": "Файлы и директория медиафайлов будут безвозвратно удалены с диска.",

    // Фоновые операции и задачи
    "tasks.widget_tooltip": "Фоновые операции (нажмите для подробностей)",
    "tasks.idle": "Все задачи завершены",
    "tasks.popup_title": "Фоновые операции",
    "tasks.running_section": "Выполняются сейчас",
    "tasks.recent_section": "Недавние операции",
    "tasks.no_running": "Нет активных операций",
    "tasks.no_recent": "История операций пуста",
    "tasks.clear_history": "Очистить",
    "tasks.status_running": "Выполняется",
    "tasks.status_completed": "Завершено",
    "tasks.status_failed": "Ошибка",

    // Events & Journal
    "events.filter_all": "Все события",
    "events.filter_info": "Информация",
    "events.filter_warning": "Предупреждения",
    "events.filter_error": "Ошибки",
    "events.page_size": "Размер страницы:",
    "events.sort_time": "Время ↓",
    "events.col_time": "Время",
    "events.col_component": "Компонент",
    "events.col_message": "Сообщение",
    "events.empty": "Событий нет",
    "journal.filter_all": "Все уровни",
    "journal.btn_download": "Скачать .txt",
    "journal.btn_clear": "Очистить",
    "journal.col_time": "Время",
    "journal.col_level": "Уровень",
    "journal.col_component": "Компонент",
    "journal.col_message": "Сообщение",
    "journal.retention_title": "Хранение",
    "journal.retention_label": "Хранить записи журнала и событий",
    "journal.empty": "Записей нет",

    // Backup
    "backup.btn_create": "Создать бэкап",
    "backup.btn_upload": "Загрузить архив",
    "backup.btn_schedule_settings": "Настройки расписания",
    "backup.btn_start_create": "Начать создание",
    "backup.btn_confirm_restore": "Восстановить данные",
    "backup.btn_restore": "Восстановить",
    "backup.btn_delete_selected": "Удалить выбранные",
    "backup.col_file": "Файл и Тип",
    "backup.col_size": "Размер",
    "backup.col_contents": "Состав архива",
    "backup.col_created": "Создан",
    "backup.col_actions": "Действия",
    "backup.empty": "Резервных копий ещё нет",
    "backup.stat_total": "Всего копий",
    "backup.stat_latest": "Последний бэкап",
    "backup.stat_schedule": "Авто-бэкап",
    "backup.stat_storage": "Хранилище",
    "backup.create_title": "Создание резервной копии",
    "backup.create_subtitle": "Выберите тип архива для сохранения данных Aliasarr",
    "backup.type_full_title": "Полный бэкап (Рекомендуется)",
    "backup.type_full_desc": "Включает всю медиатеку (карточки фильмов, сериалов, аниме, эпизоды, историю, алиасы) + все профили качества, форматы качества, индексаторы, загрузчики и настройки.",
    "backup.type_config_title": "Только настройки (Конфигурация)",
    "backup.type_config_desc": "Сохраняет только настройки системы, индексаторы, клиенты загрузки, профили качества, форматы качества, шаблоны переименования и уведомления (без карточек медиатеки).",
    "backup.restore_title": "Восстановление из резервной копии",
    "backup.restore_subtitle": "Проверка содержимого архива и выбор режима восстановления",
    "backup.restore_items_label": "Обнаруженные компоненты в архиве:",
    "backup.restore_mode_label": "Режим восстановления:",
    "backup.safety_snapshot_note": "Перед применением бэкапа Aliasarr автоматически создаст резервную точку отката текущей базы данных.",
    "backup.mode_auto": "Автоматически (согласно составу архива)",
    "backup.mode_full": "Полное восстановление (Библиотека + Настройки)",
    "backup.mode_config": "Только конфигурация (Сохранить текущую библиотеку)",
    "backup.schedule_title": "Расписание автоматического бэкапа",
    "backup.schedule_subtitle": "Автоматическое резервное копирование и ротация архивов",
    "backup.schedule_interval_label": "Интервал автосоздания:",
    "backup.schedule_type_label": "Тип автоматического бэкапа:",
    "backup.schedule_retention_label": "Лимит хранения (Retention Count):",
    "backup.interval_disabled": "Отключено (Только вручную)",
    "backup.interval_daily": "Ежедневно (Каждые 24 часа)",
    "backup.interval_weekly": "Еженедельно (Раз в 7 дней)",
    "backup.interval_monthly": "Ежемесячно (Раз в 30 дней)",
    "backup.type_full": "Полный (Медиатека + Настройки)",
    "backup.type_config": "Только настройки (Конфигурация)",
    "backup.retention_hint": "При превышении лимита самые старые архивы будут автоматически удаляться.",
    "backup.toast_created": "Резервная копия успешно создана",
    "backup.toast_restored": "Данные успешно восстановлены из бэкапа",
    "backup.toast_schedule_saved": "Настройки автобэкапа сохранены",
    "backup.badge_full": "Полный",
    "backup.badge_config": "Настройки",

    // Templates Guide Modal
    "tpl_guide.title": "Справочник шаблонов переименования",
    "tpl_guide.hint": "Кликните на любой готовый пресет или токен, чтобы вставить его в шаблон. Изменения сразу применяются к целевому полю.",
    "tpl_guide.tab_series": "Сериалы",
    "tpl_guide.tab_anime": "Аниме",
    "tpl_guide.tab_movie": "Фильмы",
    "tpl_guide.editor_label": "Редактируемый шаблон:",
    "tpl_guide.target_label": "Поле:",
    "tpl_guide.target_series": "Шаблон — Сериал",
    "tpl_guide.target_anime": "Шаблон — Аниме",
    "tpl_guide.target_movie": "Шаблон — Фильм",
    "tpl_guide.default_label": "По умолчанию:",
    "tpl_guide.btn_default": "По умолчанию",
    "tpl_guide.preview_label": "Предпросмотр результата:",
    "tpl_guide.presets_title": "Готовые форматы (кликните для применения)",
    "tpl_guide.tokens_title": "Справочник токенов",

    // Show Details Modal
    "show.directory": "Директория:",
    "show.not_set": "Не задана",
    "show.btn_sync": "Синхронизация",
    "show.present_on_disk": "Присутствует на диске",
    "show.missing_on_disk": "Отсутствует на диске",
    "show.on_disk": "На диске",
    "show.no_overview": "Описание отсутствует",
    "show.seasons_count": "Сезонов",
    "show.next_airing": "Следующий эфир",
    "show.upload_cover": "Загрузить",
    "show.refresh_cover": "Обновить (Сеть)",
    "show.new_alias_placeholder": "Новый алиас…",
    "show.force_search": "Принудительный автопоиск",
    "show.search_manual": "Искать релизы вручную",
    "show.delete_video": "Удалить видео",
    "show.confirm_change_category": "Сменить категорию? Это изменит папку/шаблон переименования при следующем скачивании и вид карточки, но уже скачанные файлы никуда не переместятся автоматически.",
    "show.season": "Сезон",
    "show.download_wanted_episodes": "Скачать выбранные серии",
    "show.manual_import": "Ручной импорт",
    "show.btn_sync": "Импорт библиотеки",
    "show.sync_tooltip": "Сканировать файлы на диске и обновить серии в библиотеке",
    "show.monitor_all_seasons": "Мониторить все сезоны",
    "show.unmonitor_all_seasons": "Игнорировать все сезоны",
    "show.monitor_all_tooltip": "Перевести все сезоны и нескачанные серии в мониторинг (в поиске)",
    "show.unmonitor_all_tooltip": "Перевести все сезоны и нескачанные серии в статус «игнорируется»",
    "show.monitor_unaired": "Мониторить невышедшие",
    "show.monitor_unaired_tooltip": "Перевести все невышедшие серии тайтла в статус «в поиске»",
    "show.unaired_monitored": "Все невышедшие серии переведены в статус «в поиске»",
    "show.all_seasons_monitored": "Все сезоны переведены в мониторинг (в поиске)",
    "show.all_seasons_unmonitored": "Все сезоны переведены в статус «игнорируется»",
    "show.preview_rename_title": "Упорядочить и переименовать",
    "show.btn_preview_rename": "Переименовать файлы",
    "show.btn_preview_rename_season": "Переименовать сезон",
    "show.expand_all_seasons": "Развернуть все",
    "show.collapse_all_seasons": "Свернуть все",
    "show.rename_relative_hint": "Все пути указаны относительно:",
    "show.rename_template_label": "Шаблон именования:",
    "show.rename_select_all": "Выбрать все",
    "show.rename_selected_count": "Выбрано: {selected} из {total}",
    "show.btn_organize": "Организовать",
    "show.rename_no_files": "Все файлы уже переименованы в соответствии с шаблоном.",
    "show.rename_success": "Успешно переименовано {count} файл(ов)",
    "show.import_specials": "Импорт спецвыпусков",
    "show.import_specials_tooltip": "Ручное сопоставление и импорт скачанных спецвыпусков",
    "show.import_specials_ready": "Спецвыпуски скачаны и готовы к импорту!",
    "manual_import.global_btn": "Ручной импорт",
    "manual_import.title": "Ручной импорт файлов",
    "manual_import.title_specials": "Ручной импорт спецвыпусков (Сезон 0)",
    "manual_import.warn_duplicate": "Внимание: эта серия выбрана в нескольких строках!",
    "manual_import.col_show": "Тайтл (сериал / фильм)",
    "manual_import.select_show": "— Выберите тайтл —",
    "manual_import.scan": "Сканировать",
    "manual_import.folder_placeholder": "Путь к папке со скачанными файлами...",
    "manual_import.mode_label": "Режим:",
    "manual_import.mode_move": "Переместить",
    "manual_import.mode_copy": "Копировать",
    "manual_import.col_file": "Исходный файл",
    "manual_import.col_quality": "Качество",
    "manual_import.col_episode": "Серия карточки (сопоставление)",
    "manual_import.col_status": "Статус",
    "manual_import.skip": "— Не импортировать (пропустить) —",
    "manual_import.ready": "Готово",
    "manual_import.overwrite": "Перезапишет существующий",
    "manual_import.not_matched": "Выберите серию",
    "manual_import.btn_import": "Импортировать выбранные",
    "manual_import.no_files": "Видеофайлы не найдены в указанной папке",
    "manual_import.summary": "Найдено файлов: {total}, выбрано для импорта: {selected}",
    "manual_import.success": "Файлы успешно импортированы",

    // Add Video Wizard
    "wizard.step_method": "1. Способ",
    "wizard.step_search": "2. Поиск",
    "wizard.step_setup": "3. Настройка",
    "wizard.method_metadata_title": "Найти через метаданные",
    "wizard.method_metadata_desc": "Алиасы и даты выхода заполнятся автоматически.",
    "wizard.method_manual_title": "Добавить вручную",
    "wizard.method_manual_desc": "Укажите название и алиасы самостоятельно — удобно для редких тайтлов без метаданных.",
    "wizard.search_placeholder": "Название фильма, сериала или аниме…",
    "wizard.manual_title_label": "Название (основное)",
    "wizard.manual_title_placeholder": "Например: The Villager of Level 999",
    "wizard.manual_aliases_label": "Алиасы, по одному на строку. Формат: текст | язык (ru/en/jp/romaji)",
    "wizard.manual_cover_label": "Обложка",
    "wizard.manual_no_cover": "Нет обложки",
    "wizard.manual_upload_cover": "Загрузить с компьютера",
    "wizard.manual_cover_url_placeholder": "…или вставьте ссылку на изображение",
    "wizard.back": "Назад",
    "wizard.next": "Далее",
    "wizard.select": "Выбрать",
    "wizard.already_in_library": "Уже в библиотеке",
    "wizard.category_label": "Категория",
    "wizard.category_hint": "(определяет папку и шаблон переименования после скачивания)",
    "wizard.path_label": "Путь к папке (необязательно)",
    "wizard.monitor_immediately": "Начать мониторинг сразу после добавления",
    "wizard.autosearch_after_add": "Запустить автопоиск после добавления",
    "wizard.finish_btn": "Добавить видео",
    "wizard.toast_no_metadata_source": "Сначала добавьте источник метаданных в Настройках",
    "tracker.checking": "Проверка раздач",
    "search.searching": "Поиск",
    "md.updating": "Метаданные",

    // Dashboard & Calendar & Settings & Backup Toasts / Prompts
    "dash.toast_grabbed_for_shows": "Готово: захвачено для {count} видео",
    "calendar.prompt_air_date": "«{title}»\nВведите новую дату выхода (ГГГГ-ММ-ДД) или оставьте пустым и нажмите OK, чтобы убрать из календаря и вернуть в \"Ожидание даты выхода\":",
    "calendar.toast_removed": "Убрано из календаря",
    "calendar.toast_invalid_date": "Некорректная дата",
    "calendar.toast_date_updated": "Дата обновлена",
    "settings.confirm_regenerate_key": "Сгенерировать новый API-ключ? Старый ключ перестанет работать — обновите его во всех внешних клиентах.",
    "settings.toast_saved": "Настройки сохранены",
    "settings.toast_key_regenerated": "Новый API-ключ сгенерирован и сохранён в этом браузере",
    "settings.toast_template_applied": "Шаблон применён к активному полю",
    "settings.toast_default_template_inserted": "Шаблон по умолчанию вставлен в активное поле",
    "settings.toast_login_enabled": "Вход по логину/паролю включён",
    "settings.toast_security_saved": "Настройки безопасности сохранены",
    "settings.toast_key_copied": "Ключ скопирован",
    "backup.confirm_restore": "Восстановить настройки из «{name}»? Текущие индексаторы, загрузчики, профили качества и шаблоны будут заменены.",
    "backup.toast_restored": "Настройки восстановлены. Обновите страницу для применения.",

    // Folder Picker & Login Modals
    "folder_picker.title": "Выбор папки",
    "folder_picker.up_title": "Наверх",
    "folder_picker.new_placeholder": "Имя новой папки…",
    "folder_picker.btn_create": "+ Создать",
    "folder_picker.btn_select": "OK — выбрать эту папку",
    "login.title": "Вход в Aliasarr",
    "login.subtitle": "Требуется логин и пароль для доступа к интерфейсу",
    "login.username": "Логин",
    "login.password": "Пароль",
    "login.btn_submit": "Войти",
    "login.2fa_title": "Двухфакторная проверка",
    "login.2fa_subtitle": "Введите 6-значный код из вашего приложения-аутентификатора или отсканируйте QR",
    "login.btn_verify_2fa": "Подтвердить вход",
    "login.btn_back_to_login": "Назад к логину",
    "users.col_2fa": "2FA TOTP",
    "users.2fa_enabled": "Включено",
    "users.2fa_disabled": "Отключено",
    "settings.2fa_global_title": "Двухфакторная аутентификация (2FA TOTP)",
    "settings.2fa_global_hint": "Защита аккаунтов одноразовыми 6-значными кодами из приложений-аутентификаторов. 2FA запрашивается исключительно при входе через внешний IP-адрес (при входе с приватных IP локальной сети 2FA не запрашивается).",
    "settings.2fa_policy_label": "Режим применения 2FA:",
    "settings.2fa_policy_choice": "Индивидуально (по выбору каждого пользователя)",
    "settings.2fa_policy_enforce": "Обязательно для всех пользователей (при входе через WAN)",
    "profile.tab_2fa": "2FA TOTP",
    "profile.2fa_status_title": "Статус двухфакторной аутентификации:",
    "profile.2fa_status_active": "2FA активирована и защищает учётную запись",
    "profile.2fa_status_inactive": "2FA не настроена",
    "profile.2fa_info": "2FA защищает вашу учётную запись с помощью временных 6-значных кодов. Запрос 2FA происходит только при подключении через внешний IP-адрес (при входе через приватный локальный IP запрос пропускается).",
    "profile.btn_enable_2fa": "Включить 2FA (QR-код)",
    "profile.btn_disable_2fa": "Отключить 2FA",
    "totp.modal_title": "Настройка 2FA TOTP",
    "totp.modal_instruction": "1. Отсканируйте QR-код приложением (Google Authenticator, Authy, Apple Passwords, 1Password, Bitwarden и др.) или введите секретный ключ вручную:",
    "totp.secret_key_label": "Секретный ключ (для ручного ввода):",
    "totp.verify_instruction": "2. Введите 6-значный код из приложения для подтверждения:",
    "totp.btn_activate": "Активировать 2FA",
    "totp.toast_copied": "Секретный ключ скопирован в буфер обмена",
    "totp.toast_activated": "Двухфакторная аутентификация успешно активирована",
    "totp.toast_disabled": "Двухфакторная аутентификация отключена",
    "apikey.title": "Введите API-ключ",
    "apikey.hint": "Ключ выводится в логах контейнера при первом запуске (<span class=\"mono\">docker logs aliasarr</span>) или лежит в файле <span class=\"mono\">/config/api_key.txt</span>.",
    "apikey.btn_submit": "Подключиться",
    "audit.search_placeholder": "Поиск по описанию/действию...",
    "audit.subtitle": "Журнал всех действий пользователей и событий безопасности",
    "profile.apikey_usage_hint": "Запросы с персональным API-ключом выполняются только в пределах прав, разрешённых вашей учётной записи.",
    "profile.modal_title": "Мой профиль",
    "poster_opt.btn_title": "Опции постера",
    "settings.season_folder_placeholder": "Сезон {season}",
    "settings.btn_fix_permissions": "Исправить права доступа (Jellyfin / Plex)",
    "dc.category_placeholder": "Категория / Label (по умолчанию aliasarr)",
    "profile.apikey_none": "API-ключ не создан",
    "profile.new_password_placeholder": "Минимум 4 символа",
    "settings.ssl_modal_title": "Безопасный протокол HTTPS",
    "settings.ssl_address_label": "Адрес для подключения:",
    "settings.ssl_notice_title": "⚠️ Важно для браузера:",
    "settings.ssl_notice_text": "Так как используется встроенный самоподписанный сертификат, при первом открытии браузер покажет предупреждение («Подключение не защищено»). Нажмите «Дополнительно» ➔ «Перейти на сайт» (или «Принять риск и продолжить»).",
    "settings.ssl_btn_goto_https": "Перейти на HTTPS",
    "settings.ssl_btn_goto_http": "Перейти на HTTP",
    "users.btn_setup_2fa": "Настроить 2FA для пользователя",
    "users.btn_disable_2fa": "Сбросить / отключить 2FA",
    "activity.col_speed": "Скорость / ETA",
    "activity.delete_files_label": "Удалить скачанные файлы с диска",
    "activity.remove_title": "Удаление загрузки",
    "settings.extra_file_extensions": "Расширения дополнительных файлов",
    "settings.extra_file_extensions_hint": "Через запятую или пробел, напр. .nfo, .srt, .ass, .jpg",
    "settings.extra_files_hint": "Автоматически переносить сопутствующие файлы (субтитры, nfo, обложки) вместе с видеофайлом",
    "settings.extra_files_title": "Дополнительные файлы",
    "settings.import_extra_files": "Импортировать дополнительные файлы",
    "calendar.ical_step_apple": "<strong>Apple Calendar:</strong> Файл → Новая подписка на календарь → вставьте Webcal ссылку.",
    "calendar.ical_step_google": "<strong>Google Calendar:</strong> Другие календари (+) → Добавить по URL → вставьте HTTPS ссылку.",
    "calendar.ical_step_outlook": "<strong>Outlook:</strong> Добавить календарь → Подписаться из Интернета → вставьте HTTPS ссылку.",
    "calendar.skyhook_default": "Sonarr SkyHook (TVDB Proxy) [По умолчанию]",
    "calendar.radarr_default": "Radarr Movie Cloud (Radarr Hook) [По умолчанию]",
    "audit.action_login": "Вход (Login)",
    "audit.action_logout": "Выход (Logout)",
    "audit.action_password_change": "Смена пароля",
    "audit.action_login_failed": "Неудачный вход",
    "audit.action_user_create": "Создание пользователя",
    "audit.action_user_update": "Изменение пользователя",
    "audit.action_user_delete": "Удаление пользователя",
    "audit.action_password_reset": "Сброс пароля",
    "audit.action_settings_update": "Настройки системы",
    "audit.action_security_update": "Настройки безопасности",
    "audit.action_show_create": "Добавление шоу",
    "audit.action_show_delete": "Удаление шоу",
    "audit.action_release_grab": "Захват релиза",
    "md.skyhook_desc": "Официальный облачный сервис Sonarr. Работает «из коробки» без API-ключей, предоставляет метаданные TheTVDB, TMDB, AniList для сериалов и аниме.",
    "md.radarr_desc": "Официальный облачный сервис Radarr для фильмов. Работает «из коробки» без API-ключей, загружает альтернативные названия (AlternativeTitles), переводы (Translations), постеры, даты кинопроката и цифрового релиза для фильмов.",
    "md.key_placeholder": "API key (опционально для SkyHook/TVMaze)",
    "notif.smtp_server": "SMTP Сервер",
    "notif.port": "Порт",
    "notif.subject_prefix": "Префикс темы",
    "notif.from_email": "От кого (From Email)",
    "notif.to_email": "Кому (To Email)",
    "notif.smtp_username": "Имя пользователя SMTP",
    "notif.smtp_password": "Пароль SMTP",
    "notif.device_id": "Device ID (необязательно)",
    "notif.apprise_server_url": "URL сервера Apprise",
    "notif.tag_optional": "Tag (необязательно)",
    "notif.urls_optional": "URLs / Services (необязательно)",
    "notif.script_path": "Путь к скрипту / исполнимому файлу",
    "notif.script_args": "Аргументы командной строки (необязательно)",
    "cf.preset_label": "Готовый пресет / Шаблон",
    "cf.preset_placeholder": "— Выберите пресет или настройте вручную —",
    "cf.preset_group_quality": "Качество / Источник",
    "cf.builtin_notice": "Штатный формат качества. Вы можете изменять параметры или при необходимости сбросить их к заводским значениям.",
    "timeout.15m": "15 минут",
    "timeout.30m": "30 минут",
    "timeout.1h": "1 час",
    "timeout.4h": "4 часа",
    "timeout.12h": "12 часов",
    "timeout.24h": "24 часа (1 день)",
    "timeout.7d": "7 дней",
    "timeout.30d": "30 дней (по умолчанию)",
    "backup.keep_5": "Хранить последние 5 копий",
    "backup.keep_10": "Хранить последние 10 копий (Стандарт)",
    "backup.keep_20": "Хранить последние 20 копий",
    "backup.keep_50": "Хранить последние 50 копий",
    "backup.keep_unlimited": "Без ограничений (Не удалять старые)",
    "backup.restore_badge_full": "Полный",
    "users.change_avatar_btn": "Сменить аватар",
    "video.delete_permanent_warning": "Файлы и директория медиафайлов будут безвозвратно удалены с диска.",
    "users.2fa_setting_notice": "2FA защищает вашу учётную запись с помощью временных 6-значных кодов. Запрос 2FA происходит только при входе с внешних (WAN) IP-адресов.",
  },
  en: {
    // Navigation & Tabs
    "nav.dashboard": "Dashboard",
    "nav.library": "Library",
    "nav.activity": "Activity",
    "nav.calendar": "Calendar",
    "nav.history": "History",
    "nav.audit": "Audit",
    "nav.settings": "Settings",
    "nav.events": "Events",
    "nav.journal": "Journal",
    "nav.release_logs": "Release Logs",
    "nav.backup": "Backup",
    "nav.wiki": "Wiki",
    "nav.wiki_tooltip": "Knowledge Base & User Documentation",
    "nav.add_video": "+ Add Video",
    "tab.dashboard": "Dashboard",
    "tab.library": "Library",
    "tab.activity": "Activity",
    "tab.calendar": "Calendar",
    "tab.history": "History",
    "tab.audit": "Audit",
    "tab.settings": "Settings",
    "tab.events": "Events",
    "tab.journal": "Journal",
    "tab.release_logs": "Release Logs",
    "tab.backup": "Backup",

    // Subtitles
    "subtitle.dashboard": "Overview and monitoring of your library",
    "subtitle.library": "All your movies, series, and anime with aliases in every language",
    "subtitle.activity": "Current downloads across all download clients",
    "subtitle.calendar": "Air dates for episodes and movie premieres",
    "subtitle.history": "Log of grabbed releases",
    "subtitle.audit": "Security and user activity audit log",
    "subtitle.events": "Application information, warnings, and errors",
    "subtitle.journal": "Application logs (info / warn / debug). Entries older than the retention period are deleted automatically.",
    "subtitle.release_logs": "Diagnostic release engine log: searching, matching, episode parsing, decision making, download client RPC and media imports.",
    "subtitle.backup": "Backup application settings (indexers, download clients, quality profiles, templates, etc.)",

    // Release Logs
    "release_logs.filter_all_stages": "All Stages",
    "release_logs.filter_all_levels": "All Levels",
    "release_logs.search_placeholder": "Search by title or release…",
    "release_logs.col_time": "Time",
    "release_logs.col_stage": "Stage",
    "release_logs.col_level": "Status",
    "release_logs.col_show": "Title",
    "release_logs.col_message": "Message & Decision",
    "release_logs.modal_title": "Release Processing Details",

    // Common actions & words
    "common.save": "Save",
    "common.details": "Details",
    "common.cancel": "Cancel",
    "common.delete": "Delete",
    "common.add": "Add",
    "common.edit": "Edit",
    "common.close": "Close",
    "common.search": "Search",
    "common.confirm": "Confirm",
    "common.refresh": "Refresh",
    "common.browse": "Browse",
    "common.test": "Test",
    "common.apply": "Apply",
    "common.copy": "Copy",
    "common.create": "Create",
    "common.restore": "Restore",
    "common.clear": "Clear",
    "common.actions": "Actions",
    "common.name": "Name",
    "common.type": "Type",
    "common.status": "Status",
    "common.date": "Date",
    "common.size": "Size",
    "common.priority": "Priority",
    "common.enabled": "Enabled",
    "common.importing": "Importing",
    "common.disabled": "Disabled",
    "common.default": "Default",
    "common.menu": "Menu",
    "common.host": "Host",
    "common.port": "Port",
    "common.username": "Username",
    "common.password": "Password",
    "common.loading": "Loading…",
    "common.none": "None",
    "common.all": "All",
    "common.yes": "Yes",
    "common.no": "No",
    "common.page": "Page",
    "common.of": "of",
    "common.total": "total",
    "common.prev": "Back",
    "common.next": "Next",
    "common.any_quality": "Any Quality (no limit)",

    // Statuses
    "status.monitored": "monitored",
    "status.monitored_title": "Monitoring Status",
    "status.unmonitored": "unmonitored",
    "status.missing": "missing",
    "status.wanted": "wanted",
    "status.downloading": "downloading",
    "status.upgrading": "upgrading",
    "status.upgrading_title": "Downloading quality upgrade",
    "status.downloaded": "downloaded",
    "status.ignored": "ignored",
    "status.unaired": "unaired",
    "status.on_air": "on air",
    "status.ended": "ended",
    "status.continuing": "continuing",
    "status.aired": "aired",
    "status.available": "available",
    "status.unavailable": "unavailable",
    "status.unknown": "unknown",

    // Actions
    "action.monitor": "Monitor",
    "action.unmonitor": "Unmonitor",
    "action.monitor_season": "Monitor Season",
    "action.unmonitor_season": "Unmonitor Season",

    // Dashboard
    "dash.btn_refresh": "Refresh",
    "dash.btn_search_wanted": "Search Wanted",
    "dash.card_media": "Media Library",
    "dash.series": "Series",
    "dash.movies": "Movies",
    "dash.anime": "Anime",
    "dash.total": "Total",
    "dash.card_title_status": "Title Status",
    "dash.monitored": "Monitored",
    "dash.unmonitored": "Unmonitored",
    "dash.ended": "Ended",
    "dash.continuing": "Continuing",
    "dash.card_episodes_status": "Episodes & Status",
    "dash.wanted": "Wanted",
    "dash.downloading": "Downloading",
    "dash.downloaded": "Downloaded",
    "dash.unaired": "Unaired",
    "dash.card_files_disk": "Files & Disk",
    "dash.files": "Files",
    "dash.total_size": "Total Size",
    "dash.indexers": "Indexers",
    "dash.download_clients": "Download Clients",
    "dash.upcoming_releases": "Upcoming Releases",
    "dash.full_calendar": "Full Calendar →",
    "dash.recent_grabs": "Recent Grabs",
    "dash.full_history": "Full History →",
    "dash.about_title": "About",
    "dash.system_health": "System Health",
    "health.status_ok": "Healthy",
    "dash.video_count": "videos",
    "dash.episodes_count": "episodes",
    "dash.no_upcoming": "No upcoming releases found",
    "dash.no_grabs": "No releases grabbed yet",

    // Library
    "library.search_placeholder": "Search library…",
    "library.filter_all": "All",
    "library.filter_movies": "Movies",
    "library.filter_series": "Series",
    "library.filter_anime": "Anime",
    "library.filter_monitored": "Monitored",
    "library.filter_unmonitored": "Unmonitored",
    "library.view_posters": "Posters",
    "library.view_table": "Table",
    "library.view_overview": "Overview",
    "library.view_label": "View:",
    "library.poster_options_title": "Poster Options",
    "library.empty": "No videos yet.",
    "library.add_first": "Add your first video",
    "library.col_title": "Title",
    "library.col_network": "Network",
    "library.col_profile": "Quality Profile",
    "library.col_next_air": "Next Airing",
    "library.col_seasons": "Seasons",
    "library.col_episodes": "Episodes",
    "library.no_results": "No results found for query",
    "library.legend_continuing": "Continuing (all episodes downloaded)",
    "library.legend_ended": "Ended (all episodes downloaded)",
    "library.legend_missing_mon": "Missing episodes (series monitored)",
    "library.legend_missing_unmon": "Missing episodes (series unmonitored)",
    "library.legend_downloading": "Downloading (one or more episodes)",

    // Poster Options
    "poster_opt.title": "Poster Options",
    "poster_opt.size": "Poster size",
    "poster_opt.small": "Small",
    "poster_opt.medium": "Medium",
    "poster_opt.large": "Large",
    "poster_opt.progress_text": "Detailed progress bar",
    "poster_opt.progress_text_hint": "Show text on progress bar",
    "poster_opt.show_title": "Show title",
    "poster_opt.show_title_hint": "Show show title under poster",
    "poster_opt.show_monitored": "Show monitored status",
    "poster_opt.show_monitored_hint": "Show monitored status under poster",
    "poster_opt.show_quality": "Show quality profile",
    "poster_opt.show_quality_hint": "Show quality profile under poster",
    "poster_opt.show_tags": "Show tags",
    "poster_opt.show_tags_hint": "Show tags under poster",

    // Activity & History
    "activity.search_wanted": "Search wanted episodes now",
    "activity.check_and_import": "Check & Import",
    "activity.col_name": "Name",
    "activity.col_client": "Client",
    "activity.col_progress": "Progress",
    "activity.col_status": "Status",
    "activity.col_size": "Size",
    "activity.empty": "Queue is empty",
    "activity.delete_title": "Remove from activity and from download client",
    "activity.delete_confirm": "Remove \"{name}\" from activity and from download client (Transmission/qBittorrent)?",
    "activity.deleted_toast": "Removed from download client",
    "history.col_date": "Date",
    "history.col_show": "Video",
    "history.col_release": "Release",
    "history.col_event": "Event",
    "history.empty": "History is empty",
    "history.event.grabbed": "grabbed",
    "history.event.imported": "imported",
    "history.event.failed": "failed",

    // Calendar
    "calendar.today": "Today",
    "calendar.view_month": "Month",
    "calendar.view_week": "Week",
    "calendar.view_forecast": "Forecast",
    "calendar.view_day": "Day",
    "calendar.view_agenda": "Agenda",
    "calendar.filter_all": "All videos",
    "calendar.filter_monitored": "Monitored only",
    "calendar.cat_all": "All Categories",
    "calendar.cat_series": "Series",
    "calendar.cat_movies": "Movies",
    "calendar.cat_anime": "Anime",
    "calendar.status_all": "All Statuses",
    "calendar.status_unaired": "Unaired",
    "calendar.status_on_air": "On Air Today",
    "calendar.status_downloading": "Downloading",
    "calendar.status_missing": "Missing",
    "calendar.status_downloaded": "Downloaded",
    "calendar.btn_search_missing": "Search",
    "calendar.search_missing_title": "Search for missing releases in visible calendar range",
    "calendar.search_missing_confirm": "Start automatic search for all missing episodes and movies in the visible calendar period?",
    "calendar.search_missing_started": "Search triggered for {count} titles ({total} items)",
    "calendar.ical_title": "iCalendar subscription (.ics)",
    "calendar.ical_modal_title": "iCalendar Feed Subscription",
    "calendar.ical_modal_hint": "Use this link to synchronize your Aliasarr release schedule with Google Calendar, Apple Calendar, Outlook, or Thunderbird.",
    "calendar.ical_feed_url": "Calendar link (.ics):",
    "calendar.ical_webcal_url": "Webcal link (Apple / Outlook):",
    "calendar.ical_instructions_title": "How to connect:",
    "calendar.ical_copied": "Link copied to clipboard",
    "calendar.show_cinema": "Movie cinema releases",
    "calendar.show_cinema_hint": "Show cinema release dates with «Cinema» badge",
    "calendar.show_digital": "Movie digital releases",
    "calendar.show_digital_hint": "Show digital (WEB-DL / VOD) release dates with «Digital» badge",
    "calendar.badge_cinema": "Cinema",
    "calendar.badge_digital": "Digital",
    "calendar.badge_physical": "Physical",
    "calendar.btn_auto_search": "Auto Search",
    "calendar.btn_manual_search": "Interactive Search",
    "calendar.btn_open_card": "Open Details",
    "calendar.btn_edit_date": "Edit Date",
    "calendar.events_count": "release(s)",
    "calendar.no_events_in_period": "No scheduled releases in the selected period",
    "calendar.movie_premiere": "Movie Premiere",
    "calendar.badge_today": "Today",
    "calendar.badge_tomorrow": "Tomorrow",
    "calendar.badge_yesterday": "Yesterday",
    "calendar.no_releases_day": "No releases",
    "calendar.settings_title": "Calendar Settings",
    "calendar.section_local": "Local",
    "calendar.collapse_multi": "Collapse multiple episodes",
    "calendar.collapse_multi_hint": "Collapse multiple episodes airing on the same day",
    "calendar.show_info": "Show episode info",
    "calendar.show_info_hint": "Show episode title and number",
    "calendar.finale_badge": "Finale badge",
    "calendar.finale_badge_hint": "Show finale badge based on episode info",
    "calendar.unmet_badge": "Unmet cutoff badge",
    "calendar.unmet_badge_hint": "Show badge on downloaded files if target quality cutoff is not met yet",
    "calendar.full_color": "Full color events",
    "calendar.full_color_hint": "Color entire event with status color rather than just left border. Does not apply to agenda.",
    "calendar.section_global": "Global",
    "calendar.first_day": "First day of week",
    "calendar.monday": "Monday",
    "calendar.sunday": "Sunday",
    "calendar.week_header": "Week column header",
    "calendar.week_header_hint": "Displayed above each column when week view is active",
    "calendar.week_header_opt_mm_dd": "Tue 03/25",
    "calendar.week_header_opt_dd_mm": "Tue 25/03",
    "calendar.week_header_opt_d_m": "Tue 25/3",
    "calendar.week_header_opt_m_d": "Tue 3/25",
    "calendar.time_format": "Time format",
    "calendar.poll_enabled": "Poll metadata source for release dates",
    "calendar.poll_interval": "Poll interval",
    "calendar.poll_interval_hint": "(minutes, only for videos added via metadata search)",
    "calendar.metadata_source": "Calendar metadata source",
    "calendar.metadata_source_hint": "(episode release dates updates)",
    "calendar.metadata_source_series": "Metadata source for series and anime",
    "calendar.metadata_source_series_hint": "(episode release dates updates, default Sonarr SkyHook)",
    "calendar.metadata_source_movie": "Metadata source for movies",
    "calendar.metadata_source_movie_hint": "(movie release dates updates, default Radarr Movie Cloud)",
    "calendar.source_auto": "Auto (show source)",
    "calendar.premiere": "Premiere",
    "calendar.season_finale": "Season Finale",
    "calendar.series_finale": "Series Finale",
    "calendar.waiting_title": "Awaiting release date",
    "calendar.waiting_col_video": "Video",
    "calendar.waiting_col_category": "Category",
    "calendar.waiting_col_expected": "Expected",
    "calendar.btn_refresh_date": "Check release date",
    "calendar.no_scheduled": "No scheduled releases",
    "calendar.more_events": "+{count} more",

    // Settings
    "settingsnav.general": "General",
    "settingsnav.security": "Security",
    "settingsnav.users": "Users",
    "settingsnav.audit": "Audit Log",
    "settingsnav.indexers": "Indexers",
    "settingsnav.download_clients": "Download Clients",
    "settingsnav.quality_profiles": "Quality Profiles",
    "settingsnav.metadata": "Metadata",
    "settingsnav.notifications": "Notifications",
    "settings.apikey_title": "API Key",
    "settings.apikey_label": "API Key",
    "settings.apikey_hint": "used by this web UI and external clients to query the server",
    "settings.apikey_source_env": "Key is set via ALIASARR_API_KEY environment variable — change it in docker-compose.yml to update the key.",
    "settings.apikey_source_auto": "Key was generated automatically. You can generate a new one at any time.",
    "settings.btn_regenerate_key": "↻ New Key",
    "settings.btn_api_docs": "API Docs",
    "settings.interface_title": "Interface",
    "settings.language": "Language",
    "settings.theme": "Theme",
    "settings.theme_dark": "Neon Midnight",
    "settings.theme_dracula": "Dracula",
    "settings.theme_light": "Polar Day",
    "settings.timezone": "Timezone",
    "settings.timezone_hint": "(unified for calendar, journal, and events)",
    "settings.folders_title": "Folders & Category Renaming",
    "settings.btn_templates_cheatsheet": "Template Cheatsheet",
    "settings.folders_hint": "Content category → download folder where client saves files → root library folder where files are moved and renamed according to template. 'Browse' opens directories inside container.",
    "settings.col_category": "Category",
    "settings.col_download_folder": "Download Folder",
    "settings.col_root_folder": "Root Library Folder",
    "settings.col_season_folder": "Season Folder",
    "settings.col_rename_template": "Rename Template",
    "settings.cat_movies": "Movies",
    "settings.cat_series": "Series",
    "settings.cat_anime": "Anime",
    "settings.autosearch_title": "Auto Search & Downloading",
    "settings.min_seeds": "Minimum seeders to download",
    "settings.min_seeds_hint": "(0 — no limit)",
    "settings.prefer_seeded": "Download only the most seeded release",
    "settings.monitor_interval": "Wanted Search auto search interval",
    "settings.monitor_interval_hint": "(minutes)",
    "settings.download_check_interval": "Download completion check interval",
    "settings.download_check_seconds_hint": "(seconds)",
    "settings.tracker_check_interval": "Tracker ongoing check interval",
    "settings.tracker_check_interval_hint": "(minutes)",
    "settings.unaired_check_interval": "Unaired → Wanted activation interval",
    "settings.unaired_check_interval_hint": "(minutes)",
    "settings.security_title": "Security & Authentication",
    "settings.security_hint": "Username and password authentication secures the web interface. External API calls continue via X-Api-Key.",
    "settings.require_login": "Require username and password login",
    "settings.auth_disabled_for_local": "Disabled for Local Addresses",
    "settings.auth_disabled_for_local_hint": "Allows connections from local and private IP addresses (localhost, 127.0.0.1, 192.168.x.x, 10.x.x.x, 172.16-31.x.x) to access the web interface without entering credentials. Only master admin can change this setting.",
    "settings.current_ip": "Your current IP:",
    "settings.local_ip_badge": "Local (no password required)",
    "settings.remote_ip_badge": "External / WAN (password required)",
    "settings.login_username": "Master Admin Username",
    "settings.display_name": "Master Admin Display Name",
    "settings.login_password": "New Admin Password",
    "settings.login_password_hint": "leave blank to keep current password",
    "settings.new_password_placeholder": "New password",
    "settings.session_timeout": "Session timeout (auto log out)",
    "settings.docker_reset_title": "Admin Password Reset in Docker",
    "settings.docker_reset_hint": "If the administrator password is lost or forgotten, reset it from the host machine via one of the following methods:",
    "settings.docker_reset_m1_title": "1. Via Docker terminal command (recommended):",
    "settings.docker_reset_m1_hint": "If the <code class=\"mono\">--password</code> parameter is omitted, the system will generate a secure random password and print it to the console.",
    "settings.docker_reset_m2_title": "2. Via environment variable in docker-compose.yml:",
    "settings.docker_reset_m3_title": "3. Via trigger file in mounted /config directory:",
    "settings.docker_reset_m3_hint": "Create file <code class=\"mono\">/config/reset_admin_password.txt</code> with the new password. On the next container start, Aliasarr will apply the password and remove the file.",

    // SSL / HTTPS
    "settings.ssl_title": "Secure HTTPS Protocol (SSL)",
    "settings.ssl_hint": "Encrypt web traffic using built-in self-signed SSL certificate. Certificate is valid for up to 100 years (36500 days) and automatically auto-renews before expiry.",
    "settings.ssl_enable_label": "Enable HTTPS (SSL)",
    "settings.ssl_port": "HTTPS Port",
    "settings.ssl_auto_renew_label": "Auto-renew before expiration",
    "settings.ssl_cert_details": "Certificate Details",
    "settings.ssl_btn_regenerate": "Regenerate",
    "settings.ssl_btn_save": "Save SSL Settings",
    "settings.ssl_valid_to": "Valid until:",
    "settings.ssl_days_left": "Days left:",
    "settings.ssl_subject": "Subject (SAN):",
    "settings.ssl_fingerprint": "SHA-256 Fingerprint:",
    "settings.toast_ssl_saved": "SSL settings saved successfully",
    "settings.toast_ssl_regenerated": "SSL certificate regenerated successfully for 100 years",

    // Users & RBAC
    "users.add_title": "Add User",
    "users.edit_title": "Edit User: {name}",
    "users.username_placeholder": "Username",
    "users.display_name_placeholder": "Display Name",
    "users.password_placeholder": "Password (minimum 4 characters)",
    "users.is_admin_label": "Administrator permissions (full access)",
    "users.custom_permissions": "Custom permissions:",
    "users.col_username": "User",
    "users.col_role": "Role",
    "users.col_status": "Status",
    "users.col_last_login": "Last Login",
    "users.col_actions": "Actions",
    "users.btn_reset_pwd": "Reset Password",
    "users.modal_reset_title": "Reset User Password",
    "users.active": "Active",
    "users.disabled": "Disabled",
    "users.role_admin": "Administrator",
    "users.role_user": "User",
    "users.role_owner": "Master Admin",
    "users.never_logged_in": "Never",

    // Permissions
    "perm.view_dashboard": "View dashboard",
    "perm.view_library": "View library",
    "perm.manage_library": "Manage library",
    "perm.manual_search": "Manual search & grab",
    "perm.view_calendar": "View calendar",
    "perm.manage_calendar": "Manage calendar dates",
    "perm.view_activity": "View activity / queue",
    "perm.manage_activity": "Manage downloads",
    "perm.view_history": "View history",
    "perm.view_events": "View events",
    "perm.view_journal": "View journal",
    "perm.manage_journal": "Clear & download journal",
    "perm.view_release_logs": "View release logs",
    "perm.manage_release_logs": "Manage release logs",
    "perm.view_audit": "View audit log",
    "perm.manage_settings": "Manage app settings",
    "perm.manage_indexers": "Manage indexers",
    "perm.manage_downloaders": "Manage download clients",
    "perm.manage_users": "Manage users & permissions",
    "perm.manage_backups": "Manage backups",
    "perm.use_api_key": "Personal API key",

    // Profile & Auth
    "auth.logout": "Log out",
    "profile.title": "User Profile",
    "profile.tab_general": "Profile",
    "profile.tab_permissions": "My Permissions",
    "profile.tab_apikey": "API Key",
    "profile.tab_change_password": "Change Password",
    "profile.display_name": "Display Name",
    "profile.display_name_placeholder": "Your name (e.g. Alex)",
    "profile.btn_change_avatar": "Change avatar",
    "profile.btn_remove_avatar": "Remove avatar",
    "profile.btn_generate_key": "↻ New key",
    "profile.btn_revoke_key": "Revoke",
    "profile.apikey_hint": "allows API requests scoped to your assigned permissions (header: X-Api-Key)",
    "profile.apikey_no_permission": "API key usage is disabled for your account. Please contact an administrator for permissions.",
    "profile.current_password": "Current password",
    "profile.new_password": "New password",
    "profile.confirm_password": "Confirm new password",
    "profile.btn_save_password": "Save Password",
    "profile.pwd_changed_toast": "Password updated successfully",
    "profile.pwd_mismatch": "New password and confirmation do not match",
    "profile.pwd_too_short": "Password must be at least 4 characters",
    "profile.avatar_updated": "Avatar updated successfully",
    "profile.avatar_removed": "Avatar removed",

    // Audit Log
    "audit.title": "Audit Log",
    "audit.all_actions": "All actions",
    "audit.col_time": "Time",
    "audit.col_user": "User",
    "audit.col_action": "Action",
    "audit.col_description": "Description",
    "audit.col_ip": "IP Address",
    "audit.empty": "No audit records yet",

    // Indexers
    "indexers.add_title": "Add Indexer",
    "indexers.edit_title": "Edit: {name}",
    "indexers.name_placeholder": "Name, e.g. Rutracker",
    "indexers.url_placeholder": "Base URL (Torznab endpoint)",
    "indexers.key_placeholder": "API key",
    "indexers.priority_placeholder": "Priority (0-1000, lower = higher)",
    "indexers.info_hint": "Supports direct Torznab protocol. Search follows priority strictly (0 = highest, 1000 = lowest). Category restrictions are not used so valid releases are never omitted.",
    "indexers.check_settings_title": "Availability Check Settings",
    "indexers.auto_check": "Automatically check indexer availability",
    "indexers.check_interval": "Check interval",
    "indexers.check_retries": "Retries before marking unavailable",
    "indexers.check_delay": "Retry delay",
    "indexers.col_name": "Name",
    "indexers.col_type": "Type",
    "indexers.col_url": "URL",
    "indexers.col_priority": "Priority",
    "indexers.col_availability": "Availability",
    "indexers.empty": "No indexers added",

    // Download Clients
    "dc.add_title": "Add Download Client",
    "clients.add_title": "Add Download Client",
    "dc.edit_title": "Edit: {name}",
    "dc.host_placeholder": "Host (e.g. qbittorrent or 192.168.1.10)",
    "dc.blackhole_hint": "Path to watch directory on disk:",
    "dc.use_default": "Use as default",
    "dc.seed_time_limit_label": "Seed Time Limit (min, 0 = immediate):",
    "dc.seed_ratio_limit_label": "Seed Ratio Limit:",
    "dc.seed_time_placeholder": "0 (import immediately)",
    "dc.seed_ratio_placeholder": "0 (no limit)",
    "dc.col_name": "Name",
    "dc.col_type": "Type",
    "dc.col_host": "Host",
    "dc.col_availability": "Availability",
    "dc.col_default": "Default",
    "dc.status_available": "Available",
    "dc.status_unavailable": "Unavailable",
    "dc.status_untested": "Not checked",
    "dc.empty": "No download clients added",

    // Quality Profiles & Quality Formats
    "quality.settings_title": "Quality Profiles & Formats",
    "quality.settings_subtitle": "Configure preferred quality, upgrade cutoffs and release scoring",
    "qp.add_title": "Add Quality Profile",
    "quality.add_title": "Add Quality Profile",
    "qp.edit_title": "Edit: {name}",
    "qp.name_placeholder": "Name, e.g. HD-1080p",
    "qp.allowed_label": "Allowed qualities (multiple allowed)",
    "qp.cutoff_quality_label": "Cutoff Quality",
    "qp.cutoff_score_label": "Cutoff Score",
    "qp.upgrade_allowed_label": "Allow automatic upgrade of quality / score until Cutoff is met",
    "qp.col_name": "Name",
    "qp.col_allowed": "Allowed",
    "qp.col_cutoff": "Cutoff",
    "qp.empty": "No quality profiles created",
    "cf.title": "Quality Formats",
    "cf.subtitle": "Rules for recognizing and prioritizing releases (HDR, TrueHD, Proper, Preferred Groups)",
    "cf.add_btn": "Add Format",
    "cf.guide_btn": "Quality Guide",
    "cf.guide_btn_title": "Open quality profiles, quality formats and regex guide in a new tab",
    "cf.col_score": "Score",
    "cf.col_renaming": "In Filename",
    "cf.modal_title": "Quality Format",
    "cf.score_label": "Score",
    "cf.include_renaming": "Include in filename when renaming ({Custom Formats})",
    "cf.regex_pattern": "Release Title Regex",
    "cf.builtin_badge": "Built-in",
    "cf.reset_btn": "Reset to Default",
    "cf.reset_confirm": "Reset this quality format to default factory settings?",
    "cf.cannot_delete_builtin": "Built-in quality formats cannot be deleted",
    "cf.reset_success": "Quality format reset to default settings",

    // Metadata
    "md.add_title": "Add Metadata Source",
    "metadata.add_title": "Add Metadata Source",
    "md.edit_title": "Edit: {name}",
    "md.name_placeholder": "Name, e.g. TMDB or TheTVDB",
    "md.tmdb_how_title": "How to get a TMDB key:",
    "md.tmdb_step1": "Register at <a href=\"https://www.themoviedb.org\" target=\"_blank\" rel=\"noopener\">themoviedb.org</a>",
    "md.tmdb_step2": "Open <a href=\"https://www.themoviedb.org/settings/api\" target=\"_blank\" rel=\"noopener\">Settings → API</a>",
    "md.tmdb_step3": "Copy <strong>Read Access Token (v4 auth)</strong> — this is the long <code>eyJ...</code> string",
    "md.tmdb_important": "<strong>Important:</strong> paste the <em>Read Access Token</em> (<code>eyJ...</code>), not the short API Key v3.",
    "md.thetvdb_title": "TheTVDB API v4:",
    "md.thetvdb_desc": "To use TheTVDB, enter your <strong>API Key v4</strong> from your account at <a href=\"https://thetvdb.com/dashboard/account/api\" target=\"_blank\" rel=\"noopener\">thetvdb.com</a>. If you have a User-supported key with Subscriber PIN, enter your PIN below.",
    "md.pin_placeholder": "Subscriber PIN (optional)",
    "md.tvmaze_title": "TVMaze:",
    "md.tvmaze_desc": "If you have a TVmaze account, for Premium features enter <code>your_username:your_API_key</code>. Key can be found at <a href=\"https://www.tvmaze.com/dashboard\" target=\"_blank\" rel=\"noopener\">tvmaze.com/dashboard</a>.",
    "md.alias_filter_title": "Alias country filter:",
    "md.alias_filter_hint": "If none selected, aliases for all countries are imported.",
    "md.col_name": "Name",
    "md.col_type": "Type",
    "md.empty": "No metadata sources added",

    "md.auto_refresh_title": "Automatic Metadata Refresh",
    "md.auto_refresh_desc": "Regular synchronization with SkyHook/TMDB/TVDB: fetching official titles for unreleased episodes (instead of 'Episode N'), adding newly announced episodes and updating premiere dates.",
    "md.auto_refresh_checkbox": "Enable automatic library metadata refresh",
    "md.refresh_interval_label": "Refresh interval:",
    "md.interval_6h": "Every 6 hours",
    "md.interval_12h": "Every 12 hours",
    "md.interval_24h": "Every 24 hours (1 day)",
    "md.interval_3d": "Every 3 days",
    "md.interval_7d": "Every 1 week (7 days)",
    "md.btn_refresh_now": "Refresh all metadata now",
    "md.btn_refresh_now_title": "Start full metadata refresh for all titles now",
    "md.settings_saved": "Metadata refresh settings saved",
    "md.refresh_started": "Background library metadata refresh started...",
    "library.btn_refresh_all": "Refresh Metadata",
    "library.btn_refresh_all_title": "Refresh all library metadata from the cloud",

    // Countries
    "country.ru": "Russia (RU)",
    "country.us": "United States (US)",
    "country.gb": "United Kingdom (GB)",
    "country.jp": "Japan (JP)",
    "country.kr": "South Korea (KR)",
    "country.cn": "China (CN)",
    "country.fr": "France (FR)",
    "country.de": "Germany (DE)",
    "country.es": "Spain (ES)",
    "country.it": "Italy (IT)",

    // Health
    "health.indexers_enabled": "Enabled indexers: {count}",
    "health.no_indexers": "No enabled indexers — release searching will not work",
    "health.dc_enabled": "Enabled download clients: {count}",
    "health.no_dc": "No enabled download clients — grabbed releases will not be downloaded",
    "health.shows_without_profile": "Videos without quality profile: {count} (any quality will be allowed)",

    // Notifications
    "nt.add_title": "Add Notification",
    "notifications.add_title": "Add Notification",
    "nt.edit_title": "Edit: {name}",
    "nt.enabled": "Enable notification",
    "nt.bot_token_label": "Bot token",
    "nt.bot_token_hint": "(from @BotFather)",
    "nt.chat_id_label": "Chat ID",
    "nt.chat_id_placeholder": "-1001234567890 or 123456789",
    "nt.telegram_thread_id_label": "Topic / Thread ID (optional)",
    "nt.telegram_thread_id_placeholder": "1234",
    "nt.telegram_silent": "Silent",
    "nt.discord_webhook_url_label": "Discord Webhook URL",
    "nt.discord_username_label": "Bot username (optional)",
    "nt.discord_avatar_url_label": "Avatar URL (optional)",
    "nt.gotify_server_url_label": "Gotify Server URL",
    "nt.gotify_app_token_label": "App Token",
    "nt.gotify_priority_label": "Priority (1-10)",
    "nt.ntfy_server_url_label": "Ntfy Server URL (default https://ntfy.sh)",
    "nt.ntfy_topic_label": "Topic",
    "nt.ntfy_token_label": "Access Token (optional for private topics)",
    "nt.ntfy_priority_label": "Priority (1-5)",
    "nt.pushover_user_key_label": "User Key",
    "nt.pushover_api_token_label": "App API Token",
    "nt.pushover_priority_label": "Priority (-2..2)",
    "nt.pushover_sound_label": "Sound (optional)",
    "nt.slack_webhook_url_label": "Slack Webhook URL",
    "nt.slack_channel_label": "Channel (optional, e.g. #downloads)",
    "nt.webhook_url_label": "Webhook URL",
    "nt.webhook_method_label": "HTTP Method",
    "nt.include_app_name": "Include Aliasarr in title",
    "nt.triggers_title": "Notification Triggers:",
    "nt.on_grab": "On Grab",
    "nt.on_import": "On Download / Import",
    "nt.on_upgrade": "On Upgrade",
    "nt.on_rename": "On Rename",
    "nt.on_series_add": "On Series Add",
    "nt.on_series_delete": "On Series Delete",
    "nt.on_file_delete": "On File Delete",
    "nt.on_backup": "On Backup",
    "nt.col_name": "Name",
    "nt.col_type": "Type",
    "nt.col_status": "Status",
    "nt.status_enabled": "Enabled",
    "nt.status_disabled": "Disabled",
    "nt.empty": "No notifications configured",
    "show.delete_modal_title": "Delete Title Card",
    "show.delete_files_label": "Delete card together with files",
    "show.delete_files_hint": "Media files and directory will be permanently removed from disk.",

    // Background Tasks & Operations
    "tasks.widget_tooltip": "Background tasks & operations (click for details)",
    "tasks.idle": "All tasks completed",
    "tasks.popup_title": "Background Tasks",
    "tasks.running_section": "Running Now",
    "tasks.recent_section": "Recent Operations",
    "tasks.no_running": "No active tasks",
    "tasks.no_recent": "Operation history is empty",
    "tasks.clear_history": "Clear",
    "tasks.status_running": "Running",
    "tasks.status_completed": "Completed",
    "tasks.status_failed": "Failed",

    // Events & Journal
    "events.filter_all": "All events",
    "events.filter_info": "Info",
    "events.filter_warning": "Warnings",
    "events.filter_error": "Errors",
    "events.page_size": "Page size:",
    "events.sort_time": "Time ↓",
    "events.col_time": "Time",
    "events.col_component": "Component",
    "events.col_message": "Message",
    "events.empty": "No events",
    "journal.filter_all": "All levels",
    "journal.btn_download": "Download .txt",
    "journal.btn_clear": "Clear",
    "journal.col_time": "Time",
    "journal.col_level": "Level",
    "journal.col_component": "Component",
    "journal.col_message": "Message",
    "journal.retention_title": "Retention",
    "journal.retention_label": "Retain journal & events logs",
    "journal.empty": "No log entries",

    // Backup
    "backup.btn_create": "Create Backup",
    "backup.btn_upload": "Upload Archive",
    "backup.btn_schedule_settings": "Schedule Settings",
    "backup.btn_start_create": "Start Creation",
    "backup.btn_confirm_restore": "Restore Data",
    "backup.btn_restore": "Restore",
    "backup.btn_delete_selected": "Delete Selected",
    "backup.col_file": "File & Type",
    "backup.col_size": "Size",
    "backup.col_contents": "Contents",
    "backup.col_created": "Created",
    "backup.col_actions": "Actions",
    "backup.empty": "No backups yet",
    "backup.stat_total": "Total Backups",
    "backup.stat_latest": "Latest Backup",
    "backup.stat_schedule": "Auto-Backup",
    "backup.stat_storage": "Storage Location",
    "backup.create_title": "Create Backup",
    "backup.create_subtitle": "Select the archive type to save Aliasarr data",
    "backup.type_full_title": "Full Backup (Recommended)",
    "backup.type_full_desc": "Includes entire media library (movies, series, anime, episodes, history, aliases) + quality profiles, custom formats, indexers, download clients, and settings.",
    "backup.type_config_title": "Configuration Only",
    "backup.type_config_desc": "Saves system configuration only: indexers, download clients, quality profiles, custom formats, rename templates, and notifications (excludes media library items).",
    "backup.restore_title": "Restore From Backup",
    "backup.restore_subtitle": "Inspect archive contents and select restoration mode",
    "backup.restore_items_label": "Detected components in archive:",
    "backup.restore_mode_label": "Restoration mode:",
    "backup.safety_snapshot_note": "Before applying changes, Aliasarr will automatically create a safety rollback snapshot of the current database.",
    "backup.mode_auto": "Automatic (according to archive contents)",
    "backup.mode_full": "Full Restore (Library + Configuration)",
    "backup.mode_config": "Configuration Only (Preserve current library)",
    "backup.schedule_title": "Automatic Backup Schedule",
    "backup.schedule_subtitle": "Automatic scheduled backups and retention rotation",
    "backup.schedule_interval_label": "Schedule Interval:",
    "backup.schedule_type_label": "Default Backup Type:",
    "backup.schedule_retention_label": "Retention Count (Max copies):",
    "backup.interval_disabled": "Disabled (Manual only)",
    "backup.interval_daily": "Daily (Every 24 hours)",
    "backup.interval_weekly": "Weekly (Every 7 days)",
    "backup.interval_monthly": "Monthly (Every 30 days)",
    "backup.type_full": "Full (Library + Configuration)",
    "backup.type_config": "Configuration Only",
    "backup.retention_hint": "When the limit is reached, older backup archives will be automatically rotated out.",
    "backup.toast_created": "Backup created successfully",
    "backup.toast_restored": "Data restored successfully from backup",
    "backup.toast_schedule_saved": "Backup schedule settings saved",
    "backup.badge_full": "Full",
    "backup.badge_config": "Config",

    // Templates Guide Modal
    "tpl_guide.title": "Naming Templates Reference Guide",
    "tpl_guide.hint": "Click any preset or token to insert into template. Changes apply to the target field immediately.",
    "tpl_guide.tab_series": "Series",
    "tpl_guide.tab_anime": "Anime",
    "tpl_guide.tab_movie": "Movies",
    "tpl_guide.editor_label": "Template editor:",
    "tpl_guide.target_label": "Target field:",
    "tpl_guide.target_series": "Template — Series",
    "tpl_guide.target_anime": "Template — Anime",
    "tpl_guide.target_movie": "Template — Movie",
    "tpl_guide.default_label": "Default:",
    "tpl_guide.btn_default": "Default",
    "tpl_guide.preview_label": "Preview result:",
    "tpl_guide.presets_title": "Presets (click to apply)",
    "tpl_guide.tokens_title": "Tokens Reference",

    // Show Details Modal
    "show.directory": "Directory:",
    "show.not_set": "Not set",
    "show.btn_sync": "Sync Files",
    "show.present_on_disk": "Present on disk",
    "show.missing_on_disk": "Missing on disk",
    "show.on_disk": "On disk",
    "show.no_overview": "No description available",
    "show.seasons_count": "Seasons",
    "show.next_airing": "Next airing",
    "show.upload_cover": "Upload",
    "show.refresh_cover": "Refresh (Web)",
    "show.new_alias_placeholder": "New alias…",
    "show.force_search": "Force Auto Search",
    "show.search_manual": "Manual Release Search",
    "show.delete_video": "Delete Video",
    "show.confirm_change_category": "Change category? This will update the destination folder and renaming template for future downloads and the card view, but existing files will not be moved automatically.",
    "show.season": "Season",
    "show.download_wanted_episodes": "Download Selected Episodes",
    "show.manual_import": "Manual Import",
    "show.btn_sync": "Library Import",
    "show.sync_tooltip": "Rescan disk files and update library episodes",
    "show.monitor_all_seasons": "Monitor All Seasons",
    "show.unmonitor_all_seasons": "Ignore All Seasons",
    "show.monitor_all_tooltip": "Set all seasons and un-downloaded episodes to monitoring (Wanted)",
    "show.unmonitor_all_tooltip": "Set all seasons and un-downloaded episodes to Ignored",
    "show.monitor_unaired": "Monitor Unaired",
    "show.monitor_unaired_tooltip": "Set all unreleased episodes of the show to 'Wanted' status",
    "show.unaired_monitored": "All unaired episodes set to 'Wanted' status",
    "show.all_seasons_monitored": "All seasons set to monitoring (Wanted)",
    "show.all_seasons_unmonitored": "All seasons set to Ignored",
    "show.preview_rename_title": "Preview Rename & Organize",
    "show.btn_preview_rename": "Rename Files",
    "show.btn_preview_rename_season": "Rename Season",
    "show.expand_all_seasons": "Expand All",
    "show.collapse_all_seasons": "Collapse All",
    "show.rename_relative_hint": "All paths are relative to:",
    "show.rename_template_label": "Naming pattern:",
    "show.rename_select_all": "Select all",
    "show.rename_selected_count": "Selected: {selected} of {total}",
    "show.btn_organize": "Organize",
    "show.rename_no_files": "All files are already named according to the template.",
    "show.rename_success": "Successfully renamed {count} file(s)",
    "show.import_specials": "Import Specials",
    "show.import_specials_tooltip": "Manual mapping and import of downloaded specials",
    "show.import_specials_ready": "Specials downloaded and ready for import!",
    "manual_import.global_btn": "Manual Import",
    "manual_import.title": "Manual File Import",
    "manual_import.title_specials": "Manual Specials Import (Season 0)",
    "manual_import.warn_duplicate": "Warning: this episode is selected in multiple rows!",
    "manual_import.col_show": "Series / Movie",
    "manual_import.select_show": "— Select show —",
    "manual_import.scan": "Scan Folder",
    "manual_import.folder_placeholder": "Path to folder containing downloaded files...",
    "manual_import.mode_label": "Mode:",
    "manual_import.mode_move": "Move",
    "manual_import.mode_copy": "Copy",
    "manual_import.col_file": "Source File",
    "manual_import.col_quality": "Quality",
    "manual_import.col_episode": "Target Episode (Mapping)",
    "manual_import.col_status": "Status",
    "manual_import.skip": "— Do not import (skip) —",
    "manual_import.ready": "Ready",
    "manual_import.overwrite": "Will overwrite existing file",
    "manual_import.not_matched": "Select episode",
    "manual_import.btn_import": "Import Selected",
    "manual_import.no_files": "No video files found in the specified folder",
    "manual_import.summary": "Found files: {total}, selected for import: {selected}",
    "manual_import.success": "Files imported successfully",

    // Add Video Wizard
    "wizard.step_method": "1. Method",
    "wizard.step_search": "2. Search",
    "wizard.step_setup": "3. Setup",
    "wizard.method_metadata_title": "Search via Metadata",
    "wizard.method_metadata_desc": "Aliases and air dates populate automatically.",
    "wizard.method_manual_title": "Add Manually",
    "wizard.method_manual_desc": "Enter title and aliases manually — useful for rare titles without metadata.",
    "wizard.search_placeholder": "Movie, series, or anime title…",
    "wizard.manual_title_label": "Title (Main)",
    "wizard.manual_title_placeholder": "e.g., The Villager of Level 999",
    "wizard.manual_aliases_label": "Aliases, one per line. Format: title | language (ru/en/jp/romaji)",
    "wizard.manual_cover_label": "Poster",
    "wizard.manual_no_cover": "No poster",
    "wizard.manual_upload_cover": "Upload from computer",
    "wizard.manual_cover_url_placeholder": "…or paste image URL",
    "wizard.back": "Back",
    "wizard.next": "Next",
    "wizard.select": "Select",
    "wizard.already_in_library": "Already in library",
    "wizard.category_label": "Category",
    "wizard.category_hint": "(determines download folder and rename template)",
    "wizard.path_label": "Folder path (optional)",
    "wizard.monitor_immediately": "Start monitoring immediately after adding",
    "wizard.autosearch_after_add": "Start auto search for missing after adding",
    "wizard.finish_btn": "Add Video",
    "wizard.toast_no_metadata_source": "Add a metadata source in Settings first",
    "tracker.checking": "Checking releases",
    "search.searching": "Search",
    "md.updating": "Metadata",

    // Dashboard & Calendar & Settings & Backup Toasts / Prompts
    "dash.toast_grabbed_for_shows": "Done: grabbed for {count} video(s)",
    "calendar.prompt_air_date": "\"{title}\"\nEnter new air date (YYYY-MM-DD) or leave blank and click OK to remove from calendar and return to \"Awaiting release date\":",
    "calendar.toast_removed": "Removed from calendar",
    "calendar.toast_invalid_date": "Invalid date",
    "calendar.toast_date_updated": "Date updated",
    "settings.confirm_regenerate_key": "Generate new API key? The previous key will be invalidated — remember to update it in all external clients.",
    "settings.toast_saved": "Settings saved",
    "settings.toast_key_regenerated": "New API key generated and saved in this browser",
    "settings.toast_template_applied": "Template applied to active field",
    "settings.toast_default_template_inserted": "Default template inserted into active field",
    "settings.toast_login_enabled": "Login with username/password enabled",
    "settings.toast_security_saved": "Security settings saved",
    "settings.toast_key_copied": "Key copied to clipboard",
    "backup.confirm_restore": "Restore settings from \"{name}\"? Current indexers, download clients, quality profiles, and templates will be overwritten.",
    "backup.toast_restored": "Settings restored. Refresh the page to apply.",

    // Folder Picker & Login Modals
    "folder_picker.title": "Select Folder",
    "folder_picker.up_title": "Up",
    "folder_picker.new_placeholder": "New folder name…",
    "folder_picker.btn_create": "+ Create",
    "folder_picker.btn_select": "OK — Select this folder",
    "login.title": "Login to Aliasarr",
    "login.subtitle": "Username and password required to access interface",
    "login.username": "Username",
    "login.password": "Password",
    "login.btn_submit": "Log In",
    "login.2fa_title": "Two-Factor Verification",
    "login.2fa_subtitle": "Enter the 6-digit code from your authenticator app or scan QR",
    "login.btn_verify_2fa": "Verify & Sign In",
    "login.btn_back_to_login": "Back to Login",
    "users.col_2fa": "2FA TOTP",
    "users.2fa_enabled": "Enabled",
    "users.2fa_disabled": "Disabled",
    "settings.2fa_global_title": "Two-Factor Authentication (2FA TOTP)",
    "settings.2fa_global_hint": "Protects accounts with time-based 6-digit OTP codes. 2FA is strictly requested when logging in via external/WAN IP addresses (login from private/LAN IP addresses bypasses 2FA).",
    "settings.2fa_policy_label": "2FA Enforcement Policy:",
    "settings.2fa_policy_choice": "Individual (user choice)",
    "settings.2fa_policy_enforce": "Mandatory for all users (on WAN login)",
    "profile.tab_2fa": "2FA TOTP",
    "profile.2fa_status_title": "Two-Factor Authentication Status:",
    "profile.2fa_status_active": "2FA is active and protecting this account",
    "profile.2fa_status_inactive": "2FA is not configured",
    "profile.2fa_info": "2FA protects your account using time-based 6-digit codes. 2FA is prompted only when accessing via external WAN IP addresses (requests from private LAN addresses bypass 2FA).",
    "profile.btn_enable_2fa": "Enable 2FA (QR Code)",
    "profile.btn_disable_2fa": "Disable 2FA",
    "totp.modal_title": "Setup 2FA TOTP",
    "totp.modal_instruction": "1. Scan the QR code with your authenticator app (Google Authenticator, Authy, Apple Passwords, 1Password, Bitwarden, etc.) or enter the secret key manually:",
    "totp.secret_key_label": "Secret Key (for manual entry):",
    "totp.verify_instruction": "2. Enter the 6-digit code from your app to verify and activate:",
    "totp.btn_activate": "Activate 2FA",
    "totp.toast_copied": "Secret key copied to clipboard",
    "totp.toast_activated": "Two-Factor Authentication activated successfully",
    "totp.toast_disabled": "Two-Factor Authentication disabled",
    "apikey.title": "Enter API Key",
    "apikey.hint": "Key is printed in container logs on first launch (<span class=\"mono\">docker logs aliasarr</span>) or located in <span class=\"mono\">/config/api_key.txt</span>.",
    "apikey.btn_submit": "Connect",
    "audit.search_placeholder": "Search by description/action...",
    "audit.subtitle": "Log of all user actions and security events",
    "profile.apikey_usage_hint": "Requests with a personal API key are executed strictly within permissions granted to your account.",
    "profile.modal_title": "My Profile",
    "poster_opt.btn_title": "Poster Options",
    "settings.season_folder_placeholder": "Season {season}",
    "settings.btn_fix_permissions": "Fix Permissions (Jellyfin / Plex)",
    "dc.category_placeholder": "Category / Label (default: aliasarr)",
    "profile.apikey_none": "API key not generated",
    "profile.new_password_placeholder": "At least 4 characters",
    "settings.ssl_modal_title": "Secure HTTPS Protocol",
    "settings.ssl_address_label": "Connection Address:",
    "settings.ssl_notice_title": "⚠️ Important for Browser:",
    "settings.ssl_notice_text": "Since a built-in self-signed certificate is used, your browser will show a warning on first access ('Connection not private'). Click 'Advanced' ➔ 'Proceed to site' (or 'Accept risk and continue').",
    "settings.ssl_btn_goto_https": "Go to HTTPS",
    "settings.ssl_btn_goto_http": "Go to HTTP",
    "users.btn_setup_2fa": "Setup 2FA for user",
    "users.btn_disable_2fa": "Reset / disable 2FA",
    "activity.col_speed": "Speed / ETA",
    "activity.delete_files_label": "Delete downloaded files from disk",
    "activity.remove_title": "Remove Download",
    "settings.extra_file_extensions": "Extra File Extensions",
    "settings.extra_file_extensions_hint": "Comma or space separated, e.g. .nfo, .srt, .ass, .jpg",
    "settings.extra_files_hint": "Automatically import companion files (subtitles, nfo, artwork) alongside video",
    "settings.extra_files_title": "Extra Files",
    "settings.import_extra_files": "Import Extra Files",
    "calendar.ical_step_apple": "<strong>Apple Calendar:</strong> File → New Calendar Subscription → paste Webcal link.",
    "calendar.ical_step_google": "<strong>Google Calendar:</strong> Other calendars (+) → From URL → paste HTTPS link.",
    "calendar.ical_step_outlook": "<strong>Outlook:</strong> Add calendar → Subscribe from web → paste HTTPS link.",
    "calendar.skyhook_default": "Sonarr SkyHook (TVDB Proxy) [Default]",
    "calendar.radarr_default": "Radarr Movie Cloud (Radarr Hook) [Default]",
    "audit.action_login": "Login",
    "audit.action_logout": "Logout",
    "audit.action_password_change": "Password Change",
    "audit.action_login_failed": "Login Failed",
    "audit.action_user_create": "Create User",
    "audit.action_user_update": "Update User",
    "audit.action_user_delete": "Delete User",
    "audit.action_password_reset": "Reset Password",
    "audit.action_settings_update": "System Settings Update",
    "audit.action_security_update": "Security Settings Update",
    "audit.action_show_create": "Add Video",
    "audit.action_show_delete": "Delete Video",
    "audit.action_release_grab": "Release Grabbed",
    "md.skyhook_desc": "Official Sonarr cloud service. Works out of the box without API keys, provides TheTVDB, TMDB, AniList metadata for TV shows and anime.",
    "md.radarr_desc": "Official Radarr cloud service for movies. Works out of the box without API keys, retrieves AlternativeTitles, Translations, posters, theatrical and digital release dates for movies.",
    "md.key_placeholder": "API key (optional for SkyHook/TVMaze)",
    "notif.smtp_server": "SMTP Server",
    "notif.port": "Port",
    "notif.subject_prefix": "Subject Prefix",
    "notif.from_email": "From Email",
    "notif.to_email": "To Email",
    "notif.smtp_username": "SMTP Username",
    "notif.smtp_password": "SMTP Password",
    "notif.device_id": "Device ID (optional)",
    "notif.apprise_server_url": "Apprise Server URL",
    "notif.tag_optional": "Tag (optional)",
    "notif.urls_optional": "URLs / Services (optional)",
    "notif.script_path": "Path to script / executable",
    "notif.script_args": "Command line arguments (optional)",
    "cf.preset_label": "Preset / Template",
    "cf.preset_placeholder": "— Select a preset or configure manually —",
    "cf.preset_group_quality": "Quality / Source",
    "cf.builtin_notice": "Built-in custom format. You can customize parameters or reset to factory defaults if needed.",
    "timeout.15m": "15 minutes",
    "timeout.30m": "30 minutes",
    "timeout.1h": "1 hour",
    "timeout.4h": "4 hours",
    "timeout.12h": "12 hours",
    "timeout.24h": "24 hours (1 day)",
    "timeout.7d": "7 days",
    "timeout.30d": "30 days (default)",
    "backup.keep_5": "Keep latest 5 backups",
    "backup.keep_10": "Keep latest 10 backups (Standard)",
    "backup.keep_20": "Keep latest 20 backups",
    "backup.keep_50": "Keep latest 50 backups",
    "backup.keep_unlimited": "Unlimited (Do not delete old)",
    "backup.restore_badge_full": "Full",
    "users.change_avatar_btn": "Change Avatar",
    "video.delete_permanent_warning": "Files and the media folder will be permanently deleted from disk.",
    "users.2fa_setting_notice": "2FA protects your account using temporary 6-digit TOTP codes. Verification is requested when logging in from external (WAN) IPs.",
  },
};
let CURRENT_LANG = "ru";
// Часовой пояс приложения — единый для календаря, журнала и событий.
// Даты в БД хранятся в UTC; конвертация — только при выводе через formatDateTZ().
let APP_TIMEZONE = localStorage.getItem("vbeacon_timezone") || "UTC";

function formatDateTZ(value, options) {
  if (!value) return "—";
  try {
    let dStr = value;
    if (typeof dStr === "string") {
      if (dStr.includes(" ") && !dStr.includes("T")) {
        dStr = dStr.replace(" ", "T");
      }
      if (dStr.includes("T") && !dStr.endsWith("Z")) {
        dStr += "Z";
      }
    }
    const locale = CURRENT_LANG === "en" ? "en-US" : "ru-RU";
    return new Intl.DateTimeFormat(locale, Object.assign({
      timeZone: APP_TIMEZONE, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    }, options || {})).format(new Date(dStr));
  } catch (e) {
    return new Date(value).toLocaleString(CURRENT_LANG === "en" ? "en-US" : "ru-RU");
  }
}

const formatTimezoneDate = formatDateTZ;

function formatDateOnly(value) {
  if (!value) return "—";
  try {
    const locale = CURRENT_LANG === "en" ? "en-US" : "ru-RU";
    return new Date(value).toLocaleDateString(locale, { year: "numeric", month: "2-digit", day: "2-digit" });
  } catch (e) {
    return "—";
  }
}

function tzDayKey(date) {
  return date.toDateString();
}

// t(key, params) — глобальная функция локализации с поддержкой интерполяции {param}
function t(key, params) {
  const dict = TRANSLATIONS[CURRENT_LANG] || TRANSLATIONS.ru;
  let val = dict[key] || (TRANSLATIONS.ru[key]) || key;
  if (params && typeof params === "object") {
    for (const [k, v] of Object.entries(params)) {
      val = val.replaceAll("{" + k + "}", v);
    }
  }
  return val;
}

// Переводит значение EpisodeStatus enum в локализованный статус
function episodeStatusLabel(status) {
  return t("status." + status);
}

function openQualityGuide(event, hash) {
  if (event) event.preventDefault();
  const targetHash = hash ? (hash.startsWith("#") ? hash : "#" + hash) : "#section-qualities";
  const url = "/wiki" + targetHash;
  window.open(url, "_blank");
}

function openWiki(event, hash) {
  if (event) {
    event.stopPropagation();
  }
  const targetHash = hash ? (hash.startsWith("#") ? hash : "#" + hash) : "";
  window.open("/wiki" + targetHash, "_blank");
  if (event) event.preventDefault();
}

function applyLanguage(lang) {
  CURRENT_LANG = (lang === "en") ? "en" : "ru";
  document.documentElement.setAttribute("lang", CURRENT_LANG);
  try {
    localStorage.setItem("vbeacon_lang", CURRENT_LANG);
    localStorage.setItem("aliasarr_lang", CURRENT_LANG);
  } catch (e) {}

  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    const dict = TRANSLATIONS[CURRENT_LANG] || TRANSLATIONS.ru;
    const val = dict[key];
    if (val !== undefined && val !== null) {
      if (val.includes("<") && val.includes(">")) {
        el.innerHTML = val;
      } else {
        el.textContent = val;
      }
    }
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    const val = t(el.getAttribute("data-i18n-placeholder"));
    if (val) el.setAttribute("placeholder", val);
  });
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    const val = t(el.getAttribute("data-i18n-title"));
    if (val) el.setAttribute("title", val);
  });

  // Обновляем текущий активный вид, только если панель уже активна в DOM
  const activeNav = document.querySelector(".nav-item.active");
  const hashTab = (window.location.hash || "").replace("#", "");
  const tabId = activeNav?.dataset?.tab || hashTab || localStorage.getItem("aliasarr_last_tab");
  if (tabId && document.getElementById("tab-" + tabId)?.classList.contains("active")) {
    if (tabId === "dashboard") loadDashboard();
    else if (tabId === "library") renderLibrary();
    else if (tabId === "calendar") loadCalendar();
    else if (tabId === "history") loadHistory();
    else if (tabId === "activity") loadQueue();
    else if (tabId === "events") loadEvents(EVENTS_STATE.page);
    else if (tabId === "journal") loadJournal(JOURNAL_STATE.page);
    else if (tabId === "backup") loadBackups();
  }

  // Если открыто модальное окно деталей — обновляем его содержимое
  if (document.getElementById("show-modal")?.classList.contains("active") && CURRENT_SHOW_ID) {
    refreshShowModal();
  }

  checkConnection();
}

// ---------- API helper ----------
async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  const sessionToken = sessionStorage.getItem("aliasarr_session_token") || localStorage.getItem("aliasarr_session_token");
  if (sessionToken && !headers["Authorization"]) {
    headers["Authorization"] = `Bearer ${sessionToken}`;
  }
  if (API_KEY) headers["X-Api-Key"] = API_KEY;

  const resp = await fetch(API_BASE + path, Object.assign({}, options, { headers }));

  if (resp.status === 401) {
    showLoginScreen();
    throw new Error("unauthorized");
  }
  if (!resp.ok) {
    let detail = "";
    try { const body = await resp.json(); detail = body.detail || body.error || ""; } catch (e) {}
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

// ---------- Button loading helper ----------
async function withLoading(button, fn) {
  if (!button) return fn();
  button.classList.add("is-loading");
  button.disabled = true;
  try {
    return await fn();
  } finally {
    button.classList.remove("is-loading");
    button.disabled = false;
  }
}

// ---------- Modal system ----------
function openModal(id) { document.getElementById(id).classList.add("active"); }
function closeModal(id) {
  document.getElementById(id).classList.remove("active");
  if (id === "show-modal" && typeof SHOW_MODAL_POLL_INTERVAL !== 'undefined' && SHOW_MODAL_POLL_INTERVAL) {
    clearInterval(SHOW_MODAL_POLL_INTERVAL);
  }
}

function confirmModal(message, { danger = true } = {}) {
  return new Promise((resolve) => {
    document.getElementById("confirm-message").textContent = message;
    const okBtn = document.getElementById("confirm-ok-btn");
    const cancelBtn = document.getElementById("confirm-cancel-btn");
    okBtn.className = "btn btn-solid " + (danger ? "btn-danger" : "btn-primary");

    const cleanup = () => {
      okBtn.onclick = null; cancelBtn.onclick = null;
      closeModal("confirm-modal");
    };
    okBtn.onclick = () => { cleanup(); resolve(true); };
    cancelBtn.onclick = () => { cleanup(); resolve(false); };
    openModal("confirm-modal");
  });
}


// ---------- User Profile & Auth State ----------
let CURRENT_USER = null;

function hasPermission(perm) {
  if (!CURRENT_USER) return true;
  if (CURRENT_USER.is_owner || CURRENT_USER.is_admin) return true;
  if (!CURRENT_USER.permissions) return false;
  return !!CURRENT_USER.permissions[perm];
}

function applyUserPermissionsToUI() {
  if (!CURRENT_USER) return;

  // 1. Sidebar navigation items
  const navDashboard = document.querySelector('.sidebar nav [data-tab="dashboard"]');
  if (navDashboard) navDashboard.style.display = hasPermission("view_dashboard") ? "" : "none";

  const navLibrary = document.querySelector('.sidebar nav [data-tab="library"]');
  if (navLibrary) navLibrary.style.display = hasPermission("view_library") ? "" : "none";

  const navCalendar = document.querySelector('.sidebar nav [data-tab="calendar"]');
  if (navCalendar) navCalendar.style.display = hasPermission("view_calendar") ? "" : "none";

  const navActivity = document.querySelector('.sidebar nav [data-tab="activity"]');
  if (navActivity) navActivity.style.display = hasPermission("view_activity") ? "" : "none";

  const navHistory = document.querySelector('.sidebar nav [data-tab="history"]');
  if (navHistory) navHistory.style.display = hasPermission("view_history") ? "" : "none";

  const navEvents = document.querySelector('.sidebar nav [data-tab="events"]');
  if (navEvents) navEvents.style.display = hasPermission("view_events") ? "" : "none";

  const navJournal = document.querySelector('.sidebar nav [data-tab="journal"]');
  if (navJournal) navJournal.style.display = hasPermission("view_journal") ? "" : "none";

  const navAudit = document.querySelector('.sidebar nav [data-tab="audit"]');
  if (navAudit) navAudit.style.display = hasPermission("view_audit") ? "" : "none";

  const navReleaseLogs = document.querySelector('.sidebar nav [data-tab="release-logs"]');
  if (navReleaseLogs) {
    const canSeeRelLogs = hasPermission("view_release_logs") || hasPermission("manage_release_logs");
    navReleaseLogs.style.display = canSeeRelLogs ? "" : "none";
  }

  const btnRelLogsClear = document.getElementById("release-logs-clear-btn");
  if (btnRelLogsClear) btnRelLogsClear.style.display = hasPermission("manage_release_logs") ? "" : "none";

  const btnRelLogsDl = document.getElementById("release-logs-download-btn");
  if (btnRelLogsDl) btnRelLogsDl.style.display = (hasPermission("view_release_logs") || hasPermission("manage_release_logs")) ? "" : "none";

  const navBackup = document.querySelector('.sidebar nav [data-tab="backup"]');
  if (navBackup) navBackup.style.display = hasPermission("manage_backups") ? "" : "none";

  const canSeeSettings = hasPermission("manage_settings") || hasPermission("manage_indexers") || hasPermission("manage_downloaders") || hasPermission("manage_users");
  const navSettings = document.querySelector('.sidebar nav [data-tab="settings"]');
  if (navSettings) navSettings.style.display = canSeeSettings ? "" : "none";

  // 2. Settings subtabs
  const tabGeneral = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="general"]');
  const tabSecurity = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="security"]');
  const tabQuality = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="quality"]');
  const tabMetadata = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="metadata"]');
  const tabNotifications = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="notifications"]');
  const tabUsers = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="users"]');
  const tabIndexers = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="indexers"]');
  const tabDownloaders = document.querySelector('#tab-settings .settings-tab-btn[data-settings-tab="download-clients"]');

  const hasSettingsPerm = hasPermission("manage_settings");
  if (tabGeneral) tabGeneral.style.display = hasSettingsPerm ? "" : "none";
  if (tabSecurity) tabSecurity.style.display = hasSettingsPerm ? "" : "none";
  if (tabQuality) tabQuality.style.display = hasSettingsPerm ? "" : "none";
  if (tabMetadata) tabMetadata.style.display = hasSettingsPerm ? "" : "none";
  if (tabNotifications) tabNotifications.style.display = hasSettingsPerm ? "" : "none";
  if (tabUsers) tabUsers.style.display = hasPermission("manage_users") ? "" : "none";
  if (tabIndexers) tabIndexers.style.display = hasPermission("manage_indexers") ? "" : "none";
  if (tabDownloaders) tabDownloaders.style.display = hasPermission("manage_downloaders") ? "" : "none";

  // System API key card in General Settings - strictly for Master Admin
  const cardSystemApiKey = document.getElementById("card-system-apikey");
  if (cardSystemApiKey) {
    cardSystemApiKey.style.display = (CURRENT_USER && CURRENT_USER.is_owner) ? "" : "none";
  }

  // 3. Add Show buttons across UI
  const canManageLib = hasPermission("manage_library");
  document.querySelectorAll('[onclick*="openAddShowWizard"]').forEach(el => {
    el.style.display = canManageLib ? "" : "none";
  });

  // 4. Wanted search all button
  const btnSearchWanted = document.getElementById("wanted-search-btn");
  if (btnSearchWanted) btnSearchWanted.style.display = hasPermission("manual_search") ? "" : "none";

  // 5. Active tab fallback if currently on forbidden tab
  const activeNav = document.querySelector('.sidebar nav .nav-item.active');
  const hashTab = (window.location.hash || "").replace("#", "");
  const currentActiveTab = activeNav?.dataset?.tab || hashTab || localStorage.getItem("aliasarr_last_tab") || "dashboard";

  const tabPermMap = {
    dashboard: "view_dashboard",
    library: "view_library",
    calendar: "view_calendar",
    activity: "view_activity",
    history: "view_history",
    events: "view_events",
    journal: "view_journal",
    "release-logs": "view_release_logs",
    audit: "view_audit",
    backup: "manage_backups",
  };

  const isCurrentTabAllowed = currentActiveTab === "settings"
    ? canSeeSettings
    : currentActiveTab === "release-logs"
    ? (hasPermission("view_release_logs") || hasPermission("manage_release_logs"))
    : (tabPermMap[currentActiveTab] ? hasPermission(tabPermMap[currentActiveTab]) : true);

  if (!isCurrentTabAllowed) {
    const candidateTabs = ["dashboard", "library", "calendar", "activity", "history", "events", "journal", "release-logs", "audit", "backup", "settings"];
    for (const t of candidateTabs) {
      const allowed = t === "settings" ? canSeeSettings : (t === "release-logs" ? (hasPermission("view_release_logs") || hasPermission("manage_release_logs")) : hasPermission(tabPermMap[t]));
      if (allowed && t !== currentActiveTab) {
        switchTab(t);
        break;
      }
    }
  }
}

function updateUserProfileUI(user) {
  const badge = document.getElementById("user-profile-badge");
  if (!badge) return;
  if (!user) {
    badge.style.display = "none";
    return;
  }
  badge.style.display = "flex";
  const nameEl = document.getElementById("sidebar-user-name");
  if (nameEl) nameEl.textContent = user.display_name || user.username;
  
  const roleBadge = document.getElementById("sidebar-user-role-badge");
  if (roleBadge) {
    roleBadge.textContent = user.is_owner ? t("users.role_owner") : (user.is_admin ? t("users.role_admin") : t("users.role_user"));
    roleBadge.className = "user-role-badge " + (user.is_admin ? "admin" : "user");
  }

  const avatarImg = document.getElementById("sidebar-user-avatar-img");
  const avatarInit = document.getElementById("sidebar-user-avatar-initial");
  const mobAvatarImg = document.getElementById("mobile-user-avatar-img");
  const mobAvatarInit = document.getElementById("mobile-user-avatar-initial");

  const initialChar = (user.display_name || user.username || "A").charAt(0).toUpperCase();

  if (user.avatar) {
    if (avatarImg) { avatarImg.src = user.avatar; avatarImg.style.display = "block"; }
    if (avatarInit) avatarInit.style.display = "none";
    if (mobAvatarImg) { mobAvatarImg.src = user.avatar; mobAvatarImg.style.display = "block"; }
    if (mobAvatarInit) mobAvatarInit.style.display = "none";
  } else {
    if (avatarImg) avatarImg.style.display = "none";
    if (avatarInit) {
      avatarInit.style.display = "block";
      avatarInit.textContent = initialChar;
    }
    if (mobAvatarImg) mobAvatarImg.style.display = "none";
    if (mobAvatarInit) {
      mobAvatarInit.style.display = "block";
      mobAvatarInit.textContent = initialChar;
    }
  }

  applyUserPermissionsToUI();
}

function openProfileModal() {
  if (!CURRENT_USER) return;
  const u = CURRENT_USER;
  const dispTitle = document.getElementById("profile-modal-display-name");
  if (dispTitle) dispTitle.textContent = u.display_name || u.username;
  
  const userSub = document.getElementById("profile-modal-username");
  if (userSub) userSub.textContent = "@" + u.username;
  
  const inpUser = document.getElementById("profile-input-username");
  if (inpUser) inpUser.value = u.username;
  
  const inpDisp = document.getElementById("profile-input-display-name");
  if (inpDisp) inpDisp.value = u.display_name || "";

  const timeoutSel = document.getElementById("profile-input-session-timeout");
  if (timeoutSel) timeoutSel.value = String(u.session_timeout_minutes || 43200);
  
  const roleBadge = document.getElementById("profile-modal-role");
  if (roleBadge) {
    roleBadge.textContent = u.is_owner ? t("users.role_owner") : (u.is_admin ? t("users.role_admin") : t("users.role_user"));
    roleBadge.className = "user-role-badge " + (u.is_admin ? "admin" : "user");
  }

  const avatarImg = document.getElementById("profile-modal-avatar-img");
  const avatarInit = document.getElementById("profile-modal-avatar-initial");
  const btnRemove = document.getElementById("profile-btn-remove-avatar");
  if (u.avatar) {
    if (avatarImg) { avatarImg.src = u.avatar; avatarImg.style.display = "block"; }
    if (avatarInit) avatarInit.style.display = "none";
    if (btnRemove) btnRemove.style.display = "inline-block";
  } else {
    if (avatarImg) avatarImg.style.display = "none";
    if (avatarInit) {
      avatarInit.style.display = "block";
      avatarInit.textContent = (u.display_name || u.username || "A").charAt(0).toUpperCase();
    }
    if (btnRemove) btnRemove.style.display = "none";
  }

  // Permissions list (all 19 permissions)
  const permsBox = document.getElementById("profile-permissions-list");
  if (permsBox) {
    const allPerms = [
      { key: "view_dashboard", label: t("perm.view_dashboard") },
      { key: "view_library", label: t("perm.view_library") },
      { key: "manage_library", label: t("perm.manage_library") },
      { key: "manual_search", label: t("perm.manual_search") },
      { key: "view_calendar", label: t("perm.view_calendar") },
      { key: "manage_calendar", label: t("perm.manage_calendar") },
      { key: "view_activity", label: t("perm.view_activity") },
      { key: "manage_activity", label: t("perm.manage_activity") },
      { key: "view_history", label: t("perm.view_history") },
      { key: "view_events", label: t("perm.view_events") },
      { key: "view_journal", label: t("perm.view_journal") },
      { key: "manage_journal", label: t("perm.manage_journal") },
      { key: "view_release_logs", label: t("perm.view_release_logs") },
      { key: "manage_release_logs", label: t("perm.manage_release_logs") },
      { key: "view_audit", label: t("perm.view_audit") },
      { key: "manage_settings", label: t("perm.manage_settings") },
      { key: "manage_indexers", label: t("perm.manage_indexers") },
      { key: "manage_downloaders", label: t("perm.manage_downloaders") },
      { key: "manage_users", label: t("perm.manage_users") },
      { key: "manage_backups", label: t("perm.manage_backups") },
      { key: "use_api_key", label: t("perm.use_api_key") },
    ];

    permsBox.innerHTML = allPerms.map(p => {
      const isAllowed = u.is_admin || (u.permissions && u.permissions[p.key]);
      const iconHtml = isAllowed
        ? `<i data-lucide="check" class="ico-sm" style="color:var(--accent); vertical-align:middle; margin-right:6px;"></i>`
        : `<i data-lucide="x" class="ico-sm" style="color:var(--text-muted); vertical-align:middle; margin-right:6px;"></i>`;
      return `
        <div class="perm-item ${isAllowed ? "allowed" : "denied"}" style="display:flex; align-items:center;">
          ${iconHtml}
          <span>${escapeHtml(p.label)}</span>
        </div>
      `;
    }).join("");
    if (window.lucide) lucide.createIcons();
  }

  loadMyApiKey();
  switchProfileSubtab("general");
  openModal("profile-modal");
}

let TOTP_SETUP_TARGET_USER_ID = null; // null для текущего профиля, number для настройки админом другого пользователя

function switchProfileSubtab(tab) {
  const btnGeneral = document.getElementById("btn-ptab-general");
  const btnPerms = document.getElementById("btn-ptab-perms");
  const btnApiKey = document.getElementById("btn-ptab-apikey");
  const btn2FA = document.getElementById("btn-ptab-2fa");
  const btnPwd = document.getElementById("btn-ptab-pwd");
  if (btnGeneral) btnGeneral.classList.toggle("active", tab === "general");
  if (btnPerms) btnPerms.classList.toggle("active", tab === "perms");
  if (btnApiKey) btnApiKey.classList.toggle("active", tab === "apikey");
  if (btn2FA) btn2FA.classList.toggle("active", tab === "2fa");
  if (btnPwd) btnPwd.classList.toggle("active", tab === "pwd");

  const tabGeneral = document.getElementById("ptab-general");
  const tabPerms = document.getElementById("ptab-perms");
  const tabApiKey = document.getElementById("ptab-apikey");
  const tab2FA = document.getElementById("ptab-2fa");
  const tabPwd = document.getElementById("ptab-pwd");
  if (tabGeneral) tabGeneral.style.display = tab === "general" ? "block" : "none";
  if (tabPerms) tabPerms.style.display = tab === "perms" ? "block" : "none";
  if (tabApiKey) tabApiKey.style.display = tab === "apikey" ? "block" : "none";
  if (tab2FA) tab2FA.style.display = tab === "2fa" ? "block" : "none";
  if (tabPwd) tabPwd.style.display = tab === "pwd" ? "block" : "none";

  if (tab === "2fa") {
    loadMy2FAStatus();
  }
}

async function loadMy2FAStatus() {
  if (!CURRENT_USER) return;
  try {
    const me = await api("/api/v1/auth/me");
    CURRENT_USER = me;
  } catch (e) {}

  const is2FA = !!CURRENT_USER.totp_enabled;
  const badgeEl = document.getElementById("profile-2fa-badge");
  const descEl = document.getElementById("profile-2fa-status-desc");
  const enableBtn = document.getElementById("profile-2fa-enable-btn");
  const disableBtn = document.getElementById("profile-2fa-disable-btn");

  if (badgeEl) {
    badgeEl.className = is2FA ? "badge badge-success" : "badge badge-secondary";
    badgeEl.textContent = is2FA ? t("users.2fa_enabled") : t("users.2fa_disabled");
  }
  if (descEl) {
    descEl.textContent = is2FA ? t("profile.2fa_status_active") : t("profile.2fa_status_inactive");
  }
  if (enableBtn) enableBtn.style.display = is2FA ? "none" : "inline-flex";
  if (disableBtn) disableBtn.style.display = is2FA ? "inline-flex" : "none";
  if (window.lucide) lucide.createIcons();
}

async function openMy2FASetupModal() {
  TOTP_SETUP_TARGET_USER_ID = null;
  const modalTitle = document.getElementById("totp-setup-modal-title");
  if (modalTitle) modalTitle.textContent = `${t("totp.modal_title")} (@${CURRENT_USER.username})`;
  const errEl = document.getElementById("totp-setup-error");
  if (errEl) errEl.style.display = "none";
  const codeInp = document.getElementById("totp-verify-code");
  if (codeInp) codeInp.value = "";

  try {
    const data = await api("/api/v1/auth/2fa/setup", { method: "POST" });
    document.getElementById("totp-qr-img").src = data.qr_code_svg;
    document.getElementById("totp-secret-text").value = data.secret;
    openModal("totp-setup-modal");
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    toast(formatToastMessage(e.message), true);
  }
}

async function adminSetupUser2FA(userId, username) {
  TOTP_SETUP_TARGET_USER_ID = userId;
  const modalTitle = document.getElementById("totp-setup-modal-title");
  if (modalTitle) modalTitle.textContent = `${t("totp.modal_title")} (@${username})`;
  const errEl = document.getElementById("totp-setup-error");
  if (errEl) errEl.style.display = "none";
  const codeInp = document.getElementById("totp-verify-code");
  if (codeInp) codeInp.value = "";

  try {
    const data = await api(`/api/v1/users/${userId}/2fa/setup`, { method: "POST" });
    document.getElementById("totp-qr-img").src = data.qr_code_svg;
    document.getElementById("totp-secret-text").value = data.secret;
    openModal("totp-setup-modal");
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    toast(formatToastMessage(e.message), true);
  }
}

function copyTotpSecret() {
  const secret = document.getElementById("totp-secret-text")?.value || "";
  if (!secret) return;
  copyTextToClipboard(secret);
  toast(t("totp.toast_copied"));
}

async function submitConfirm2FASetup() {
  const secret = document.getElementById("totp-secret-text")?.value || "";
  const code = (document.getElementById("totp-verify-code")?.value || "").trim();
  const btn = document.getElementById("totp-setup-confirm-btn");
  const errEl = document.getElementById("totp-setup-error");
  if (errEl) errEl.style.display = "none";

  if (!code) {
    if (errEl) {
      errEl.textContent = CURRENT_LANG === "en" ? "Enter the 6-digit verification code" : "Введите 6-значный проверочный код";
      errEl.style.display = "block";
    }
    return;
  }

  await withLoading(btn, async () => {
    try {
      if (TOTP_SETUP_TARGET_USER_ID) {
        await api(`/api/v1/users/${TOTP_SETUP_TARGET_USER_ID}/2fa/confirm`, {
          method: "POST",
          body: JSON.stringify({ secret, code }),
        });
        toast(t("totp.toast_activated"));
        closeModal("totp-setup-modal");
        loadUsers();
      } else {
        const res = await api("/api/v1/auth/2fa/confirm", {
          method: "POST",
          body: JSON.stringify({ secret, code }),
        });
        if (res.user) CURRENT_USER = res.user;
        toast(t("totp.toast_activated"));
        closeModal("totp-setup-modal");
        loadMy2FAStatus();
      }
    } catch (e) {
      if (errEl) {
        errEl.textContent = formatToastMessage(e.message);
        errEl.style.display = "block";
      }
    }
  });
}

async function disableMy2FA(btn) {
  const confirmed = await confirmModal(
    CURRENT_LANG === "en" ? "Disable Two-Factor Authentication (2FA) for your account?" : "Отключить двухфакторную аутентификацию (2FA) для вашей учётной записи?",
    { danger: true }
  );
  if (!confirmed) return;

  await withLoading(btn, async () => {
    try {
      const res = await api("/api/v1/auth/2fa/disable", { method: "POST" });
      if (res.user) CURRENT_USER = res.user;
      toast(t("totp.toast_disabled"));
      loadMy2FAStatus();
    } catch (e) {
      toast(formatToastMessage(e.message), true);
    }
  });
}

async function adminResetUser2FA(userId, username) {
  const confirmed = await confirmModal(
    CURRENT_LANG === "en" ? `Disable 2FA TOTP for user @${username}?` : `Отключить 2FA TOTP для пользователя @${username}?`,
    { danger: true }
  );
  if (!confirmed) return;

  try {
    await api(`/api/v1/users/${userId}/2fa/reset`, { method: "POST" });
    toast(t("totp.toast_disabled"));
    loadUsers();
  } catch (e) {
    toast(formatToastMessage(e.message), true);
  }
}

async function loadMyApiKey() {
  if (!CURRENT_USER) return;
  const canUse = CURRENT_USER.is_owner || CURRENT_USER.is_admin || (CURRENT_USER.permissions && CURRENT_USER.permissions.use_api_key);
  const enabledBox = document.getElementById("profile-apikey-enabled-box");
  const disabledBox = document.getElementById("profile-apikey-disabled-box");
  const inpKey = document.getElementById("profile-my-apikey");
  const btnRevoke = document.getElementById("profile-revoke-key-btn");
  const btnCopy = document.getElementById("profile-copy-key-btn");

  if (!canUse) {
    if (enabledBox) enabledBox.style.display = "none";
    if (disabledBox) disabledBox.style.display = "block";
    return;
  }

  if (enabledBox) enabledBox.style.display = "flex";
  if (disabledBox) disabledBox.style.display = "none";

  try {
    const data = await api("/api/v1/auth/my-api-key");
    const key = data.api_key || "";
    if (inpKey) inpKey.value = key;
    if (btnRevoke) btnRevoke.style.display = key ? "inline-block" : "none";
    if (btnCopy) btnCopy.style.display = key ? "inline-block" : "none";
    if (CURRENT_USER) CURRENT_USER.api_key = key;
  } catch (err) {
    console.error("Failed to load personal API key:", err);
  }
}

async function regenerateMyApiKey(btn) {
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/v1/auth/regenerate-my-api-key", { method: "POST" });
    const inpKey = document.getElementById("profile-my-apikey");
    const btnRevoke = document.getElementById("profile-revoke-key-btn");
    const btnCopy = document.getElementById("profile-copy-key-btn");
    if (inpKey) inpKey.value = data.api_key || "";
    if (btnRevoke) btnRevoke.style.display = "inline-block";
    if (btnCopy) btnCopy.style.display = "inline-block";
    if (CURRENT_USER) CURRENT_USER.api_key = data.api_key;
    toast(t("settings.toast_key_regenerated"));
  } catch (err) {
    toast(formatToastMessage(err.message), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function revokeMyApiKey(btn) {
  const confirmed = await confirmModal(
    CURRENT_LANG === "en" ? "Revoke your personal API key? All applications using it will lose access." : "Отозвать ваш персональный API-ключ? Все внешние клиенты с этим ключом потеряют доступ."
  );
  if (!confirmed) return;

  if (btn) btn.disabled = true;
  try {
    await api("/api/v1/auth/revoke-my-api-key", { method: "DELETE" });
    const inpKey = document.getElementById("profile-my-apikey");
    const btnRevoke = document.getElementById("profile-revoke-key-btn");
    const btnCopy = document.getElementById("profile-copy-key-btn");
    if (inpKey) inpKey.value = "";
    if (btnRevoke) btnRevoke.style.display = "none";
    if (btnCopy) btnCopy.style.display = "none";
    if (CURRENT_USER) CURRENT_USER.api_key = null;
    toast(CURRENT_LANG === "en" ? "API key revoked" : "API-ключ отозван");
  } catch (err) {
    toast(formatToastMessage(err.message), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function copyMyApiKey() {
  const inpKey = document.getElementById("profile-my-apikey");
  if (!inpKey || !inpKey.value) return;
  navigator.clipboard.writeText(inpKey.value);
  toast(t("settings.toast_key_copied"));
}

async function submitUpdateMyProfile() {
  const inp = document.getElementById("profile-input-display-name");
  const timeoutSel = document.getElementById("profile-input-session-timeout");
  const displayName = inp ? inp.value.trim() : "";
  const sessionTimeout = timeoutSel ? Number(timeoutSel.value) || 43200 : 43200;

  try {
    const updated = await api("/api/v1/auth/me", {
      method: "PUT",
      body: JSON.stringify({ 
        display_name: displayName,
        session_timeout_minutes: sessionTimeout,
      }),
    });
    if (CURRENT_USER) {
      CURRENT_USER.display_name = updated.display_name;
      CURRENT_USER.session_timeout_minutes = updated.session_timeout_minutes;
      updateUserProfileUI(CURRENT_USER);
      const dispTitle = document.getElementById("profile-modal-display-name");
      if (dispTitle) dispTitle.textContent = updated.display_name || updated.username;
    }
    toast(t("settings.toast_saved"));
    if (document.getElementById("tab-settings")?.classList.contains("active")) {
      loadUsers();
      loadSecuritySettings();
    }
  } catch (err) {
    toast(formatToastMessage(err.message), true);
  }
}

const submitUpdateMyDisplayName = submitUpdateMyProfile;

function handleAvatarFileSelect(event) {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    toast(CURRENT_LANG === "en" ? "Image size should not exceed 2MB" : "Размер изображения не должен превышать 2 МБ", true);
    return;
  }
  const reader = new FileReader();
  reader.onload = async (e) => {
    const dataUrl = e.target.result;
    try {
      const resp = await api("/api/v1/auth/me/avatar", {
        method: "POST",
        body: JSON.stringify({ avatar: dataUrl }),
      });
      if (CURRENT_USER) {
        CURRENT_USER.avatar = resp.avatar;
        updateUserProfileUI(CURRENT_USER);
        openProfileModal();
      }
      toast(t("profile.avatar_updated"));
    } catch (err) {
      toast(formatToastMessage(err.message), true);
    }
  };
  reader.readAsDataURL(file);
}

async function removeMyAvatar() {
  try {
    await api("/api/v1/auth/me/avatar", {
      method: "POST",
      body: JSON.stringify({ avatar: null }),
    });
    if (CURRENT_USER) {
      CURRENT_USER.avatar = null;
      updateUserProfileUI(CURRENT_USER);
      openProfileModal();
    }
    toast(t("profile.avatar_removed"));
  } catch (err) {
    toast(formatToastMessage(err.message), true);
  }
}

async function submitChangePassword() {
  const current_password = document.getElementById("profile-current-pwd").value;
  const new_password = document.getElementById("profile-new-pwd").value;
  const confirm_password = document.getElementById("profile-confirm-pwd").value;

  if (!current_password) {
    toast(CURRENT_LANG === "en" ? "Enter current password" : "Укажите текущий пароль", true);
    return;
  }
  if (!new_password || new_password.length < 4) {
    toast(t("profile.pwd_too_short"), true);
    return;
  }
  if (new_password !== confirm_password) {
    toast(t("profile.pwd_mismatch"), true);
    return;
  }

  try {
    await api("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    });
    toast(t("profile.pwd_changed_toast"));
    document.getElementById("profile-current-pwd").value = "";
    document.getElementById("profile-new-pwd").value = "";
    document.getElementById("profile-confirm-pwd").value = "";
    closeModal("profile-modal");
  } catch (err) {
    toast(formatToastMessage(err.message), true);
  }
}

async function logoutUser() {
  const confirmed = await confirmModal(t("auth.logout") + "?", { danger: false });
  if (!confirmed) return;
  try {
    await fetch("/api/v1/auth/logout", { method: "POST" });
  } catch (e) {}
  CURRENT_USER = null;
  API_KEY = "";
  localStorage.removeItem("aliasarr_api_key");
  sessionStorage.removeItem("aliasarr_session_token");
  localStorage.removeItem("aliasarr_session_token");
  updateUserProfileUI(null);
  location.reload();
}

// ---------- Login screen ----------
function showLoginScreen() {
  document.getElementById("login-screen").classList.add("active");
}
function hideLoginScreen() {
  document.getElementById("login-screen").classList.remove("active");
}

async function checkAuthStatus() {
  try {
    const headers = {};
    const sessionToken = sessionStorage.getItem("aliasarr_session_token") || localStorage.getItem("aliasarr_session_token");
    if (sessionToken) headers["Authorization"] = `Bearer ${sessionToken}`;
    if (API_KEY) headers["X-Api-Key"] = API_KEY;

    const status = await fetch("/api/v1/auth/status", { headers }).then(r => r.json());
    if (status.authenticated && status.user) {
      CURRENT_USER = status.user;
      if (status.api_key || (status.user && status.user.api_key)) {
        API_KEY = status.api_key || status.user.api_key;
        localStorage.setItem("aliasarr_api_key", API_KEY);
      } else {
        API_KEY = "";
        localStorage.removeItem("aliasarr_api_key");
      }
      updateUserProfileUI(CURRENT_USER);
      hideLoginScreen();
      return false; // Already authenticated, no login needed
    }
    if (status.login_required || !status.authenticated) {
      showLoginScreen();
      return true; // Login required
    }
  } catch (e) {
    console.error("checkAuthStatus error:", e);
  }
  return false;
}

let CURRENT_PRE_AUTH_TOKEN = "";

async function submitLogin(triggerEl) {
  const button = document.getElementById("login-submit-btn");
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  const errorEl = document.getElementById("login-error");
  errorEl.style.display = "none";

  await withLoading(button, async () => {
    try {
      const resp = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        errorEl.textContent = formatToastMessage(body.detail || (CURRENT_LANG === "en" ? "Invalid username or password" : "Неверный логин или пароль"));
        errorEl.style.display = "block";
        return;
      }
      const data = await resp.json();

      // Если требуется шаг 2FA TOTP (при входе через внешний IP):
      if (data.requires_2fa) {
        CURRENT_PRE_AUTH_TOKEN = data.temp_token;
        const credsBox = document.getElementById("login-step-credentials");
        const step2fa = document.getElementById("login-step-2fa");
        if (credsBox) credsBox.style.display = "none";
        if (step2fa) step2fa.style.display = "block";
        const codeInput = document.getElementById("login-2fa-code");
        if (codeInput) {
          codeInput.value = "";
          codeInput.focus();
        }
        const err2fa = document.getElementById("login-2fa-error");
        if (err2fa) err2fa.style.display = "none";
        if (window.lucide) lucide.createIcons();
        return;
      }

      CURRENT_USER = data.user;
      if (data.token) {
        sessionStorage.setItem("aliasarr_session_token", data.token);
        localStorage.setItem("aliasarr_session_token", data.token);
      }
      if (data.api_key || (data.user && data.user.api_key)) {
        API_KEY = data.api_key || data.user.api_key;
        localStorage.setItem("aliasarr_api_key", API_KEY);
      } else {
        API_KEY = "";
        localStorage.removeItem("aliasarr_api_key");
      }
      updateUserProfileUI(CURRENT_USER);
      hideLoginScreen();
      startApp();
    } catch (e) {
      errorEl.textContent = CURRENT_LANG === "en" ? "Failed to connect to server" : "Не удалось связаться с сервером";
      errorEl.style.display = "block";
    }
  });
}

function cancelLogin2FA() {
  CURRENT_PRE_AUTH_TOKEN = "";
  const credsBox = document.getElementById("login-step-credentials");
  const step2fa = document.getElementById("login-step-2fa");
  if (step2fa) step2fa.style.display = "none";
  if (credsBox) credsBox.style.display = "block";
  const pwdInp = document.getElementById("login-password");
  if (pwdInp) {
    pwdInp.value = "";
    pwdInp.focus();
  }
}

async function submitLogin2FA(triggerEl) {
  const button = document.getElementById("login-2fa-submit-btn");
  const code = (document.getElementById("login-2fa-code")?.value || "").trim();
  const errorEl = document.getElementById("login-2fa-error");
  if (errorEl) errorEl.style.display = "none";

  if (!code) {
    if (errorEl) {
      errorEl.textContent = CURRENT_LANG === "en" ? "Please enter the 6-digit code" : "Введите 6-значный код";
      errorEl.style.display = "block";
    }
    return;
  }

  await withLoading(button, async () => {
    try {
      const resp = await fetch("/api/v1/auth/login-2fa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ temp_token: CURRENT_PRE_AUTH_TOKEN, code }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        if (errorEl) {
          errorEl.textContent = formatToastMessage(body.detail || (CURRENT_LANG === "en" ? "Invalid 2FA code" : "Неверный код 2FA"));
          errorEl.style.display = "block";
        }
        return;
      }
      const data = await resp.json();
      CURRENT_USER = data.user;
      if (data.token) {
        sessionStorage.setItem("aliasarr_session_token", data.token);
        localStorage.setItem("aliasarr_session_token", data.token);
      }
      if (data.api_key || (data.user && data.user.api_key)) {
        API_KEY = data.api_key || data.user.api_key;
        localStorage.setItem("aliasarr_api_key", API_KEY);
      } else {
        API_KEY = "";
        localStorage.removeItem("aliasarr_api_key");
      }
      updateUserProfileUI(CURRENT_USER);
      hideLoginScreen();
      startApp();
    } catch (e) {
      if (errorEl) {
        errorEl.textContent = CURRENT_LANG === "en" ? "Failed to verify 2FA code" : "Ошибка проверки 2FA кода";
        errorEl.style.display = "block";
      }
    }
  });
}

// ---------- Toast ----------
function formatToastMessage(message) {
  if (!message) return "";
  let text = String(message);
  if (CURRENT_LANG !== "en") return text;

  // General error and action prefixes
  text = text
    .replace(/^Ошибка:\s*/i, "Error: ")
    .replace(/^Ошибка загрузки:\s*/i, "Loading error: ")
    .replace(/^Ошибка загрузки настроек:\s*/i, "Settings load error: ")
    .replace(/^Ошибка автопоиска:\s*/i, "Auto-search error: ")
    .replace(/^Ошибка скачивания:\s*/i, "Download error: ")
    .replace(/^Ошибка сохранения настроек опроса:\s*/i, "Poll settings save error: ")
    .replace(/^Ошибка сохранения настроек:\s*/i, "Settings save error: ")
    .replace(/^Ошибка сохранения:\s*/i, "Save error: ")
    .replace(/^Ошибка восстановления:\s*/i, "Restore error: ")
    .replace(/^Ошибка удаления:\s*/i, "Deletion error: ")
    .replace(/^Ошибка обновления:\s*/i, "Update error: ")
    .replace(/^Ошибка обновления прав:\s*/i, "Error updating permissions: ")
    .replace(/^Ошибка анализа файла архива:\s*/i, "Archive analysis error: ")
    .replace(/^Постер обновлён из\s*/i, "Cover updated from ")
    .replace(/^Постер обновлен из\s*/i, "Cover updated from ")
    .replace(/^Подтверждено:\s*/i, "Confirmed: ");

  // Standalone success & info messages
  const exactTranslations = {
    "Настройки сохранены": "Settings saved",
    "Настройки успешно сохранены": "Settings saved successfully",
    "Журнал очищен": "Journal cleared",
    "Логи релизов очищены": "Release logs cleared",
    "События очищены": "Events cleared",
    "Резервная копия создана": "Backup created",
    "Резервная копия удалена": "Backup deleted",
    "Настройки восстановлены": "Settings restored",
    "Алиас добавлен": "Alias added",
    "Алиас удален": "Alias deleted",
    "Алиас удалён": "Alias deleted",
    "Индексатор добавлен": "Indexer added",
    "Индексатор сохранен": "Indexer saved",
    "Индексатор сохранён": "Indexer saved",
    "Индексатор удален": "Indexer deleted",
    "Индексатор удалён": "Indexer deleted",
    "Клиент загрузки добавлен": "Download client added",
    "Клиент загрузки сохранен": "Download client saved",
    "Клиент загрузки сохранён": "Download client saved",
    "Клиент загрузки удален": "Download client deleted",
    "Клиент загрузки удалён": "Download client deleted",
    "Профиль сохранен": "Profile saved",
    "Профиль сохранён": "Profile saved",
    "Профиль удален": "Profile deleted",
    "Профиль удалён": "Profile deleted",
    "Формат качества добавлен": "Quality format added",
    "Формат качества сохранен": "Quality format saved",
    "Формат качества сохранён": "Quality format saved",
    "Формат удален": "Format deleted",
    "Формат удалён": "Format deleted",
    "Укажите название формата": "Enter format name",
    "Уведомление сохранено": "Notification saved",
    "Уведомление удалено": "Notification deleted",
    "Тестовое уведомление отправлено": "Test notification sent",
    "Постер не найден": "Cover not found",
    "Пользователь создан": "User created",
    "Пользователь обновлен": "User updated",
    "Пользователь обновлён": "User updated",
    "Пользователь удален": "User deleted",
    "Пользователь удалён": "User deleted",
    "Пароль успешно изменен": "Password changed successfully",
    "Пароль успешно изменён": "Password changed successfully",
    "Папка добавлена": "Folder added",
    "Папка удалена": "Folder deleted",
    "Источник метаданных добавлен": "Metadata source added",
    "Источник метаданных сохранен": "Metadata source saved",
    "Источник метаданных сохранён": "Metadata source saved",
    "Источник метаданных удален": "Metadata source deleted",
    "Источник метаданных удалён": "Metadata source deleted",
    "Права доступа обновлены": "Permissions updated",
    "Права медиатеки обновлены": "Media permissions updated",
    "Не выбрано ни одной серии": "No episodes selected",
    "Записи старше указанного срока удалены": "Entries older than specified retention deleted",
  };
  if (exactTranslations[text.trim()]) {
    return exactTranslations[text.trim()];
  }

  // Backend API HTTPException messages & common phrases
  text = text
    .replace(/Шоу «(.*?)» уже добавлено в библиотеку \(id=(\d+)\)/g, 'Video "$1" is already in library (id=$2)')
    .replace(/content_type должен быть movie, series или anime/g, "content_type must be movie, series or anime")
    .replace(/Внутренняя ошибка при импорте:\s*(.*)/g, "Internal import error: $1")
    .replace(/Текст алиаса не может быть пустым/g, "Alias text cannot be empty")
    .replace(/Не выбрано ни одной серии/g, "No episodes selected")
    .replace(/Серии не найдены/g, "Episodes not found")
    .replace(/У данного видео не задана директория \(настройте папки библиотек в Настройки -> Папки\)/g, "No directory set for this video (configure root folders in Settings -> Folders)")
    .replace(/Директория «(.*?)» не существует на диске/g, 'Directory "$1" does not exist on disk')
    .replace(/language должен быть 'ru' или 'en'/g, "language must be 'ru' or 'en'")
    .replace(/theme должна быть 'dark', 'light' или 'dracula'/g, "theme must be 'dark', 'light' or 'dracula'")
    .replace(/min_seeds не может быть отрицательным/g, "min_seeds cannot be negative")
    .replace(/Интервал должен быть не меньше 1 минуты/g, "Interval must be at least 1 minute")
    .replace(/Число попыток должно быть не меньше 1/g, "Number of retries must be at least 1")
    .replace(/Срок хранения должен быть не меньше 1 дня/g, "Retention period must be at least 1 day")
    .replace(/Размер страницы должен быть не меньше 5/g, "Page size must be at least 5")
    .replace(/Интервал опроса должен быть не меньше 5 минут/g, "Poll interval must be at least 5 minutes")
    .replace(/Некорректный уровень события/g, "Invalid event level")
    .replace(/Некорректный уровень лога/g, "Invalid log level")
    .replace(/Резервная копия не найдена/g, "Backup not found")
    .replace(/Некорректный файл резервной копии:\s*(.*)/g, "Invalid backup file: $1")
    .replace(/Папка не найдена:\s*(.*)/g, "Folder not found: $1")
    .replace(/Нет доступа к папке:\s*(.*)/g, "No access to folder: $1")
    .replace(/Путь должен быть абсолютным/g, "Path must be absolute")
    .replace(/Не удалось создать папку:\s*(.*)/g, "Failed to create folder: $1")
    .replace(/Вход по логину\/паролю не включён/g, "Login with password is not enabled")
    .replace(/Пароль ещё не задан — настройте его в Настройках перед включением входа/g, "Password is not set yet — configure it in Settings first")
    .replace(/Неверный логин или пароль/g, "Invalid username or password")
    .replace(/Укажите пароль, чтобы включить вход по логину\/паролю/g, "Specify password to enable login")
    .replace(/Нет ни одного включённого индексатора/g, "No enabled indexers")
    .replace(/Нет настроенного и включённого download client/g, "No configured and enabled download client")
    .replace(/Не удалось отправить релиз в download client:\s*(.*)/g, "Failed to send release to download client: $1")
    .replace(/Видео не найдено/g, "Video not found")
    .replace(/Шоу не найдено/g, "Show not found")
    .replace(/Серия не найдена/g, "Episode not found")
    .replace(/У этого сезона ещё нет серий — сначала добавьте их через метаданные/g, "This season has no episodes yet — add them via metadata first")
    .replace(/Раздача не найдена ни в одном из включённых download client'ов/g, "Torrent not found in any enabled download client")
    .replace(/Не удалось связаться с сервером/g, "Failed to connect to server");

  return text;
}

let TOAST_TIMEOUT_ID = null;

function toast(message, isError = false) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  if (TOAST_TIMEOUT_ID) {
    clearTimeout(TOAST_TIMEOUT_ID);
    TOAST_TIMEOUT_ID = null;
  }
  const formatted = formatToastMessage(message);
  const iconHtml = isError 
    ? '<i data-lucide="alert-circle" style="color:var(--danger, #f43f5e); width:20px; height:20px; flex-shrink:0;"></i>'
    : '<i data-lucide="check-circle" style="color:var(--teal, #2dd4bf); width:20px; height:20px; flex-shrink:0;"></i>';
  
  el.innerHTML = `${iconHtml}<span>${escapeHtml(formatted)}</span>`;
  el.className = "toast show" + (isError ? " error" : "");
  if (window.lucide) lucide.createIcons();
  
  TOAST_TIMEOUT_ID = setTimeout(() => {
    el.className = "toast";
    TOAST_TIMEOUT_ID = null;
  }, 4000);
}

function showInlineStatus(elementId, message, isSuccess = true) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const icon = isSuccess ? '<i data-lucide="check-circle" class="ico-sm"></i>' : '<i data-lucide="alert-triangle" class="ico-sm"></i>';
  el.className = "inline-status-box " + (isSuccess ? "success" : "error");
  el.innerHTML = `${icon}<span>${escapeHtml(formatToastMessage(message))}</span>`;
  el.style.display = "flex";
  if (window.lucide) lucide.createIcons();
}

function clearInlineStatus(elementId) {
  const el = document.getElementById(elementId);
  if (el) {
    el.style.display = "none";
    el.innerHTML = "";
  }
}

// ---------- Tabs ----------
let QUEUE_POLL_INTERVAL = null;
let DASHBOARD_POLL_INTERVAL = null;

// Перерисовывает данные текущей открытой вкладки — используется после смены
// языка, чтобы статусы/подписи, сгенерированные JS (не через data-i18n),
// обновились без ручного перехода между вкладками.
function refreshActiveTab() {
  const activePanel = document.querySelector(".tab-panel.active");
  if (!activePanel) return;
  const tabId = activePanel.id.replace(/^tab-/, "");
  if (tabId === "dashboard") loadDashboard();
  else if (tabId === "library") loadShows();
  else if (tabId === "calendar") loadCalendar();
  else if (tabId === "history") loadHistory();
  else if (tabId === "settings") loadAllSettings();
  else if (tabId === "activity") loadQueue();
}

// ---------- Mobile Detection & Menu Navigation ----------
function isMobileDevice() {
  return (
    window.innerWidth <= 1024 ||
    /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints > 0 && window.innerWidth <= 1024)
  );
}

let _lastCalendarIsMobile = window.innerWidth <= 768;
function updateMobileState() {
  const isMobile = isMobileDevice();
  document.documentElement.classList.toggle("is-mobile", isMobile);
  document.body.classList.toggle("is-mobile-body", isMobile);
  if (!isMobile) {
    closeMobileMenu();
  }
  const curCalIsMobile = window.innerWidth <= 768;
  if (curCalIsMobile !== _lastCalendarIsMobile) {
    _lastCalendarIsMobile = curCalIsMobile;
    const calTab = document.getElementById("tab-calendar");
    if (calTab && calTab.classList.contains("active")) {
      loadCalendar();
    }
  }
}

function toggleMobileMenu() {
  const sidebar = document.querySelector(".sidebar");
  if (!sidebar) return;
  if (sidebar.classList.contains("mobile-open")) {
    closeMobileMenu();
  } else {
    openMobileMenu();
  }
}

function openMobileMenu() {
  const sidebar = document.querySelector(".sidebar");
  const backdrop = document.getElementById("mobile-sidebar-backdrop");
  if (sidebar) sidebar.classList.add("mobile-open");
  if (backdrop) backdrop.classList.add("active");
  document.body.style.overflow = "hidden";
  if (window.lucide) lucide.createIcons();
}

function closeMobileMenu() {
  const sidebar = document.querySelector(".sidebar");
  const backdrop = document.getElementById("mobile-sidebar-backdrop");
  if (sidebar) sidebar.classList.remove("mobile-open");
  if (backdrop) backdrop.classList.remove("active");
  document.body.style.overflow = "";
}

window.addEventListener("resize", updateMobileState);
window.addEventListener("orientationchange", updateMobileState);

function switchTab(tabId) {
  if (!tabId || typeof tabId !== "string" || tabId === "undefined") return;
  const targetPanel = document.getElementById("tab-" + tabId);
  if (!targetPanel) return;

  const initStyle = document.getElementById("initial-tab-style");
  if (initStyle) initStyle.remove();

  window.history.replaceState(null, null, "#" + tabId);
  try {
    localStorage.setItem("aliasarr_last_tab", tabId);
  } catch (e) {}

  document.querySelectorAll(".nav-item[data-tab]").forEach(el => el.classList.toggle("active", el.dataset.tab === tabId));
  document.querySelectorAll(".mobile-bottom-item[data-tab]").forEach(el => el.classList.toggle("active", el.dataset.tab === tabId));
  document.querySelectorAll(".tab-panel").forEach(el => el.classList.toggle("active", el.id === "tab-" + tabId));
  
  closeMobileMenu();
  window.scrollTo({ top: 0, behavior: "instant" });

  if (tabId === "dashboard") {
    loadDashboard();
    if (DASHBOARD_POLL_INTERVAL) clearInterval(DASHBOARD_POLL_INTERVAL);
    DASHBOARD_POLL_INTERVAL = setInterval(loadDashboard, 15000);
  } else if (DASHBOARD_POLL_INTERVAL) {
    clearInterval(DASHBOARD_POLL_INTERVAL);
    DASHBOARD_POLL_INTERVAL = null;
  }

  if (tabId === "library") loadShows();
  if (tabId === "calendar") loadCalendar();
  if (tabId === "history") loadHistory();
  if (tabId === "audit") loadAuditLogs(1);
  if (tabId === "settings") loadAllSettings();
  if (tabId === "events") loadEvents();
  if (tabId === "journal") loadJournal();
  if (tabId === "release-logs") loadReleaseLogs(1);
  if (tabId === "backup") loadBackups();

  if (tabId === "activity") {
    loadQueue();
    if (QUEUE_POLL_INTERVAL) clearInterval(QUEUE_POLL_INTERVAL);
    QUEUE_POLL_INTERVAL = setInterval(loadQueue, 3000);
  } else if (QUEUE_POLL_INTERVAL) {
    clearInterval(QUEUE_POLL_INTERVAL);
    QUEUE_POLL_INTERVAL = null;
  }
}

document.querySelectorAll(".nav-item[data-tab]").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.querySelectorAll(".settings-tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".settings-tab-btn").forEach(b => b.classList.toggle("active", b === btn));
    const targetTab = btn.dataset.settingsTab;
    document.querySelectorAll(".settings-panel").forEach(p =>
      p.classList.toggle("active", p.id === "settings-" + targetTab)
    );
    if (targetTab === "metadata") loadMetadataSources();
    else if (targetTab === "indexers") loadIndexers();
    else if (targetTab === "download-clients") loadDownloadClients();
    else if (targetTab === "quality") loadQualityProfiles();
    else if (targetTab === "notifications") loadNotifications();
    else if (targetTab === "general") loadGeneralSettings();
    else if (targetTab === "security") loadSecuritySettings();
    else if (targetTab === "users") loadUsers();
  });
});

// ---------- Connection status ----------
async function checkConnection() {
  const el = document.getElementById("conn-status");
  if (!el) return;
  try {
    const r = await fetch("/api/v1/health");
    if (r.ok) {
      el.textContent = CURRENT_LANG === "en" ? "● connected" : "● подключено";
      el.className = "conn-status conn-ok";
    } else throw new Error();
  } catch (e) {
    el.textContent = CURRENT_LANG === "en" ? "● no connection" : "● нет соединения";
    el.className = "conn-status conn-error";
  }
}

function escapeHtml(s) {
  return (s || "").toString().replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function formatSize(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0, val = bytes;
  while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
  return `${val.toFixed(1)} ${units[i]}`;
}

function setElText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function pad(n) { return String(n).padStart(2, "0"); }

// =============================================================================
// DASHBOARD
// =============================================================================

async function triggerWantedSearch(btn) {
  await withLoading(btn, async () => {
    try {
      const res = await api("/api/v1/search/wanted", { method: "POST" });
      toast(`${t("common.confirm")}: ${res.grabbed_shows || 0}`, false);
      await loadDashboard();
    } catch (e) {
      toast("Ошибка: " + e.message, true);
    }
  });
}

async function loadDashboard() {
  try {
    const stats = await api("/api/v1/stats");
    const totalShows = stats.total_shows || 0;

    // Медиатека
    setElText("stat-shows", `${totalShows} ${t("dash.video_count")}`);
    setElText("stat-shows-sub", totalShows);
    setElText("stat-series", stats.series || 0);
    setElText("stat-movies", stats.movies || 0);
    setElText("stat-anime", stats.anime || 0);

    // Статус тайтлов
    const monitored = stats.monitored || 0;
    setElText("stat-monitored-main", `${monitored} / ${totalShows}`);
    setElText("stat-monitored", monitored);
    setElText("stat-unmonitored", stats.unmonitored || 0);
    setElText("stat-ended", stats.ended || 0);
    setElText("stat-continuing", stats.continuing || 0);

    // Эпизоды и загрузки
    setElText("stat-episodes", `${stats.total_episodes || 0} ${t("dash.episodes_count")}`);
    setElText("stat-wanted", stats.wanted || 0);
    setElText("stat-downloading", stats.downloading || 0);
    setElText("stat-downloaded", stats.downloaded || 0);
    setElText("stat-unaired", stats.unaired || 0);

    // Файлы и Диск
    const sizeStr = formatSize(stats.total_size_bytes || 0);
    setElText("stat-size", sizeStr);
    setElText("stat-size-sub", sizeStr);
    setElText("stat-files", stats.total_files || 0);
    setElText("stat-indexers", stats.indexers_count || 0);
    setElText("stat-clients", stats.download_clients_count || 0);

    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  } catch (e) {}

  try {
    const entries = (await api("/api/v1/calendar?days_forward=10&days_back=0")).slice(0, 6);
    const el = document.getElementById("dash-calendar");
    el.innerHTML = entries.map(e => `
      <div class="simple-list-row" onclick="openShowModal(${e.show_id})" style="cursor:pointer;" title="${escapeHtml(e.show_title)}">
        <span>${escapeHtml(e.show_title)} ${e.season != null && e.episode != null ? `<span class="muted">S${pad(e.season)}E${pad(e.episode)}</span>` : ''}</span>
        <span class="muted">${formatDateOnly(e.air_date)}</span>
      </div>`).join("") || `<div class="simple-list-empty">${t("dash.no_upcoming")}</div>`;
  } catch (e) {}

  try {
    const entries = (await api("/api/v1/history?limit=6"));
    const el = document.getElementById("dash-history");
    el.innerHTML = entries.map(e => `
      <div class="simple-list-row" ${e.show_id ? `onclick="openShowModal(${e.show_id})" style="cursor:pointer;" title="${escapeHtml(e.show_title_snapshot || e.show_title || '')}"` : ''}>
        <span>${escapeHtml(e.show_title_snapshot || e.release_title || e.show_title || '—')}</span>
        <span class="muted">${formatDateTZ(e.created_at, { hour: undefined, minute: undefined })}</span>
      </div>`).join("") || `<div class="simple-list-empty">${t("dash.no_grabs")}</div>`;
  } catch (e) {}

  loadSystemAbout();
  loadHealthCheck();
}

async function loadSystemAbout() {
  const el = document.getElementById("dash-about-content");
  const versionBadge = document.getElementById("dash-about-version");
  if (!el) return;
  try {
    const info = await api("/api/v1/system/about");
    if (!info) return;

    if (versionBadge) {
      versionBadge.textContent = `v${info.version || '1.0.0'}`;
    }

    const isRu = CURRENT_LANG !== "en";
    const rows = [
      {
        icon: "tag",
        label: isRu ? "Версия" : "Version",
        val: `<span class="badge-teal mono">v${escapeHtml(info.version || '1.0.0')} (${escapeHtml(info.branch || 'main')})</span>`,
      },
      {
        icon: "box",
        label: isRu ? "Среда выполнения" : "Runtime",
        val: `<span class="mono">${escapeHtml(info.runtime || 'Docker')}</span>`,
      },
      {
        icon: "terminal",
        label: "Python",
        val: `<span class="mono">${escapeHtml(info.python_version || '3.11')}</span>`,
      },
      {
        icon: "database",
        label: isRu ? "База данных" : "Database",
        val: `<span class="mono">${escapeHtml(info.database_type || 'SQLite')} ${escapeHtml(info.database_version || '')} (${info.database_size_formatted || '0 B'})</span>`,
      },
      {
        icon: "folder",
        label: isRu ? "Каталог настроек" : "AppData Dir",
        val: `<span class="mono" title="${escapeHtml(info.config_directory || '')}">${escapeHtml(info.config_directory || '/config')}</span>`,
      },
      {
        icon: "clock",
        label: isRu ? "Время работы" : "Uptime",
        val: `<span>${escapeHtml(isRu ? info.uptime_formatted : info.uptime_formatted_en)}</span>`,
      },
      {
        icon: "globe",
        label: isRu ? "Часовой пояс" : "Timezone",
        val: `<span>${escapeHtml(info.timezone || 'UTC')}</span>`,
      },
      {
        icon: info.ssl_enabled ? "shield-check" : "globe",
        label: isRu ? "Режим подключения" : "Connection Mode",
        val: `<span class="mono" style="color:${info.ssl_enabled ? 'var(--teal)' : 'inherit'}">${escapeHtml(isRu ? info.mode : info.mode_en)}</span>`,
      },
    ];

    el.innerHTML = rows.map(r => `
      <div class="about-item">
        <span class="about-label">
          <i data-lucide="${r.icon}"></i>
          <span>${r.label}</span>
        </span>
        <span class="about-val">${r.val}</span>
      </div>
    `).join("");

    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  } catch (e) {
    console.error("loadSystemAbout error:", e);
    el.innerHTML = `<div class="about-item"><span style="color:var(--text-muted);">${escapeHtml(e.message || "Ошибка загрузки информации")}</span></div>`;
  }
}

function formatHealthMessage(msg) {
  if (CURRENT_LANG !== "en") return msg;
  return (msg || "")
    .replace(/^Свободно (.+?) из (.+?) \((\d+(?:\.\d+)?)% занято\)/i, "Free $1 of $2 ($3% used)")
    .replace(/^Свободно (.+?) из (.+?) \((\d+(?:\.\d+)?)% свободно\)/i, "Free $1 of $2 ($3% free)")
    .replace(/^Включено (\d+) из (\d+) трекеров/i, "Enabled $1 of $2 trackers")
    .replace(/^Нет ни одного включённого индексатора.*/i, "No enabled indexers — release searching will not work")
    .replace(/^Включено (\d+) из (\d+) клиентов загрузки/i, "Enabled $1 of $2 download clients")
    .replace(/^Нет активных download-клиентов.*/i, "No active download clients — grabbed releases will not be downloaded")
    .replace(/^Активно (\d+) источников.*/i, "Active $1 metadata sources (SkyHook, TheTVDB, TVMaze, TMDB)")
    .replace(/^Нет активных источников метаданных/i, "No active metadata sources")
    .replace(/^Служба автоматической проверки загрузок и трекеров работает/i, "Automatic downloads and tracker monitoring service active")
    .replace(/^Все тайтлы библиотеки привязаны к профилям качества/i, "All titles in library are assigned to quality profiles")
    .replace(/^Видео без профиля качества: (\d+).*/i, "Videos without quality profile: $1 (any quality allowed)");
}

function formatHealthTitle(title) {
  if (CURRENT_LANG !== "en") return title;
  const map = {
    "Индексаторы": "Indexers",
    "Загрузчики": "Download Clients",
    "Метаданные": "Metadata Sources",
    "Фоновый мониторинг": "Background Monitor",
    "Профили качества": "Quality Profiles",
    "Безопасность": "Security",
  };
  if (map[title]) return map[title];
  if (title && (title.startsWith("Диск: ") || title.startsWith("Диск "))) {
    let t = title.replace(/^Диск:\s*/, "Disk: ").replace(/^Диск\s+/, "Disk: ");
    t = t.replace("Медиатека", "Media Library")
         .replace("Загрузки", "Downloads")
         .replace("Конфигурация", "Config")
         .replace("Корень", "Root");
    return t;
  }
  return title;
}

async function loadHealthCheck() {
  const el = document.getElementById("health-checks");
  const healthBadge = document.getElementById("dash-health-badge");
  if (!el) return;
  try {
    const res = await api("/api/v1/health-check");
    const checks = (res && Array.isArray(res.checks)) ? res.checks : [];
    const overall = res && res.status ? res.status : "ok";

    if (healthBadge) {
      if (overall === "error") {
        healthBadge.className = "badge badge-error";
        healthBadge.textContent = CURRENT_LANG === "en" ? "Issues Found" : "Есть ошибки";
      } else if (overall === "warn") {
        healthBadge.className = "badge badge-warn";
        healthBadge.textContent = CURRENT_LANG === "en" ? "Warnings" : "Предупреждения";
      } else {
        healthBadge.className = "badge badge-ok";
        healthBadge.textContent = CURRENT_LANG === "en" ? "Healthy" : "В норме";
      }
    }

    if (checks.length > 0) {
      el.innerHTML = checks.map(c => {
        const lvl = c.level || 'ok';
        let progressHtml = "";
        if (c.used_pct !== undefined) {
          const fillColor = lvl === 'error' ? 'var(--danger)' : (lvl === 'warn' ? '#fbbf24' : 'var(--teal)');
          progressHtml = `
            <div class="health-progress-bar">
              <div class="health-progress-fill" style="width:${Math.min(100, Math.max(0, c.used_pct))}%; background:${fillColor};"></div>
            </div>
          `;
        }
        return `
          <div class="health-item">
            <div class="health-item-header">
              <div class="health-item-title">
                <span class="health-dot health-${lvl}"></span>
                <span>${escapeHtml(formatHealthTitle(c.title || "Статус"))}</span>
              </div>
              <span class="badge ${lvl === 'error' ? 'badge-error' : (lvl === 'warn' ? 'badge-warn' : 'badge-ok')}" style="font-size:10.5px; padding:2px 6px;">
                ${lvl === 'error' ? (CURRENT_LANG === 'en' ? 'Error' : 'Ошибка') : (lvl === 'warn' ? (CURRENT_LANG === 'en' ? 'Warning' : 'Внимание') : (CURRENT_LANG === 'en' ? 'OK' : 'Норма'))}
              </span>
            </div>
            <div class="health-item-msg">${escapeHtml(formatHealthMessage(c.message))}</div>
            ${progressHtml}
          </div>
        `;
      }).join("");
    } else {
      el.innerHTML = `<div class="simple-list-empty" style="color:var(--text-muted); padding:8px 0;">${CURRENT_LANG === "en" ? "All services operating normally" : "Все службы работают в штатном режиме"}</div>`;
    }
    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  } catch (e) {
    console.error("loadHealthCheck error:", e);
    if (healthBadge) {
      healthBadge.className = "badge badge-warn";
      healthBadge.textContent = "Error";
    }
    el.innerHTML = `<div class="health-item"><div class="health-item-msg" style="color:var(--danger);">${escapeHtml(e.message || "Ошибка загрузки состояния системы")}</div></div>`;
  }
}

// =============================================================================
// LIBRARY
// =============================================================================

let LIBRARY_VIEW_MODE = localStorage.getItem("aliasarr_library_view") || "posters";
const VIEW_MODE_LABELS = { posters: "library.view_posters", table: "library.view_table", overview: "library.view_overview" };

let LIBRARY_CATEGORY_FILTER = localStorage.getItem("aliasarr_library_cat") || "all";
let LIBRARY_MONITOR_FILTER = localStorage.getItem("aliasarr_library_mon") || "all";

function setLibraryCategory(category) {
  if (LIBRARY_CATEGORY_FILTER === category && category !== "all") {
    LIBRARY_CATEGORY_FILTER = "all";
  } else {
    LIBRARY_CATEGORY_FILTER = category;
  }
  try { localStorage.setItem("aliasarr_library_cat", LIBRARY_CATEGORY_FILTER); } catch (e) {}
  updateLibraryFilterButtons();
  renderLibrary();
}

function setLibraryMonitor(status) {
  if (LIBRARY_MONITOR_FILTER === status && status !== "all") {
    LIBRARY_MONITOR_FILTER = "all";
  } else {
    LIBRARY_MONITOR_FILTER = status;
  }
  try { localStorage.setItem("aliasarr_library_mon", LIBRARY_MONITOR_FILTER); } catch (e) {}
  updateLibraryFilterButtons();
  renderLibrary();
}

function updateLibraryFilterButtons() {
  document.querySelectorAll("#library-category-btns button").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.category === LIBRARY_CATEGORY_FILTER);
  });
  document.querySelectorAll("#library-monitor-btns button").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.monitor === LIBRARY_MONITOR_FILTER);
  });
}

let POSTER_OPTIONS = {
  size: "large",
  progressText: true,
  title: true,
  monitored: true,
  quality: true,
  tags: true
};
try {
  const saved = localStorage.getItem("aliasarr_poster_options");
  if (saved) POSTER_OPTIONS = { ...POSTER_OPTIONS, ...JSON.parse(saved) };
} catch (e) {}

function openPosterOptionsModal() {
  document.getElementById("poster-opt-size").value = POSTER_OPTIONS.size;
  document.getElementById("poster-opt-progress-text").checked = POSTER_OPTIONS.progressText;
  document.getElementById("poster-opt-title").checked = POSTER_OPTIONS.title;
  document.getElementById("poster-opt-monitored").checked = POSTER_OPTIONS.monitored;
  document.getElementById("poster-opt-quality").checked = POSTER_OPTIONS.quality;
  document.getElementById("poster-opt-tags").checked = POSTER_OPTIONS.tags;
  openModal("poster-options-modal");
}

function applyPosterOptions() {
  POSTER_OPTIONS = {
    size: document.getElementById("poster-opt-size").value,
    progressText: document.getElementById("poster-opt-progress-text").checked,
    title: document.getElementById("poster-opt-title").checked,
    monitored: document.getElementById("poster-opt-monitored").checked,
    quality: document.getElementById("poster-opt-quality").checked,
    tags: document.getElementById("poster-opt-tags").checked
  };
  localStorage.setItem("aliasarr_poster_options", JSON.stringify(POSTER_OPTIONS));
  renderLibrary();
}

async function loadShows() {
  const empty = document.getElementById("shows-empty");
  try {
    const promises = [api("/api/v1/shows")];
    if (!CACHED_QUALITY_PROFILES.length) {
      promises.push(api("/api/v1/quality-profiles").catch(() => []));
    }
    const results = await Promise.all(promises);
    CACHED_SHOWS = results[0] || [];
    if (results[1] && results[1].length) {
      CACHED_QUALITY_PROFILES = results[1];
    }
    renderLibrary();
  } catch (e) {
    if (e.message !== "unauthorized") toast("Ошибка загрузки: " + e.message, true);
  }
}

function toggleViewMenu() {
  document.getElementById("view-switcher-menu").classList.toggle("open");
}

function setLibraryView(mode) {
  LIBRARY_VIEW_MODE = mode;
  localStorage.setItem("aliasarr_library_view", mode);
  document.getElementById("view-switcher-label").textContent = t(VIEW_MODE_LABELS[mode]);
  document.getElementById("view-switcher-menu").classList.remove("open");
  renderLibrary();
}

document.addEventListener("click", (e) => {
  const switcher = document.querySelector(".view-switcher");
  if (switcher && !switcher.contains(e.target)) {
    document.getElementById("view-switcher-menu")?.classList.remove("open");
  }
});

function qualityProfileName(id) {
  if (id === null || id === undefined || id === "") return t("common.any_quality");
  const qp = CACHED_QUALITY_PROFILES.find(p => String(p.id) === String(id));
  return qp ? qp.name : (id ? `Профиль #${id}` : t("common.any_quality"));
}

function renderLibrary() {
  const viewLabel = document.getElementById("view-switcher-label");
  if (viewLabel) viewLabel.textContent = t(VIEW_MODE_LABELS[LIBRARY_VIEW_MODE]);

  updateLibraryFilterButtons();

  const grid = document.getElementById("shows-grid");
  const tableWrap = document.getElementById("shows-table-wrap");
  const overviewWrap = document.getElementById("shows-overview-wrap");
  const empty = document.getElementById("shows-empty");

  if (grid) grid.style.display = LIBRARY_VIEW_MODE === "posters" ? "grid" : "none";
  if (tableWrap) tableWrap.style.display = LIBRARY_VIEW_MODE === "table" ? "block" : "none";
  if (overviewWrap) overviewWrap.style.display = LIBRARY_VIEW_MODE === "overview" ? "flex" : "none";

  const searchInput = document.getElementById("library-search");
  const query = (searchInput ? searchInput.value : "").toLowerCase().trim();

  let shows = CACHED_SHOWS || [];

  // Category filter
  if (LIBRARY_CATEGORY_FILTER && LIBRARY_CATEGORY_FILTER !== "all") {
    shows = shows.filter(s => (s.content_type || "series") === LIBRARY_CATEGORY_FILTER);
  }

  // Monitor filter
  if (LIBRARY_MONITOR_FILTER === "monitored") {
    shows = shows.filter(s => s.monitored === true);
  } else if (LIBRARY_MONITOR_FILTER === "unmonitored") {
    shows = shows.filter(s => !s.monitored);
  }

  // Search query filter
  if (query) {
    shows = shows.filter(s =>
      (s.title && s.title.toLowerCase().includes(query)) ||
      (s.aliases || []).some(a => a.text && a.text.toLowerCase().includes(query))
    );
  }

  if (!CACHED_SHOWS.length) {
    if (grid) grid.innerHTML = "";
    if (tableWrap && tableWrap.querySelector("tbody")) tableWrap.querySelector("tbody").innerHTML = "";
    if (overviewWrap) overviewWrap.innerHTML = "";
    if (empty) empty.style.display = "block";
    const dashContainer = document.getElementById("library-dashboard-container");
    if (dashContainer) dashContainer.innerHTML = "";
    return;
  }
  if (empty) empty.style.display = "none";

  if (!shows.length) {
    const emptyMsg = `<div class="simple-list-empty">${t("library.no_results")}</div>`;
    if (grid) grid.innerHTML = emptyMsg;
    const tbody = document.getElementById("shows-table-body");
    if (tbody) tbody.innerHTML = "";
    if (overviewWrap) overviewWrap.innerHTML = emptyMsg;
    const dashContainer = document.getElementById("library-dashboard-container");
    if (dashContainer) dashContainer.innerHTML = "";
    const alphaIndex = document.getElementById("alphabet-index");
    if (alphaIndex) alphaIndex.style.display = "none";
    return;
  }

  const dashContainer = document.getElementById("library-dashboard-container");
  if (dashContainer) dashContainer.innerHTML = renderLibraryDashboard(shows);

  if (LIBRARY_VIEW_MODE === "posters") {
    if (grid) {
      grid.className = "shows-grid size-" + POSTER_OPTIONS.size;
      grid.innerHTML = shows.map(renderShowCard).join("");
      shows.forEach(s => document.getElementById("show-card-" + s.id)?.addEventListener("click", () => openShowModal(s.id)));
      if (window.lucide) lucide.createIcons();
    }
  } else if (LIBRARY_VIEW_MODE === "table") {
    const tbody = document.getElementById("shows-table-body");
    if (tbody) {
      tbody.innerHTML = shows.map(renderShowTableRow).join("");
      shows.forEach(s => document.getElementById("show-row-" + s.id)?.addEventListener("click", () => openShowModal(s.id)));
      if (window.lucide) lucide.createIcons();
    }
  } else {
    if (overviewWrap) {
      overviewWrap.className = "shows-overview size-" + (POSTER_OPTIONS.size || "medium");
      overviewWrap.innerHTML = shows.map(renderShowOverviewRow).join("");
      shows.forEach(s => document.getElementById("show-overview-" + s.id)?.addEventListener("click", () => openShowModal(s.id)));
      if (window.lucide) lucide.createIcons();
    }
  }
  buildAlphabetIndex(shows);
}

function renderLibraryDashboard(shows) {
  if (!shows || !shows.length) return "";
  return `
    <div class="library-dashboard-footer">
      <div class="library-dashboard-legend">
        <div class="library-legend-item">
          <div class="library-legend-color status-continuing"></div>
          <span>${t("library.legend_continuing")}</span>
        </div>
        <div class="library-legend-item">
          <div class="library-legend-color status-ended"></div>
          <span>${t("library.legend_ended")}</span>
        </div>
        <div class="library-legend-item">
          <div class="library-legend-color status-missing-mon"></div>
          <span>${t("library.legend_missing_mon")}</span>
        </div>
        <div class="library-legend-item">
          <div class="library-legend-color status-missing-unmon"></div>
          <span>${t("library.legend_missing_unmon")}</span>
        </div>
        <div class="library-legend-item">
          <div class="library-legend-color status-downloading"></div>
          <span>${t("library.legend_downloading")}</span>
        </div>
      </div>
    </div>
  `;
}

function getTaskDisplayTitle(task) {
  if (!task) return CURRENT_LANG === "en" ? "Import" : "Импорт";
  const name = (task.name || "").toLowerCase();
  const title = (task.title || "").toLowerCase();
  if (name === "import_files" || name === "manual_import" || title.includes("импорт") || title.includes("перенос")) {
    return CURRENT_LANG === "en" ? "Import" : "Импорт";
  }
  if (name === "recheck_releases" || name === "recheck_trackers" || name === "recheck_all_tracked_releases" || title.includes("отслежив") || title.includes("проверка раздач") || title.includes("трекер")) {
    return CURRENT_LANG === "en" ? "Checking" : "Проверка";
  }
  if (name === "refresh_metadata" || name === "metadata_refresh" || title.includes("метаданн")) {
    return CURRENT_LANG === "en" ? "Metadata" : "Метаданные";
  }
  if (name.includes("search") || title.includes("поиск")) {
    return CURRENT_LANG === "en" ? "Search" : "Поиск";
  }
  return task.title || (CURRENT_LANG === "en" ? "Processing" : "Обработка");
}

function computeShowProgressHtml(show, activeTask) {
  if (!activeTask && typeof CURRENT_ACTIVE_TASKS !== "undefined" && CURRENT_ACTIVE_TASKS) {
    activeTask = CURRENT_ACTIVE_TASKS.find(t => 
      (t.show_id && t.show_id === show.id) ||
      (t.title && t.title.toLowerCase().includes((show.title || "").toLowerCase())) ||
      (t.message && t.message.toLowerCase().includes((show.title || "").toLowerCase()))
    );
  }

  if (show.episodes_count > 0 || show.content_type === "movie") {
    const total = show.episodes_count || 1;
    const downloaded = show.downloaded_episodes_count || 0;
    const downloading = show.downloading_episodes_count || 0;
    
    let statusClass = "status-ended";
    if (downloading > 0) {
      statusClass = "status-downloading";
    } else if (downloaded < total) {
      statusClass = show.monitored ? "status-missing-mon" : "status-missing-unmon";
    } else {
      if (show.content_type === "series" || show.content_type === "anime") {
        if (show.next_airing) {
          statusClass = "status-continuing";
        } else {
          statusClass = "status-ended";
        }
      } else {
        statusClass = "status-ended";
      }
    }
    
    show._computed_status = statusClass;
    
    let textHtml = "";
    if (POSTER_OPTIONS.progressText && show.content_type !== "movie") {
      textHtml = `<div class="poster-progress-text">${downloaded} / ${total}</div>`;
    } else if (POSTER_OPTIONS.progressText && show.content_type === "movie") {
      textHtml = `<div class="poster-progress-text">${downloaded > 0 ? "1 / 1" : "0 / 1"}</div>`;
    }
    
    if (activeTask) {
      const taskTitle = getTaskDisplayTitle(activeTask);
      const pct = Math.min(100, Math.max(0, Math.round((activeTask.progress || 0) * 100)));
      statusClass = "status-importing";
      textHtml = `<div class="poster-progress-text">${escapeHtml(taskTitle)}: ${pct}%</div>`;
    }

    return `<div class="poster-progress ${statusClass}">${textHtml}</div>`;
  } else {
    show._computed_status = show.monitored ? "status-missing-mon" : "status-missing-unmon";
    return "";
  }
}

function getShowAlpha(show) {
  const title = (show.title || "").trim();
  const firstChar = title[0]?.toUpperCase() || "#";
  if (/[A-Z]/.test(firstChar)) {
    return firstChar;
  }
  if (/[А-ЯЁ]/.test(firstChar)) {
    return firstChar === "Ё" ? "Е" : firstChar;
  }
  return "#";
}

function buildAlphabetIndex(shows) {
  const container = document.getElementById("alphabet-index");
  if (!container) return;
  if (!shows || shows.length === 0) {
    container.style.display = "none";
    return;
  }

  const existingLetters = new Set();
  let hasCyrillic = false;

  shows.forEach(s => {
    const alpha = getShowAlpha(s);
    existingLetters.add(alpha);
    if (/[А-Я]/.test(alpha)) {
      hasCyrillic = true;
    }
  });

  const alphabet = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];
  if (hasCyrillic) {
    alphabet.push(..."АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ".split(""));
  }

  container.innerHTML = alphabet.map(char => {
    const exists = existingLetters.has(char);
    if (exists) {
      return `<a class="alphabet-link active" onclick="scrollToLetter('${char}')" title="${char}">${char}</a>`;
    } else {
      return `<span class="alphabet-link disabled" title="${char}">${char}</span>`;
    }
  }).join("");

  container.style.display = "flex";
}

function scrollToLetter(char) {
  let target = null;
  if (LIBRARY_VIEW_MODE === "posters") {
    target = document.querySelector(`.show-card[data-alpha="${char}"]`);
  } else if (LIBRARY_VIEW_MODE === "table") {
    target = document.querySelector(`#shows-table-body tr[data-alpha="${char}"]`);
  } else {
    target = document.querySelector(`.overview-row[data-alpha="${char}"]`);
  }

  if (target) {
    const stickyHeader = document.querySelector("#tab-library .panel-sticky-header");
    const headerOffset = (stickyHeader ? stickyHeader.offsetHeight : 0) + 16;
    const elementPosition = target.getBoundingClientRect().top;
    const offsetPosition = elementPosition + window.pageYOffset - headerOffset;
    window.scrollTo({
      top: Math.max(0, offsetPosition),
      behavior: "smooth"
    });
  }
}

function renderShowCard(show) {
  const initial = (show.title || "?").trim()[0]?.toUpperCase() || "?";
  const posterStyle = show.poster_url ? `style="background-image:url('${show.poster_url}')"` : "";
  const aliases = (show.aliases || []).slice(0, 4).map(
    a => `<span class="alias-chip lang-${a.language}">${escapeHtml(a.text)}</span>`
  ).join("");
  
  // Active Task overlay check
  const activeTask = (typeof CURRENT_ACTIVE_TASKS !== "undefined" && CURRENT_ACTIVE_TASKS) ? CURRENT_ACTIVE_TASKS.find(t => 
    (t.show_id && t.show_id === show.id) ||
    (t.title && t.title.toLowerCase().includes((show.title || "").toLowerCase())) ||
    (t.message && t.message.toLowerCase().includes((show.title || "").toLowerCase()))
  ) : null;

  const taskTitle = activeTask ? getTaskDisplayTitle(activeTask) : "";

  let importOverlayHtml = "";
  if (activeTask) {
    const pct = Math.min(100, Math.max(0, Math.round((activeTask.progress || 0) * 100)));
    importOverlayHtml = `
      <div class="poster-import-overlay">
        <div class="poster-import-spinner"></div>
        <div class="poster-import-title">${escapeHtml(taskTitle)}</div>
        <div class="poster-import-pct">${pct}%</div>
        <div class="poster-import-bar-track">
          <div class="poster-import-bar-fill" style="width: ${pct}%;"></div>
        </div>
      </div>
    `;
  }

  // Индикатор прогресса
  const progressHtml = computeShowProgressHtml(show, activeTask);

  let infoHtml = "";
  if (POSTER_OPTIONS.title) {
    infoHtml += `<div class="show-title">${escapeHtml(show.title)}${show.year ? ` (${show.year})` : ""}</div>`;
  }
  if (POSTER_OPTIONS.monitored) {
    const mtext = show.monitored ? t("dash.monitored") : t("dash.unmonitored");
    const mClass = show.monitored ? "monitored" : "unmonitored";
    const mIcon = show.monitored ? "bookmark-check" : "bookmark-x";
    infoHtml += `
      <div class="show-monitored-badge-wrap">
        <span class="show-monitored-pill ${mClass}">
          <i data-lucide="${mIcon}" class="ico-xs"></i>
          <span>${escapeHtml(mtext)}</span>
        </span>
      </div>
    `;
  }
  if (POSTER_OPTIONS.quality) {
    infoHtml += `<div class="show-quality-badge-wrap"><span class="show-quality-badge">${escapeHtml(qualityProfileName(show.quality_profile_id))}</span></div>`;
  }
  if (POSTER_OPTIONS.tags && aliases) {
    infoHtml += `<div class="alias-cluster">${aliases}</div>`;
  }

  return `
    <div class="show-card" id="show-card-${show.id}" data-alpha="${getShowAlpha(show)}">
      <div class="show-poster" ${posterStyle}>
        ${show.poster_url ? "" : initial}
        ${importOverlayHtml}
      </div>
      ${progressHtml}
      ${infoHtml ? `<div class="show-info">${infoHtml}</div>` : ""}
    </div>`;
}

function renderShowTableRow(show) {
  const nextAiring = show.next_airing ? formatDateOnly(show.next_airing) : "—";
  const mTitle = show.monitored ? t("dash.monitored") : t("dash.unmonitored");
  const mIcon = show.monitored ? "bookmark-check" : "bookmark-x";
  const mClass = show.monitored ? "monitored" : "unmonitored";
  return `
    <tr id="show-row-${show.id}" data-alpha="${getShowAlpha(show)}" style="cursor:pointer">
      <td style="text-align: center; width: 44px;">
        <span class="show-table-monitored ${mClass}" title="${escapeHtml(mTitle)}">
          <i data-lucide="${mIcon}" class="ico-xs"></i>
        </span>
      </td>
      <td>${escapeHtml(show.title)}${show.year ? ` <span class="hint">(${show.year})</span>` : ""}</td>
      <td>${show.network ? escapeHtml(show.network) : "—"}</td>
      <td>${escapeHtml(qualityProfileName(show.quality_profile_id))}</td>
      <td class="mono">${nextAiring}</td>
      <td class="mono">${show.seasons_count || 0}</td>
      <td class="mono">${show.episodes_count || 0}</td>
    </tr>`;
}

function renderShowOverviewRow(show) {
  const initial = (show.title || "?").trim()[0]?.toUpperCase() || "?";
  const posterStyle = show.poster_url ? `style="background-image:url('${show.poster_url}')"` : "";
  const nextAiring = show.next_airing ? formatDateOnly(show.next_airing) : null;
  const mtext = show.monitored ? t("dash.monitored") : t("dash.unmonitored");
  const mClass = show.monitored ? "monitored" : "unmonitored";
  const mIcon = show.monitored ? "bookmark-check" : "bookmark-x";
  const progressHtml = computeShowProgressHtml(show);

  const aliases = (show.aliases || []).slice(0, 6).map(
    a => `<span class="alias-chip lang-${a.language}">${escapeHtml(a.text)}</span>`
  ).join("");

  let titleRowHtml = "";
  if (POSTER_OPTIONS.title || POSTER_OPTIONS.monitored) {
    titleRowHtml = `
      <div class="overview-title-row">
        ${POSTER_OPTIONS.title ? `<span class="overview-title">${escapeHtml(show.title)}${show.year ? ` (${show.year})` : ""}</span>` : ""}
        ${POSTER_OPTIONS.monitored ? `<span class="show-monitored-pill ${mClass}"><i data-lucide="${mIcon}" class="ico-xs"></i><span>${escapeHtml(mtext)}</span></span>` : ""}
      </div>`;
  }

  const qualityBadge = POSTER_OPTIONS.quality ? `<span class="meta-badge meta-badge-quality">${escapeHtml(qualityProfileName(show.quality_profile_id))}</span>` : "";
  const seasonsBadge = show.seasons_count ? `<span class="meta-badge">${t("show.seasons_count")}: ${show.seasons_count}</span>` : "";
  const ratingBadge = show.rating ? `<span class="meta-badge meta-badge-rating"><i data-lucide="star" class="ico-xs" style="color:var(--warning); vertical-align:middle; margin-right:3px;"></i>${Number(show.rating).toFixed(1)}</span>` : "";
  const genreBadge = show.genre ? `<span class="meta-badge">${escapeHtml(show.genre)}</span>` : "";
  const countryBadge = show.country ? `<span class="meta-badge">${escapeHtml(show.country)}</span>` : "";
  const networkBadge = show.network ? `<span class="meta-badge">${escapeHtml(show.network)}</span>` : "";
  const nextAirBadge = nextAiring ? `<span class="meta-badge">${t("show.next_airing")}: ${nextAiring}</span>` : "";

  const tagsHtml = (POSTER_OPTIONS.tags && aliases) ? `<div class="alias-cluster" style="margin-top:6px;">${aliases}</div>` : "";

  return `
    <div class="overview-row" id="show-overview-${show.id}" data-alpha="${getShowAlpha(show)}">
      <div class="overview-poster-col">
        <div class="overview-poster" ${posterStyle}>${show.poster_url ? "" : initial}</div>
        ${progressHtml}
      </div>
      <div class="overview-info">
        ${titleRowHtml}
        <p class="overview-desc">${escapeHtml(show.overview || t("show.no_overview"))}</p>
        <div class="overview-meta-row">
          ${qualityBadge}
          ${seasonsBadge}
          ${ratingBadge}
          ${genreBadge}
          ${countryBadge}
          ${networkBadge}
          ${nextAirBadge}
        </div>
        ${tagsHtml}
      </div>
    </div>`;
}

// =============================================================================
// SHOW DETAIL MODAL
// =============================================================================

let CURRENT_SHOW_ID = null;
let SHOW_MODAL_POLL_INTERVAL = null;
let SHOW_EXPANDED_SEASONS = window._SHOW_EXPANDED_SEASONS || {};
window._SHOW_EXPANDED_SEASONS = SHOW_EXPANDED_SEASONS;

async function openShowModal(showId) {
  CURRENT_SHOW_ID = showId;
  const content = document.getElementById("show-modal-content");
  content.innerHTML = `<p>${t("common.loading")}</p>`;
  openModal("show-modal");
  await refreshShowModal();
  
  if (SHOW_MODAL_POLL_INTERVAL) clearInterval(SHOW_MODAL_POLL_INTERVAL);
  SHOW_MODAL_POLL_INTERVAL = setInterval(async () => {
    if (!document.getElementById("show-modal").classList.contains("active")) {
      clearInterval(SHOW_MODAL_POLL_INTERVAL);
      return;
    }
    try {
      const [episodes, queue] = await Promise.all([
        api(`/api/v1/shows/${showId}/episodes`),
        api(`/api/v1/queue`).catch(() => [])
      ]);
      const queueByHash = {};
      queue.forEach(q => queueByHash[q.hash.toLowerCase()] = q.progress);

      let statusChanged = false;

      episodes.forEach(ep => {
        const row = document.getElementById(`episode-row-${ep.id}`);
        if (!row) return;
        
        if (row.dataset.status && row.dataset.status !== ep.status) {
          statusChanged = true;
          return;
        }
        
        if (ep.status === "downloading") {
          if (ep.torrent_hash) {
            const liveProgress = queueByHash[ep.torrent_hash.toLowerCase()];
            if (liveProgress !== undefined) {
              ep.download_progress = liveProgress;
            }
          }
          const pct = Math.min(100, Math.max(0, (ep.download_progress || 0) * 100)).toFixed(1);
          
          const progressFillEl = row.querySelector('.status-pill.status-upgrading .status-pill-fill, .status-pill.status-downloading-progress .status-pill-fill, .ep-progress > div > div');
          if (progressFillEl) {
            progressFillEl.style.width = `${pct}%`;
          }
        }
      });

      if (statusChanged) {
        await refreshShowModal();
        if (typeof loadShows === "function") {
          loadShows(false);
        }
      }
    } catch (e) {}
  }, 2000);
}

async function refreshShowModal() {
  const showId = CURRENT_SHOW_ID;
  if (!showId) return;

  // Сохраняем текущее состояние развернутых сезонов и спецвыпусков перед обновлением DOM
  const existingBlocks = document.querySelectorAll("#seasons-container .season-block");
  if (existingBlocks.length > 0) {
    const currentSet = SHOW_EXPANDED_SEASONS[showId] || new Set();
    existingBlocks.forEach(b => {
      const sn = parseInt(b.id.replace("season-block-", ""), 10);
      if (!isNaN(sn)) {
        if (!b.classList.contains("collapsed")) {
          currentSet.add(sn);
        } else {
          currentSet.delete(sn);
        }
      }
    });
    SHOW_EXPANDED_SEASONS[showId] = currentSet;
  }

  const content = document.getElementById("show-modal-content");
  try {
    const [show, episodes, queue] = await Promise.all([
      api(`/api/v1/shows/${showId}`),
      api(`/api/v1/shows/${showId}/episodes`),
      api(`/api/v1/queue`).catch(() => []) // Queue might fail if clients are offline, fallback to empty
    ]);

    if (!CACHED_QUALITY_PROFILES.length) {
      try { CACHED_QUALITY_PROFILES = await api("/api/v1/quality-profiles"); } catch (e) {}
    }

    const queueByHash = {};
    queue.forEach(q => queueByHash[q.hash.toLowerCase()] = q.progress);

    episodes.forEach(ep => {
      if (ep.status === "downloading" && ep.torrent_hash) {
        const liveProgress = queueByHash[ep.torrent_hash.toLowerCase()];
        if (liveProgress !== undefined) {
          ep.download_progress = liveProgress;
        }
      }
    });

    const seasons = {};
    episodes.forEach(ep => {
      (seasons[ep.season_number] = seasons[ep.season_number] || []).push(ep);
    });
    const seasonNumbers = Object.keys(seasons).map(Number).sort((a, b) => a - b);

    const posterStyle = show.poster_url ? `style="background-image:url('${show.poster_url}')"` : "";
    const initial = (show.title || "?").trim()[0]?.toUpperCase() || "?";

    const canManageLib = hasPermission("manage_library");
    const canSearch = hasPermission("manual_search");

    content.innerHTML = `
      <div class="show-detail-header">
        <div class="show-detail-poster-col">
          <div class="show-detail-poster" ${posterStyle}>${show.poster_url ? "" : initial}</div>
          ${canManageLib ? `
          <div class="poster-manual-actions">
            <button type="button" class="btn btn-secondary btn-small" onclick="document.getElementById('show-cover-file-${show.id}').click()" title="${t("show.upload_cover")}"><i data-lucide="upload" class="ico-sm"></i> <span>${t("show.upload_cover")}</span></button>
            <input id="show-cover-file-${show.id}" type="file" accept="image/*" style="display:none" onchange="onShowCoverFile(event, ${show.id})">
            <button type="button" class="btn btn-secondary btn-small" style="white-space: normal; line-height: 1.2;" onclick="searchPosterForShow(${show.id})" title="${t("show.refresh_cover")}"><i data-lucide="search" class="ico-sm"></i> <span>${t("show.refresh_cover")}</span></button>
          </div>` : ""}
        </div>
        <div class="show-detail-meta">
          <h2>${escapeHtml(show.title)}${show.year ? ` (${show.year})` : ""}</h2>
          <div class="alias-manager" id="alias-manager-${show.id}">
            ${renderAliasChips(show, canManageLib)}
          </div>
          ${canManageLib ? `
          <div class="alias-add-row">
            <input id="new-alias-text-${show.id}" class="input input-small" type="text" placeholder="${t("show.new_alias_placeholder")}"
              onkeydown="if(event.key==='Enter') addAlias(${show.id})">
            <select id="new-alias-lang-${show.id}" class="input input-small">
              <option value="ru">ru</option><option value="en">en</option>
              <option value="jp">jp</option><option value="romaji">romaji</option><option value="other">other</option>
            </select>
            <button class="btn btn-secondary btn-small" onclick="addAlias(${show.id})"><i data-lucide="plus" class="ico-sm"></i> ${t("common.add")}</button>
          </div>` : ""}
          <p class="show-detail-overview" style="max-height: 160px; overflow-y: auto;">${escapeHtml(show.overview || t("show.no_overview"))}</p>
          <div class="meta-badges-row">
            ${show.rating ? `<span class="meta-badge meta-badge-rating"><i data-lucide="star" class="ico-xs" style="color:var(--warning); vertical-align:middle; margin-right:3px;"></i>${Number(show.rating).toFixed(1)}</span>` : ""}
            ${show.genre ? `<span class="meta-badge">${escapeHtml(show.genre)}</span>` : ""}
            ${show.country ? `<span class="meta-badge">${escapeHtml(show.country)}</span>` : ""}
            ${show.network ? `<span class="meta-badge">${escapeHtml(show.network)}</span>` : ""}
          </div>
          <div class="show-detail-path">
            ${show.path && canManageLib ? `
            <div class="show-detail-path-actions">
              <button type="button" class="btn btn-secondary btn-small" onclick="syncShowPath(${show.id})" title="${t("show.sync_tooltip")}">
                <i data-lucide="refresh-cw" class="ico-sm"></i> <span>${t("show.btn_sync")}</span>
              </button>
              <button type="button" class="btn btn-secondary btn-small" onclick="openPreviewRenameModal(${show.id})" title="${t("show.btn_preview_rename")}">
                <i data-lucide="folder-sync" class="ico-sm"></i> <span>${t("show.btn_preview_rename")}</span>
              </button>
              <button type="button" class="btn btn-secondary btn-small" onclick="openManualImportModal(${show.id})" title="${t("show.manual_import")}">
                <i data-lucide="hard-drive-download" class="ico-sm"></i> <span>${t("show.manual_import")}</span>
              </button>
              <button type="button" class="btn btn-secondary btn-small" onclick="fixShowPermissions(this, ${show.id})" title="${CURRENT_LANG === 'en' ? 'Fix permissions (chmod 777/666 for Jellyfin/Plex)' : 'Исправить права доступа (chmod 777/666 для Jellyfin/Plex)'}">
                <i data-lucide="shield-check" class="ico-sm"></i> <span>${CURRENT_LANG === 'en' ? 'Permissions' : 'Права доступа'}</span>
              </button>
            </div>` : ""}
            <div class="show-detail-path-info">
              <div class="show-detail-path-label">${t("show.directory")}</div>
              <code class="show-detail-path-code">${show.path || t("show.not_set")}</code>
            </div>
          </div>
        </div>
      </div>

      <div class="show-detail-actions-row">
        <div class="form-col">
          <label class="hint">${t("library.col_profile")}</label>
          <select class="input" style="max-width:260px" ${canManageLib ? "" : "disabled"} onchange="changeQualityProfile(${show.id}, this.value)">
            <option value="">${t("common.any_quality")}</option>
            ${CACHED_QUALITY_PROFILES.map(qp => `<option value="${qp.id}" ${qp.id === show.quality_profile_id ? "selected" : ""}>${escapeHtml(qp.name)}</option>`).join("")}
          </select>
        </div>
        <div class="form-col">
          <label class="hint">${t("settings.col_category")}</label>
          <select class="input" style="max-width:260px" ${canManageLib ? "" : "disabled"} onchange="changeContentType(${show.id}, this.value)">
            <option value="movie" ${show.content_type === "movie" ? "selected" : ""}>${t("settings.cat_movies")}</option>
            <option value="series" ${show.content_type === "series" ? "selected" : ""}>${t("settings.cat_series")}</option>
            <option value="anime" ${show.content_type === "anime" ? "selected" : ""}>${t("settings.cat_anime")}</option>
          </select>
        </div>
      </div>

      <div class="search-status-row ${show.is_searching ? "is-searching" : ""}">
        ${renderSearchStatus(show)}
      </div>

      <div class="show-actions-row">
        ${canSearch ? `
        <button class="btn btn-primary btn-small" id="btn-show-download-selected" onclick="searchSelectedEpisodes(this, null)" style="display:none;" title="${CURRENT_LANG === 'en' ? 'Download selected episodes across all seasons' : 'Скачать все выбранные серии из всех сезонов'}">
          <i data-lucide="download" class="ico-sm"></i> <span id="btn-show-download-selected-label">${CURRENT_LANG === 'en' ? 'Download selected' : 'Скачать выбранные серии'}</span>
        </button>` : ""}
        ${canManageLib ? `
        <button class="btn btn-secondary btn-small" onclick="toggleMonitored(this, ${show.id}, ${!show.monitored})">
          <i data-lucide="${show.monitored ? 'pause' : 'play'}" class="ico-sm"></i> <span>${show.monitored ? t("action.unmonitor") : t("action.monitor")}</span>
        </button>
        ${show.content_type !== "movie" ? `
        <button class="btn btn-secondary btn-small" onclick="setAllSeasonsMonitor(${show.id}, true)" title="${t("show.monitor_all_tooltip")}">
          <i data-lucide="bookmark-plus" class="ico-sm"></i> <span>${t("show.monitor_all_seasons")}</span>
        </button>
        <button class="btn btn-secondary btn-small" onclick="setAllSeasonsMonitor(${show.id}, false)" title="${t("show.unmonitor_all_tooltip")}">
          <i data-lucide="bookmark-minus" class="ico-sm"></i> <span>${t("show.unmonitor_all_seasons")}</span>
        </button>
        <button class="btn btn-secondary btn-small" onclick="setUnairedMonitor(${show.id}, true)" title="${t("show.monitor_unaired_tooltip")}">
          <i data-lucide="calendar-search" class="ico-sm"></i> <span>${t("show.monitor_unaired")}</span>
        </button>` : ""}` : ""}
        ${canSearch ? `
        <button class="btn btn-primary btn-small" onclick="forceSearchShow(this, ${show.id})"><i data-lucide="refresh-cw" class="ico-sm"></i> <span>${t("show.force_search")}</span></button>
        <button class="btn btn-secondary btn-small" onclick="searchReleasesForShow(this, ${show.id})"><i data-lucide="search" class="ico-sm"></i> <span>${t("show.search_manual")}</span></button>` : ""}
        ${canManageLib ? `
        <button class="btn btn-danger btn-small" onclick="deleteShow(${show.id})"><i data-lucide="trash-2" class="ico-sm"></i> <span>${t("show.delete_video")}</span></button>` : ""}
      </div>

      <div id="manual-search-results-${show.id}" class="manual-search-panel"></div>

      <div id="seasons-container">
        ${show.content_type === "movie"
          ? (episodes.length ? renderMovieBlock(show, episodes[0], canManageLib) :
             `<p style="color:var(--text-muted)">${t("show.no_overview")}</p>`)
          : `${seasonNumbers.length > 1 ? `
            <div class="seasons-toolbar" style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 10px; padding: 2px 4px;">
              <span style="font-size: 13px; font-weight: 600; color: var(--text-muted);">${t("show.seasons_count")}: ${seasonNumbers.length}</span>
              <div style="display:flex; gap: 6px;">
                <button class="btn btn-secondary btn-small" onclick="expandAllSeasons()" style="padding: 4px 9px; font-size: 12px;" title="${t("show.expand_all_seasons")}">
                  <i data-lucide="chevrons-up-down" class="ico-xs"></i> <span>${t("show.expand_all_seasons")}</span>
                </button>
                <button class="btn btn-secondary btn-small" onclick="collapseAllSeasons()" style="padding: 4px 9px; font-size: 12px;" title="${t("show.collapse_all_seasons")}">
                  <i data-lucide="chevrons-down-up" class="ico-xs"></i> <span>${t("show.collapse_all_seasons")}</span>
                </button>
              </div>
            </div>` : ""}
            ${seasonNumbers.map(sn => renderSeasonBlock(sn, seasons[sn], canManageLib, canSearch, show)).join("") ||
             `<p style="color:var(--text-muted)">${t("show.no_overview")}</p>`}`}
      </div>`;

    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }

    if (show && show.content_type !== "movie") {
      checkSpecialsImportStatus(show.id);
    }
  } catch (e) {
    if (e.message !== "unauthorized") content.innerHTML = `<p style="color:var(--danger)">${CURRENT_LANG === "en" ? "Error:" : "Ошибка:"} ${escapeHtml(formatToastMessage(e.message))}</p>`;
  }
}

function renderSearchStatus(show) {
  if (show.is_searching) {
    return `<span class="spin-icon">↻</span> ${t("common.loading")}`;
  }
  if (!show.last_search_at) {
    return `—`;
  }
  const when = formatDateTZ(show.last_search_at);
  return `${escapeHtml(show.last_search_result || "—")} (${when})`;
}

function renderAliasChips(show, canManageLib = true) {
  const sorted = [...(show.aliases || [])].sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));
  return sorted.map((a, idx) => `
      <span class="alias-chip lang-${a.language}" title="${a.source === "manual" ? "Manual" : "Source: " + escapeHtml(a.source)}">
        <span class="alias-chip-priority" title="${t("common.priority")}">#${a.priority ?? 100}</span>
        ${escapeHtml(a.text)}
        ${canManageLib ? `<button class="alias-chip-edit" onclick="editAliasPrompt(${show.id}, ${a.id}, '${escapeHtml(a.text).replace(/'/g, "&apos;")}', ${a.priority ?? 100})" title="${t("common.edit")}"><i data-lucide="edit-2" class="ico-xs"></i></button>` : ""}
        ${canManageLib ? `<button class="alias-chip-remove" onclick="deleteAliasFromShow(${show.id}, ${a.id})" title="${t("common.delete")}"><i data-lucide="x" class="ico-xs"></i></button>` : ""}
      </span>`).join("");
}

async function editAliasPrompt(showId, aliasId, currentText, currentPriority) {
  const newText = prompt(t("common.name") + ":", currentText);
  if (newText === null) return;
  const newPriorityStr = prompt(t("common.priority") + ":", String(currentPriority));
  if (newPriorityStr === null) return;
  const newPriority = parseInt(newPriorityStr, 10);
  try {
    await api(`/api/v1/shows/${showId}/aliases/${aliasId}`, {
      method: "PUT",
      body: JSON.stringify({
        text: newText.trim() || undefined,
        priority: Number.isFinite(newPriority) ? newPriority : undefined,
      }),
    });
    await refreshShowModal();
    await loadShows();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function addAlias(showId) {
  const textInput = document.getElementById(`new-alias-text-${showId}`);
  const langSelect = document.getElementById(`new-alias-lang-${showId}`);
  const text = textInput.value.trim();
  if (!text) return;
  try {
    await api(`/api/v1/shows/${showId}/aliases`, {
      method: "POST",
      body: JSON.stringify({ text, language: langSelect.value, priority: 100 }),
    });
    textInput.value = "";
    await refreshShowModal();
    await loadShows();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function fixShowPermissions(btn, showId) {
  if (btn) btn.disabled = true;
  try {
    const res = await api(`/api/v1/shows/${showId}/fix-permissions`, { method: "POST" });
    toast(res.message || (CURRENT_LANG === "en" ? "Permissions updated" : "Права доступа обновлены"));
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error updating permissions: " : "Ошибка обновления прав: ") + e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function fixAllMediaPermissions(btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await api("/api/v1/system/fix-media-permissions", { method: "POST" });
    toast(res.message || (CURRENT_LANG === "en" ? "Media permissions updated" : "Права медиатеки обновлены"));
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function deleteAliasFromShow(showId, aliasId) {
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  try {
    await api(`/api/v1/shows/${showId}/aliases/${aliasId}`, { method: "DELETE" });
    await refreshShowModal();
    await loadShows();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function onShowCoverFile(event, showId) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      await api(`/api/v1/shows/${showId}`, { method: "PUT", body: JSON.stringify({ poster_url: reader.result }) });
      await refreshShowModal();
      await loadShows();
      toast(t("settings.toast_saved"));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  };
  reader.readAsDataURL(file);
}

async function searchPosterForShow(showId) {
  try {
    // 1. Сначала пробуем специализированный бэкенд-роут обновления постера
    try {
      const resp = await api(`/api/v1/shows/${showId}/refresh-cover`, { method: "POST" });
      if (resp && resp.success) {
        toast((CURRENT_LANG === "en" ? "Cover updated from " : "Постер обновлён из ") + (resp.source_name || "SkyHook"));
        await refreshShowModal();
        await loadShows();
        return;
      }
    } catch (apiErr) {
      // fallback на клиентский поиск по источникам
    }

    const show = await api(`/api/v1/shows/${showId}`);
    const query = show.title || show.metadata_id || "";
    if (!query) {
      toast(CURRENT_LANG === "en" ? "No title to search cover for" : "Нет названия для поиска постера", true);
      return;
    }

    const isMovie = show.category === "movies" || show.content_type === "movie";
    const sources = await api("/api/v1/metadata-sources");
    let enabledSources = (sources || []).filter(s => s.enabled);

    if (isMovie) {
      // Для фильмов: строго Radarr SkyHook и TMDB, исключая Sonarr / TVMaze / TheTVDB
      enabledSources = enabledSources
        .filter(s => s.type === "radarr" || s.type === "radarr_skyhook" || s.type === "tmdb")
        .sort((a, b) => (a.type === "radarr" ? -1 : 1));
    } else {
      // Для сериалов и аниме: строго Sonarr SkyHook, TheTVDB, TVMaze, TMDB, исключая Radarr
      enabledSources = enabledSources
        .filter(s => s.type !== "radarr" && s.type !== "radarr_skyhook")
        .sort((a, b) => (a.type === "skyhook" || a.type === "sonarr" ? -1 : 1));
    }

    if (!enabledSources.length) {
      toast(CURRENT_LANG === "en" 
        ? `No active metadata sources for ${isMovie ? "movies (Radarr/TMDB)" : "series/anime (Sonarr/TVDB)"}` 
        : `Нет активных источников для ${isMovie ? "фильмов (Radarr/TMDB)" : "сериалов/аниме (Sonarr/TVDB)"}`, true);
      return;
    }

    for (const src of enabledSources) {
      try {
        const results = await api(`/api/v1/metadata-sources/${src.id}/search?query=${encodeURIComponent(query)}`);
        const found = (results || []).find(r => {
          if (!r.poster_url) return false;
          if (isMovie) return !r.content_type || r.content_type === "movie";
          return !r.content_type || r.content_type !== "movie";
        });
        if (found && found.poster_url) {
          const updatePayload = { poster_url: found.poster_url };
          if (!show.title && found.title) updatePayload.title = found.title;
          if (!show.overview && found.overview) updatePayload.overview = found.overview;
          await api(`/api/v1/shows/${showId}`, {
            method: "PUT",
            body: JSON.stringify(updatePayload),
          });
          toast((CURRENT_LANG === "en" ? "Cover updated from " : "Постер обновлён из ") + src.name);
          await refreshShowModal();
          await loadShows();
          return;
        }
      } catch (e) { /* try next */ }
    }
    toast(CURRENT_LANG === "en" ? "No cover found" : "Постер не найден", true);
  } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
}

function renderMovieBlock(show, ep, canManageLib = true) {
  const monitored = ep.monitored !== undefined ? Boolean(ep.monitored) : ep.status !== "ignored";
  const hasFile = Boolean(ep.has_file || ep.file_path);
  const isUpgrading = Boolean(ep.status === "downloading" && hasFile);
  const isFreshDownloading = Boolean(ep.status === "downloading" && !hasFile);

  let statusHtml = "";
  const pct = Math.min(100, Math.max(0, (ep.download_progress || 0) * 100)).toFixed(1);

  if (isUpgrading) {
    statusHtml = `
      <div class="status-pill status-upgrading" title="${t("status.upgrading_title")}">
        <div class="status-pill-fill" style="width:${pct}%;"></div>
        <span class="status-pill-text">
          <i data-lucide="refresh-cw" class="status-pill-ico status-pill-spin"></i>
          <span>${t("status.upgrading")}</span>
        </span>
      </div>
    `;
  } else if (isFreshDownloading) {
    statusHtml = `
      <div class="status-pill status-downloading-progress" title="${t("status.downloading")}">
        <div class="status-pill-fill" style="width:${pct}%;"></div>
        <span class="status-pill-text">
          <i data-lucide="download" class="status-pill-ico"></i>
          <span>${t("status.downloading")}</span>
        </span>
      </div>
    `;
  } else {
    statusHtml = `<span class="status-pill status-${ep.status}">${escapeHtml(episodeStatusLabel(ep.status))}</span>`;
  }

  const hasFileBadge = hasFile
    ? `<span class="badge-file-present" title="${ep.file_path ? t("show.present_on_disk") + ': ' + escapeHtml(ep.file_path) : t("show.present_on_disk")}"><i data-lucide="hard-drive"></i> ${ep.downloaded_quality ? escapeHtml(ep.downloaded_quality) : t("show.on_disk")}</span>`
    : "";
  // MediaInfo бейджи
  let mediaInfoBadges = "";
  if (hasFile) {
    if (ep.dynamic_range) mediaInfoBadges += `<span class="badge-hdr">${escapeHtml(ep.dynamic_range)}</span> `;
    if (ep.video_codec) mediaInfoBadges += `<span class="badge-quality" style="font-size:10px;">${escapeHtml(ep.video_codec)}</span> `;
    if (ep.audio_codec) mediaInfoBadges += `<span class="badge-audio">${escapeHtml(ep.audio_codec)}</span> `;
    if (ep.release_group) mediaInfoBadges += `<span class="badge-group">${escapeHtml(ep.release_group)}</span> `;
  }

  return `
    <div class="season-block" id="season-block-1">
      <div class="season-header">
        <div class="season-header-left">
          <span>${t("settings.cat_movies")}</span>
          <span class="season-progress">${(ep.status === "downloaded" || hasFile) ? t("status.downloaded") : episodeStatusLabel(ep.status)}</span>
        </div>
      </div>
      <div class="season-episodes">
        <div class="episode-row" id="episode-row-${ep.id}" data-episode-id="${ep.id}" data-status="${ep.status}">
          <span class="ep-title">${escapeHtml(show.title)}</span>
          ${renderAirDateBadge(ep.air_date)}
          ${mediaInfoBadges ? `<div class="ep-mediainfo-tags" style="display:inline-flex; align-items:center; gap:3px; margin: 0 6px;">${mediaInfoBadges}</div>` : ""}
          ${hasFileBadge}
          ${statusHtml}
          <div class="ep-actions" style="display:inline-flex; align-items:center; gap:4px;">
            <button class="btn-icon-only" title="Интерактивный поиск фильма" onclick="openInteractiveSearch(${show.id}, null, null)">
              <i data-lucide="search" class="ico-xs"></i>
            </button>
            ${canManageLib ? `
            <button class="btn-icon-only ${monitored ? "active" : ""}" title="${monitored ? t("action.unmonitor") : t("action.monitor")}"
              onclick="toggleEpisodeMonitor(${ep.id}, ${monitored})"><i data-lucide="bookmark" class="ico-xs"></i></button>` : ""}
          </div>
        </div>
      </div>
    </div>`;
}

function renderSeasonBlock(seasonNumber, episodes, canManageLib = true, canSearch = true, show = null) {
  const downloaded = episodes.filter(e => e.status === "downloaded" || (e.file_path && e.status === "downloading")).length;
  const seasonTitle = seasonNumber === 0
    ? (CURRENT_LANG === "en" ? "Specials" : "Спецвыпуски")
    : `${t("show.season")} ${seasonNumber}`;
  const targetShowId = show ? show.id : CURRENT_SHOW_ID;

  let isCollapsed = true;
  const expandedSet = SHOW_EXPANDED_SEASONS[targetShowId];
  if (expandedSet !== undefined) {
    isCollapsed = !expandedSet.has(seasonNumber);
  } else {
    isCollapsed = (seasonNumber !== 1);
  }

  return `
    <div class="season-block ${isCollapsed ? "collapsed" : ""}" id="season-block-${seasonNumber}">
      <div class="season-header" onclick="toggleSeasonCollapse(${seasonNumber})">
        <div class="season-header-left">
          <i data-lucide="chevron-down" class="season-caret ico-sm"></i>
          <span>${seasonTitle}</span>
          <span class="season-progress">${downloaded}/${episodes.length} ${t("status.downloaded")}</span>
        </div>
        <div class="row-actions" onclick="event.stopPropagation()" style="display:flex;align-items:center;gap:8px;">
          ${canManageLib && seasonNumber === 0 ? `
          <button class="btn btn-secondary btn-small btn-specials-import" id="btn-specials-import-${targetShowId}" onclick="openSpecialsImportModal(${targetShowId})" title="${t("show.import_specials_tooltip")}">
            <i data-lucide="sparkles" class="ico-xs"></i> <span>${t("show.import_specials")}</span>
          </button>` : ""}
          ${canSearch ? `
          <button class="btn btn-primary btn-small" title="${CURRENT_LANG === "en" ? `Auto search and download season ${seasonNumber}` : `Автоматический поиск и скачивание всех серий сезона ${seasonNumber}`}" onclick="searchSeasonAuto(this, ${targetShowId}, ${seasonNumber})">
            <i data-lucide="zap" class="ico-xs"></i> <span>${CURRENT_LANG === "en" ? "Auto Search Season" : "Автопоиск сезона"}</span>
          </button>
          <button class="btn btn-secondary btn-small" title="${CURRENT_LANG === "en" ? `Interactive search season ${seasonNumber}` : `Интерактивный поиск сезона ${seasonNumber}`}" onclick="openInteractiveSearch(${targetShowId}, ${seasonNumber}, null)">
            <i data-lucide="search" class="ico-xs"></i> <span>${CURRENT_LANG === "en" ? "Interactive Search" : "Интерактивный поиск"}</span>
          </button>` : ""}
          ${canManageLib ? `
          <button class="btn-icon-only" title="${t("action.monitor_season")}" onclick="setSeasonMonitor(${seasonNumber}, true)"><i data-lucide="bookmark" class="ico-xs"></i></button>
          <button class="btn-icon-only" title="${t("action.unmonitor_season")}" onclick="setSeasonMonitor(${seasonNumber}, false)"><i data-lucide="bookmark-minus" class="ico-xs"></i></button>` : ""}
        </div>
      </div>
      <div class="season-episodes">
        ${canSearch ? `
        <div class="episode-row episode-row-bulk" onclick="event.stopPropagation()" style="background:var(--panel-alt);border-bottom:1px solid var(--border);padding:6px 12px;display:flex;align-items:center;gap:10px;">
          <label class="checkbox-row" style="margin:0;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:6px;">
            <input type="checkbox" class="season-select-all-checkbox" onchange="toggleSelectAllSeason(${seasonNumber}, this.checked)">
            <span style="font-weight:500;">${CURRENT_LANG === "en" ? "Select all" : "Выбрать все"}</span>
          </label>
          <div style="flex:1"></div>
          <button class="btn btn-secondary btn-small" id="btn-download-selected-${seasonNumber}" onclick="searchSelectedEpisodes(this, ${seasonNumber})" title="${CURRENT_LANG === "en" ? "Download selected episodes" : "Скачать отмеченные серии сезона"}">
            <i data-lucide="download" class="ico-xs"></i> <span id="btn-download-selected-label-${seasonNumber}">${CURRENT_LANG === "en" ? "Download selected" : "Скачать выбранные серии"}</span>
          </button>
        </div>` : ""}
        ${episodes.map(ep => renderEpisodeRow(ep, canManageLib, show)).join("")}
      </div>
    </div>`;
}

function renderEpisodeRow(ep, canManageLib = true, show = null) {
  const monitored = ep.monitored !== undefined ? Boolean(ep.monitored) : ep.status !== "ignored";
  const canSearch = hasPermission("manual_search");
  
  const hasFile = Boolean(ep.has_file || ep.file_path);
  const isUpgrading = Boolean(ep.status === "downloading" && hasFile);
  const isFreshDownloading = Boolean(ep.status === "downloading" && !hasFile);

  let statusHtml = "";
  const pct = Math.min(100, Math.max(0, (ep.download_progress || 0) * 100)).toFixed(1);

  if (isUpgrading) {
    statusHtml = `
      <div class="status-pill status-upgrading" title="${t("status.upgrading_title")}">
        <div class="status-pill-fill" style="width:${pct}%;"></div>
        <span class="status-pill-text">
          <i data-lucide="refresh-cw" class="status-pill-ico status-pill-spin"></i>
          <span>${t("status.upgrading")}</span>
        </span>
      </div>
    `;
  } else if (isFreshDownloading) {
    statusHtml = `
      <div class="status-pill status-downloading-progress" title="${t("status.downloading")}">
        <div class="status-pill-fill" style="width:${pct}%;"></div>
        <span class="status-pill-text">
          <i data-lucide="download" class="status-pill-ico"></i>
          <span>${t("status.downloading")}</span>
        </span>
      </div>
    `;
  } else {
    statusHtml = `<span class="status-pill status-${ep.status}">${escapeHtml(episodeStatusLabel(ep.status))}</span>`;
  }

  const hasFileBadge = hasFile
    ? `<span class="badge-file-present" title="${ep.file_path ? t("show.present_on_disk") + ': ' + escapeHtml(ep.file_path) : t("show.present_on_disk")}"><i data-lucide="hard-drive"></i> ${ep.downloaded_quality ? escapeHtml(ep.downloaded_quality) : t("show.on_disk")}</span>`
    : "";

  // MediaInfo бейджи
  let mediaInfoBadges = "";
  if (hasFile) {
    if (ep.dynamic_range) mediaInfoBadges += `<span class="badge-hdr">${escapeHtml(ep.dynamic_range)}</span> `;
    if (ep.video_codec) mediaInfoBadges += `<span class="badge-quality" style="font-size:10px;">${escapeHtml(ep.video_codec)}</span> `;
    if (ep.audio_codec) mediaInfoBadges += `<span class="badge-audio">${escapeHtml(ep.audio_codec)}</span> `;
    if (ep.release_group) mediaInfoBadges += `<span class="badge-group">${escapeHtml(ep.release_group)}</span> `;
  }

  let epCodeHtml = "";
  const isAnime = Boolean(show && show.content_type === "anime");
  if (isAnime) {
    if (ep.season_number === 0) {
      epCodeHtml = `<span class="ep-code" title="${CURRENT_LANG === 'en' ? 'Special' : 'Спецвыпуск'} ${ep.episode_number}">SP ${pad(ep.episode_number)}</span>`;
    } else if (ep.absolute_number != null) {
      epCodeHtml = `<span class="ep-code" title="S${pad(ep.season_number)}E${pad(ep.episode_number)}">${ep.absolute_number}</span>`;
    } else {
      epCodeHtml = `<span class="ep-code" title="S${pad(ep.season_number)}E${pad(ep.episode_number)}">${ep.episode_number}</span>`;
    }
  } else {
    if (ep.season_number === 0) {
      epCodeHtml = `<span class="ep-code" title="${CURRENT_LANG === 'en' ? 'Special' : 'Спецвыпуск'} ${ep.episode_number}">SP${pad(ep.episode_number)}</span>`;
    } else {
      epCodeHtml = `<span class="ep-code">S${pad(ep.season_number)}E${pad(ep.episode_number)}</span>`;
    }
  }

  const showId = show ? show.id : (ep.show_id || CURRENT_SHOW_ID || 0);

  return `
    <div class="episode-row" id="episode-row-${ep.id}" data-episode-id="${ep.id}" data-status="${ep.status}">
      <input type="checkbox" class="ep-select-checkbox" data-episode-id="${ep.id}" onchange="updateGlobalEpisodeSelectionState()" style="margin-right:6px;cursor:pointer;">
      ${epCodeHtml}
      <span class="ep-title">${escapeHtml(ep.title || "—")}</span>
      ${renderAirDateBadge(ep.air_date)}
      ${mediaInfoBadges ? `<div class="ep-mediainfo-tags" style="display:inline-flex; align-items:center; gap:3px; margin: 0 6px;">${mediaInfoBadges}</div>` : ""}
      ${hasFileBadge}
      ${statusHtml}
      <div class="ep-actions" style="display:inline-flex; align-items:center; gap:4px;">
        ${canSearch ? `
        <button class="btn-icon-only" title="${CURRENT_LANG === 'en' ? 'Interactive search' : 'Интерактивный поиск'} ${ep.episode_number}" onclick="openInteractiveSearch(${showId}, ${ep.season_number}, ${ep.episode_number})">
          <i data-lucide="search" class="ico-xs"></i>
        </button>` : ""}
        ${canManageLib ? `
        <button class="btn-icon-only ${monitored ? "active" : ""}" title="${monitored ? t("action.unmonitor") : t("action.monitor")}"
          onclick="toggleEpisodeMonitor(${ep.id}, ${monitored})"><i data-lucide="bookmark" class="ico-xs"></i></button>` : ""}
      </div>
    </div>`;
}

function renderAirDateBadge(airDateStr) {
  if (!airDateStr) return "";
  const airDate = new Date(airDateStr);
  const now = new Date();
  if (airDate <= now) {
    return `<span class="hint" style="margin-left:8px;font-size:0.85em;">${t("status.aired")}</span>`;
  } else {
    return `<span class="hint" style="margin-left:8px;font-size:0.85em;">${formatDateOnly(airDateStr)}</span>`;
  }
}

async function searchSeasonAuto(button, showId, seasonNumber) {
  const sId = showId || CURRENT_SHOW_ID;
  if (!sId) return;
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/shows/${sId}/search-season/${seasonNumber}`, {
        method: "POST",
      });
      toast(result.message, !result.success);
      await refreshShowModal();
    } catch (e) {
      toast("Ошибка: " + e.message, true);
    }
  });
}

function toggleSelectAllSeason(seasonNumber, isChecked) {
  const block = document.getElementById(`season-block-${seasonNumber}`);
  if (!block) return;
  const checkboxes = block.querySelectorAll('.ep-select-checkbox');
  checkboxes.forEach(cb => cb.checked = isChecked);
  updateGlobalEpisodeSelectionState();
}

function updateGlobalEpisodeSelectionState() {
  const allChecked = Array.from(document.querySelectorAll('#show-modal-content .ep-select-checkbox:checked'));
  const totalCount = allChecked.length;

  // Обновляем состояние чекбоксов "Выбрать все" и кнопок в каждом сезоне
  const seasonBlocks = document.querySelectorAll('#show-modal-content .season-block');
  seasonBlocks.forEach(block => {
    const seasonId = block.id.replace('season-block-', '');
    const seasonCbs = Array.from(block.querySelectorAll('.ep-select-checkbox'));
    const seasonChecked = seasonCbs.filter(cb => cb.checked);
    const selectAllCb = block.querySelector('.season-select-all-checkbox');
    if (selectAllCb) {
      selectAllCb.checked = seasonCbs.length > 0 && seasonChecked.length === seasonCbs.length;
      selectAllCb.indeterminate = seasonChecked.length > 0 && seasonChecked.length < seasonCbs.length;
    }
    const labelSpan = document.getElementById(`btn-download-selected-label-${seasonId}`);
    const btn = document.getElementById(`btn-download-selected-${seasonId}`);
    if (labelSpan) {
      if (totalCount > 0) {
        labelSpan.textContent = CURRENT_LANG === "en" ? `Download selected (${totalCount})` : `Скачать выбранные (${totalCount})`;
        if (btn) btn.classList.replace("btn-secondary", "btn-primary");
      } else {
        labelSpan.textContent = CURRENT_LANG === "en" ? "Download selected" : "Скачать выбранные серии";
        if (btn) btn.classList.replace("btn-primary", "btn-secondary");
      }
    }
  });

  // Обновляем кнопку в панели действий карточки
  const showBtn = document.getElementById("btn-show-download-selected");
  const showBtnLabel = document.getElementById("btn-show-download-selected-label");
  if (showBtn) {
    if (totalCount > 0) {
      showBtn.style.display = "inline-flex";
      if (showBtnLabel) {
        showBtnLabel.textContent = CURRENT_LANG === "en" ? `Download selected (${totalCount})` : `Скачать выбранные (${totalCount})`;
      }
    } else {
      showBtn.style.display = "none";
    }
  }
}

function updateSeasonSelectionState(seasonNumber) {
  updateGlobalEpisodeSelectionState();
}

async function searchSelectedEpisodes(button, seasonNumber = null) {
  // 1. Проверяем все явно отмеченные чекбоксами серии во всех сезонах
  const allCheckedBoxes = Array.from(document.querySelectorAll('#show-modal-content .ep-select-checkbox:checked'));
  let episodeIds = allCheckedBoxes.map(cb => Number(cb.dataset.episodeId)).filter(id => id);

  // 2. Если ни один чекбокс не выбран, но кнопка нажата в конкретном сезоне
  if (!episodeIds.length && seasonNumber !== null) {
    const block = document.getElementById(`season-block-${seasonNumber}`);
    if (block) {
      const wantedRows = block.querySelectorAll('.episode-row[data-status="wanted"]');
      episodeIds = Array.from(wantedRows).map(row => Number(row.dataset.episodeId)).filter(id => id);
      if (!episodeIds.length) {
        const allRows = block.querySelectorAll('.episode-row[data-episode-id]');
        episodeIds = Array.from(allRows).map(row => Number(row.dataset.episodeId)).filter(id => id);
      }
    }
  }

  // 3. Если ни один чекбокс не выбран и кнопка нажата в глобальной шапке
  if (!episodeIds.length && seasonNumber === null) {
    const wantedRows = document.querySelectorAll('#show-modal-content .episode-row[data-status="wanted"]');
    episodeIds = Array.from(wantedRows).map(row => Number(row.dataset.episodeId)).filter(id => id);
  }

  if (!episodeIds.length) {
    toast(CURRENT_LANG === "en" ? "No episodes selected" : "Не выбрано ни одной серии", true);
    return;
  }

  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/shows/${CURRENT_SHOW_ID}/search-episodes`, {
        method: "POST",
        body: JSON.stringify({ episode_ids: episodeIds }),
      });
      toast(result.message, !result.success);
      await refreshShowModal();
    } catch (e) {
      toast("Ошибка: " + e.message, true);
    }
  });
}

function toggleSeasonCollapse(seasonNumber) {
  const el = document.getElementById(`season-block-${seasonNumber}`);
  if (el) {
    el.classList.toggle("collapsed");
    const isExpanded = !el.classList.contains("collapsed");
    const targetShowId = CURRENT_SHOW_ID;
    if (targetShowId) {
      if (!SHOW_EXPANDED_SEASONS[targetShowId]) {
        SHOW_EXPANDED_SEASONS[targetShowId] = new Set();
      }
      if (isExpanded) {
        SHOW_EXPANDED_SEASONS[targetShowId].add(seasonNumber);
      } else {
        SHOW_EXPANDED_SEASONS[targetShowId].delete(seasonNumber);
      }
    }
  }
}

function expandAllSeasons() {
  document.querySelectorAll("#seasons-container .season-block").forEach(el => {
    el.classList.remove("collapsed");
    const sn = parseInt(el.id.replace("season-block-", ""), 10);
    if (!isNaN(sn) && CURRENT_SHOW_ID) {
      if (!SHOW_EXPANDED_SEASONS[CURRENT_SHOW_ID]) {
        SHOW_EXPANDED_SEASONS[CURRENT_SHOW_ID] = new Set();
      }
      SHOW_EXPANDED_SEASONS[CURRENT_SHOW_ID].add(sn);
    }
  });
}

function collapseAllSeasons() {
  document.querySelectorAll("#seasons-container .season-block").forEach(el => {
    el.classList.add("collapsed");
  });
  if (CURRENT_SHOW_ID) {
    SHOW_EXPANDED_SEASONS[CURRENT_SHOW_ID] = new Set();
  }
}

async function changeQualityProfile(showId, value) {
  try {
    const qpId = value ? Number(value) : null;
    await api(`/api/v1/shows/${showId}`, {
      method: "PUT",
      body: JSON.stringify({ quality_profile_id: qpId }),
    });
    if (typeof CACHED_SHOWS !== "undefined" && CACHED_SHOWS) {
      const s = CACHED_SHOWS.find(x => x.id === showId);
      if (s) s.quality_profile_id = qpId;
    }
    if (typeof ALL_SHOWS !== "undefined" && ALL_SHOWS) {
      const sAll = ALL_SHOWS.find(x => x.id === showId);
      if (sAll) sAll.quality_profile_id = qpId;
    }
    renderLibrary();
    toast(t("settings.toast_saved"));
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function changeContentType(showId, value) {
  const confirmed = await confirmModal(
    t("show.confirm_change_category"),
    { danger: false }
  );
  if (!confirmed) { await refreshShowModal(); return; }
  try {
    await api(`/api/v1/shows/${showId}`, { method: "PUT", body: JSON.stringify({ content_type: value }) });
    toast(t("settings.toast_saved"));
    await refreshShowModal();
    await loadShows();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function toggleMonitored(button, showId, value) {
  await withLoading(button, async () => {
    try {
      await api(`/api/v1/shows/${showId}/monitor?monitored=${value}`, { method: "PUT" });
      toast(value ? t("status.monitored") : t("status.unmonitored"));
      await refreshShowModal();
      loadShows();
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

let PENDING_DELETE_SHOW_ID = null;

function deleteShow(showId) {
  PENDING_DELETE_SHOW_ID = showId;
  const show = (typeof CACHED_SHOWS !== "undefined" && CACHED_SHOWS) ? CACHED_SHOWS.find(s => s.id === showId) : null;
  const title = show ? show.title : "";
  const path = show ? show.path : "";

  const msgEl = document.getElementById("delete-show-modal-msg");
  if (msgEl) {
    msgEl.innerHTML = `${CURRENT_LANG === "en" ? "Are you sure you want to delete" : "Вы действительно хотите удалить карточку"} <strong>«${escapeHtml(title || (CURRENT_LANG === "en" ? "this title" : "этот тайтл"))}»</strong>?`;
  }
  const cb = document.getElementById("delete-show-files-checkbox");
  if (cb) cb.checked = false;

  const pathHint = document.getElementById("delete-show-path-hint");
  if (pathHint) {
    if (path) {
      pathHint.textContent = `${CURRENT_LANG === "en" ? "Directory on disk: " : "Директория на диске: "}${path}`;
    } else {
      pathHint.textContent = t("show.delete_files_hint");
    }
  }

  openModal("delete-show-modal");
  if (window.lucide) lucide.createIcons();
}

async function executeShowDeletion() {
  if (!PENDING_DELETE_SHOW_ID) return;
  const showId = PENDING_DELETE_SHOW_ID;
  const deleteFiles = !!document.getElementById("delete-show-files-checkbox")?.checked;
  const btn = document.getElementById("delete-show-confirm-btn");

  await withLoading(btn, async () => {
    try {
      await api(`/api/v1/shows/${showId}?delete_files=${deleteFiles}`, { method: "DELETE" });
      closeModal("delete-show-modal");
      closeModal("show-modal");
      toast(deleteFiles
        ? (CURRENT_LANG === "en" ? "Card and files successfully deleted" : "Карточка и файлы успешно удалены")
        : (CURRENT_LANG === "en" ? "Card deleted" : "Карточка успешно удалена")
      );
      PENDING_DELETE_SHOW_ID = null;
      await loadShows();
    } catch (e) {
      toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true);
    }
  });
}

async function setAllSeasonsMonitor(showId, value) {
  const targetId = showId || CURRENT_SHOW_ID;
  try {
    const result = await api(`/api/v1/shows/${targetId}/all_seasons/monitor?monitored=${Boolean(value)}`, { method: "PUT" });
    toast(value ? t("show.all_seasons_monitored") : t("show.all_seasons_unmonitored"), false);
    await refreshShowModal();
    if (typeof loadShows === "function") {
      loadShows().catch(() => {});
    }
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true);
  }
}

async function setUnairedMonitor(showId, value) {
  const targetId = showId || CURRENT_SHOW_ID;
  try {
    const result = await api(`/api/v1/shows/${targetId}/unaired/monitor?monitored=${Boolean(value)}`, { method: "PUT" });
    toast(value ? t("show.unaired_monitored") : t("show.all_seasons_unmonitored"), false);
    await refreshShowModal();
    if (typeof loadShows === "function") {
      loadShows().catch(() => {});
    }
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true);
  }
}

async function setSeasonMonitor(seasonNumber, value) {
  try {
    const result = await api(`/api/v1/shows/${CURRENT_SHOW_ID}/seasons/${seasonNumber}/monitor?monitored=${value}`, { method: "PUT" });
    toast(`${t("common.confirm")}: ${result.affected}`);
    await refreshShowModal();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function toggleEpisodeMonitor(episodeId, currentlyMonitored) {
  const newMonitored = !currentlyMonitored;
  try {
    await api(`/api/v1/episodes/${episodeId}/monitor?monitored=${newMonitored}`, { method: "PUT" });
    await refreshShowModal();
    if (typeof loadShows === "function") {
      loadShows().catch(() => {});
    }
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function searchSingleEpisode(button, episodeId) {
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/episodes/${episodeId}/search`, { method: "POST" });
      toast(result.message, !result.success);
      await refreshShowModal();
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

async function syncShowPath(showId) {
  try {
    const res = await api(`/api/v1/shows/${showId}/sync_disk`, { method: "POST" });
    toast(`${t("common.confirm")}: ${res.imported_count || 0}`, false);
    await refreshShowModal();
  } catch (e) {
    toast("Ошибка: " + e.message, true);
  }
}

// ---------------------------------------------------------------------------
// УПОРЯДОЧИТЬ И ПЕРЕИМЕНОВАТЬ (PREVIEW RENAME & ORGANIZE)
// ---------------------------------------------------------------------------

let RENAME_MODAL_STATE = {
  showId: null,
  seasonNumber: null,
  items: [],
};

async function openPreviewRenameModal(showId, seasonNumber = null) {
  RENAME_MODAL_STATE.showId = showId;
  RENAME_MODAL_STATE.seasonNumber = seasonNumber;
  RENAME_MODAL_STATE.items = [];

  const container = document.getElementById("rename-items-container");
  const emptyState = document.getElementById("rename-empty-state");
  const basePathEl = document.getElementById("rename-base-path");
  const tplTextEl = document.getElementById("rename-template-text");
  const counterEl = document.getElementById("rename-counter");
  const selectAllCb = document.getElementById("rename-select-all-cb");
  const btnExec = document.getElementById("btn-execute-rename");

  if (container) {
    container.innerHTML = `<div style="text-align:center; padding:30px; color:var(--text-muted);"><span class="spin-icon">↻</span> ${t("common.loading")}</div>`;
  }
  if (emptyState) emptyState.style.display = "none";
  if (counterEl) counterEl.textContent = "";
  if (btnExec) btnExec.disabled = true;

  openModal("modal-preview-rename");

  try {
    const url = seasonNumber !== null
      ? `/api/v1/shows/${showId}/rename/preview?season=${seasonNumber}`
      : `/api/v1/shows/${showId}/rename/preview`;
    const data = await api(url);

    RENAME_MODAL_STATE.items = data.items || [];
    if (basePathEl) basePathEl.textContent = data.show_path || "—";
    if (tplTextEl) tplTextEl.textContent = data.naming_template || "—";

    if (!data.items || data.items.length === 0) {
      if (container) container.innerHTML = "";
      if (emptyState) emptyState.style.display = "block";
      if (btnExec) btnExec.disabled = true;
      if (counterEl) counterEl.textContent = "";
      return;
    }

    if (container) {
      container.innerHTML = data.items.map(item => `
        <div class="rename-diff-row" style="display: flex; align-items: flex-start; gap: 12px; padding: 12px 6px; border-bottom: 1px solid var(--border-color, rgba(255,255,255,0.06));">
          <input type="checkbox" class="rename-item-cb" data-ep-id="${item.episode_id}" ${item.needs_rename ? "checked" : ""} onchange="updateRenameCount()" style="margin-top: 4px; cursor: pointer; transform: scale(1.15);">
          <div style="flex: 1; min-width: 0; font-family: monospace; font-size: 13px; line-height: 1.5;">
            <div style="display: flex; align-items: baseline; word-break: break-all; margin-bottom: 4px;">
              <span style="color: #ef4444; font-weight: bold; margin-right: 8px; flex-shrink: 0; font-size: 14px;">—</span>
              <span style="color: #f87171;">${escapeHtml(item.existing_rel_path)}</span>
            </div>
            <div style="display: flex; align-items: baseline; word-break: break-all;">
              <span style="color: #22c55e; font-weight: bold; margin-right: 8px; flex-shrink: 0; font-size: 14px;">+</span>
              <span style="color: #4ade80;">${escapeHtml(item.new_rel_path)}</span>
            </div>
          </div>
        </div>
      `).join("");
    }

    if (selectAllCb) {
      const anyRenames = data.items.some(i => i.needs_rename);
      selectAllCb.checked = anyRenames;
    }

    updateRenameCount();

    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  } catch (err) {
    if (container) {
      container.innerHTML = `<p style="color:var(--danger); padding:16px;">${CURRENT_LANG === "en" ? "Failed to load rename preview:" : "Ошибка предпросмотра:"} ${escapeHtml(err.message)}</p>`;
    }
  }
}

function toggleRenameSelectAll(checked) {
  const checkboxes = document.querySelectorAll("#rename-items-container .rename-item-cb");
  checkboxes.forEach(cb => { cb.checked = checked; });
  updateRenameCount();
}

function updateRenameCount() {
  const checkboxes = document.querySelectorAll("#rename-items-container .rename-item-cb");
  const total = checkboxes.length;
  const selected = Array.from(checkboxes).filter(cb => cb.checked).length;

  const counterEl = document.getElementById("rename-counter");
  if (counterEl) {
    counterEl.textContent = `(${CURRENT_LANG === "en" ? `Selected: ${selected} of ${total}` : `Выбрано: ${selected} из ${total}`})`;
  }

  const btnExec = document.getElementById("btn-execute-rename");
  if (btnExec) {
    btnExec.disabled = (selected === 0);
  }

  const selectAllCb = document.getElementById("rename-select-all-cb");
  if (selectAllCb) {
    selectAllCb.checked = (selected === total && total > 0);
    selectAllCb.indeterminate = (selected > 0 && selected < total);
  }
}

async function executeRename(btn) {
  const checkboxes = document.querySelectorAll("#rename-items-container .rename-item-cb:checked");
  const episodeIds = Array.from(checkboxes).map(cb => Number(cb.getAttribute("data-ep-id"))).filter(Boolean);

  if (!episodeIds.length || !RENAME_MODAL_STATE.showId) return;

  await withLoading(btn, async () => {
    try {
      const res = await api(`/api/v1/shows/${RENAME_MODAL_STATE.showId}/rename/execute`, {
        method: "POST",
        body: JSON.stringify({ episode_ids: episodeIds }),
      });

      if (res.errors && res.errors.length > 0) {
        toast(`Переименовано ${res.renamed_count} файлов, ошибок: ${res.errors.length}`, true);
      } else {
        const msg = CURRENT_LANG === "en"
          ? `Successfully renamed ${res.renamed_count} file(s)`
          : `Успешно переименовано ${res.renamed_count} файл(ов)`;
        toast(msg);
      }

      closeModal("modal-preview-rename");

      // Обновляем карточку тайтла
      if (typeof openShowDetailModal === "function" && CURRENT_SHOW_ID === RENAME_MODAL_STATE.showId) {
        openShowDetailModal(RENAME_MODAL_STATE.showId);
      }
    } catch (e) {
      toast("Ошибка: " + e.message, true);
    }
  });
}

// ---------------------------------------------------------------------------
// РУЧНОЙ ИМПОРТ ФАЙЛОВ
// ---------------------------------------------------------------------------

let CURRENT_MANUAL_IMPORT_SHOW_ID = null;
let CURRENT_MANUAL_IMPORT_DATA = null;
let CURRENT_MANUAL_IMPORT_SEASON_FILTER = null;

async function checkSpecialsImportStatus(showId) {
  try {
    const res = await api(`/api/v1/shows/${showId}/specials-import-status`);
    const btn = document.getElementById(`btn-specials-import-${showId}`);
    if (btn) {
      if (res && res.has_pending_specials) {
        btn.classList.remove("btn-secondary");
        btn.classList.add("btn-success", "btn-specials-ready");
        btn.title = t("show.import_specials_ready");
        btn.setAttribute("data-pending-folder", res.pending_folder || "");
      } else {
        btn.classList.remove("btn-success", "btn-specials-ready");
        btn.classList.add("btn-secondary");
        btn.removeAttribute("data-pending-folder");
      }
    }
  } catch (e) {
    // ignore
  }
}

async function openSpecialsImportModal(showId) {
  let pendingFolder = null;
  const btn = document.getElementById(`btn-specials-import-${showId}`);
  if (btn) {
    pendingFolder = btn.getAttribute("data-pending-folder") || null;
  }
  if (!pendingFolder) {
    try {
      const res = await api(`/api/v1/shows/${showId}/specials-import-status`);
      if (res && res.pending_folder) {
        pendingFolder = res.pending_folder;
      }
    } catch (e) {}
  }
  await openManualImportModal(showId, pendingFolder, 0);
}

async function openManualImportModal(showId, customFolder = null, seasonFilter = null) {
  CURRENT_MANUAL_IMPORT_SHOW_ID = showId;
  CURRENT_MANUAL_IMPORT_SEASON_FILTER = seasonFilter;
  openModal("manual-import-modal");
  const content = document.getElementById("manual-import-modal-content");
  content.innerHTML = `<div style="padding: 30px; text-align: center;"><p>${t("common.loading")}</p></div>`;

  try {
    let show = null;
    try {
      show = await api(`/api/v1/shows/${showId}`);
    } catch (e) { /* fallback */ }

    const initialFolder = (customFolder || (show && show.path) || "").trim();
    await scanManualImportFolder(showId, initialFolder);
  } catch (e) {
    content.innerHTML = `<p style="color:var(--danger); padding:20px;">${CURRENT_LANG === "en" ? "Error:" : "Ошибка:"} ${escapeHtml(formatToastMessage(e.message))}</p>`;
  }
}

async function scanManualImportFolder(showId, folderPath = null) {
  const content = document.getElementById("manual-import-modal-content");
  const pathInputVal = document.getElementById("manual-import-path-input")?.value;
  const targetPath = (folderPath !== null ? folderPath : (pathInputVal || "")).trim();
  const isSpecialsOnly = (CURRENT_MANUAL_IMPORT_SEASON_FILTER === 0);
  const modalTitle = isSpecialsOnly ? t("manual_import.title_specials") : t("manual_import.title");
  const modalIcon = isSpecialsOnly ? "sparkles" : "hard-drive-download";
  const iconColor = isSpecialsOnly ? "color:#10b981;" : "";

  content.innerHTML = `
    <div class="manual-import-header">
      <div style="font-size: 16px; font-weight: 600; color: var(--text);">
        <i data-lucide="${modalIcon}" class="ico-sm" style="vertical-align: middle; margin-right: 6px; ${iconColor}"></i>
        ${modalTitle}
      </div>
      <div class="manual-import-mode-row">
        <label style="font-size: 13px; color: var(--text-muted);">${t("manual_import.mode_label")}</label>
        <select id="manual-import-mode-select" class="input input-small" style="width: auto;">
          <option value="move">${t("manual_import.mode_move")}</option>
          <option value="copy">${t("manual_import.mode_copy")}</option>
        </select>
      </div>
    </div>

    <div class="manual-import-path-row" style="margin-bottom: 14px;">
      <input id="manual-import-path-input" class="input" type="text" value="${escapeHtml(targetPath)}" placeholder="${t("manual_import.folder_placeholder")}" onkeydown="if(event.key==='Enter') scanManualImportFolder(${showId})">
      <button class="btn btn-secondary" onclick="openFolderPicker('manual-import-path-input')" title="${t("common.browse")}"><i data-lucide="folder" class="ico-sm"></i> ${t("common.browse")}</button>
      <button class="btn btn-primary" onclick="scanManualImportFolder(${showId})"><i data-lucide="search" class="ico-sm"></i> ${t("manual_import.scan")}</button>
    </div>

    <div style="padding: 40px; text-align: center;">
      <p class="hint">${t("common.loading")}</p>
    </div>
  `;

  if (window.lucide) lucide.createIcons();

  try {
    const payload = targetPath ? { folder_path: targetPath } : {};
    const data = await api(`/api/v1/shows/${showId}/manual-import/scan`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    CURRENT_MANUAL_IMPORT_DATA = data;
    renderManualImportView(showId, data);
  } catch (e) {
    content.innerHTML = `
      <div class="manual-import-header">
        <div style="font-size: 16px; font-weight: 600; color: var(--text);">
          <i data-lucide="${modalIcon}" class="ico-sm" style="vertical-align: middle; margin-right: 6px; ${iconColor}"></i>
          ${modalTitle}
        </div>
      </div>
      <div class="manual-import-path-row" style="margin-bottom: 14px;">
        <input id="manual-import-path-input" class="input" type="text" value="${escapeHtml(targetPath)}" placeholder="${t("manual_import.folder_placeholder")}">
        <button class="btn btn-secondary" onclick="openFolderPicker('manual-import-path-input')"><i data-lucide="folder" class="ico-sm"></i> ${t("common.browse")}</button>
        <button class="btn btn-primary" onclick="scanManualImportFolder(${showId})"><i data-lucide="search" class="ico-sm"></i> ${t("manual_import.scan")}</button>
      </div>
      <div style="padding: 20px; background: rgba(239, 68, 68, 0.1); border: 1px solid var(--danger); border-radius: 6px; color: var(--danger);">
        ${escapeHtml(formatToastMessage(e.message))}
      </div>
    `;
    if (window.lucide) lucide.createIcons();
  }
}

function renderManualImportView(showId, data) {
  const content = document.getElementById("manual-import-modal-content");
  const files = data.files || [];
  const episodes = data.episodes || [];
  const currentMode = document.getElementById("manual-import-mode-select")?.value || "move";
  const isSpecialsOnly = (CURRENT_MANUAL_IMPORT_SEASON_FILTER === 0);
  const modalTitle = isSpecialsOnly ? t("manual_import.title_specials") : t("manual_import.title");
  const modalIcon = isSpecialsOnly ? "sparkles" : "hard-drive-download";
  const iconColor = isSpecialsOnly ? "color:#10b981;" : "";

  let showInfo = null;
  try {
    showInfo = (typeof ALL_SHOWS !== "undefined" && ALL_SHOWS ? ALL_SHOWS.find(s => s.id === showId) : null)
      || (typeof CACHED_SHOWS !== "undefined" && CACHED_SHOWS ? CACHED_SHOWS.find(s => s.id === showId) : null);
  } catch (e) {}

  const isMovie = Boolean((data && data.content_type === "movie") || (showInfo && showInfo.content_type === "movie"));
  const isAnime = Boolean((data && data.content_type === "anime") || (showInfo && showInfo.content_type === "anime"));
  const showTitle = (data && data.show_title) || showInfo?.title || "";
  const showYear = (data && data.show_year) || showInfo?.year || "";

  const displayEpisodes = isSpecialsOnly
    ? (episodes.filter(e => e.season_number === 0).length ? episodes.filter(e => e.season_number === 0) : episodes)
    : episodes;

  const qualityOptions = QUALITY_OPTIONS;

  let rowsHtml = "";
  if (!files.length) {
    rowsHtml = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 30px;">${t("manual_import.no_files")}</td></tr>`;
  } else {
    rowsHtml = files.map((file, idx) => {
      const isMatched = file.matched_episode_id != null && (!isSpecialsOnly || displayEpisodes.some(e => e.id === file.matched_episode_id));
      const sizeStr = file.size_bytes ? formatBytes(file.size_bytes) : "";

      // Dropdown с сериями тайтла или фильмом
      const epOptions = [
        `<option value="">${t("manual_import.skip")}</option>`,
        ...displayEpisodes.map(ep => {
          let label = "";
          if (isMovie) {
            label = `${escapeHtml(showTitle || ep.title || (CURRENT_LANG === 'en' ? 'Movie' : 'Фильм'))}${showYear ? ` (${showYear})` : ""}`;
          } else if (ep.season_number === 0) {
            label = `${CURRENT_LANG === 'en' ? 'Special' : 'Спецвыпуск'} ${ep.episode_number}: ${escapeHtml(ep.title || "—")}`;
          } else if (isAnime && ep.absolute_number != null) {
            label = `${CURRENT_LANG === 'en' ? 'Ep.' : 'Серия'} ${ep.absolute_number}: ${escapeHtml(ep.title || "—")} (S${pad(ep.season_number)}E${pad(ep.episode_number)})`;
          } else {
            label = `S${pad(ep.season_number)}E${pad(ep.episode_number)}: ${escapeHtml(ep.title || "—")}`;
          }
          const sel = ep.id === file.matched_episode_id ? "selected" : "";
          return `<option value="${ep.id}" ${sel}>${label}</option>`;
        })
      ].join("");

      // Dropdown с качеством
      const qOptions = qualityOptions.map(q => {
        const sel = (file.detected_quality && file.detected_quality.toLowerCase() === q.toLowerCase()) ? "selected" : "";
        return `<option value="${q}" ${sel}>${q}</option>`;
      }).join("");

      let statusBadge = "";
      if (file.existing_file) {
        statusBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b;" title="${escapeHtml(file.existing_file)}">${t("manual_import.overwrite")}</span>`;
      } else if (isMatched) {
        statusBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">${t("manual_import.ready")}</span>`;
      } else {
        statusBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444;">${t("manual_import.not_matched")}</span>`;
      }

      return `
        <tr id="manual-import-row-${idx}" data-idx="${idx}" data-filepath="${escapeHtml(file.file_path)}">
          <td style="width: 40px; text-align: center;">
            <input type="checkbox" class="manual-import-item-check" data-idx="${idx}" ${isMatched ? "checked" : ""} onchange="onManualImportItemChange()">
          </td>
          <td class="manual-import-file-cell">
            <div class="manual-import-file-name" title="${escapeHtml(file.file_path)}">${escapeHtml(file.relative_path || file.filename)}</div>
            <div class="manual-import-file-meta">${sizeStr}</div>
          </td>
          <td style="width: 140px;">
            <select class="input input-small manual-import-quality-select" data-idx="${idx}">
              ${qOptions}
            </select>
          </td>
          <td style="min-width: 260px;">
            <select class="input input-small manual-import-episode-select" data-idx="${idx}" onchange="onManualImportEpisodeSelectChange(${idx})">
              ${epOptions}
            </select>
          </td>
          <td style="width: 140px; text-align: right;">
            <div id="manual-import-status-${idx}">${statusBadge}</div>
          </td>
        </tr>
      `;
    }).join("");
  }

  const seasonsList = Array.from(new Set(displayEpisodes.map(e => e.season_number))).sort((a, b) => a - b);

  content.innerHTML = `
    <div class="manual-import-header">
      <div style="font-size: 16px; font-weight: 600; color: var(--text);">
        <i data-lucide="${modalIcon}" class="ico-sm" style="vertical-align: middle; margin-right: 6px; ${iconColor}"></i>
        ${modalTitle}
      </div>
      <div class="manual-import-mode-row">
        <label style="font-size: 13px; color: var(--text-muted);">${t("manual_import.mode_label")}</label>
        <select id="manual-import-mode-select" class="input input-small" style="width: auto;">
          <option value="move" ${currentMode === "move" ? "selected" : ""}>${t("manual_import.mode_move")}</option>
          <option value="copy" ${currentMode === "copy" ? "selected" : ""}>${t("manual_import.mode_copy")}</option>
        </select>
      </div>
    </div>

    <div class="manual-import-path-row" style="margin-bottom: 12px;">
      <input id="manual-import-path-input" class="input" type="text" value="${escapeHtml(data.folder_path || "")}" placeholder="${t("manual_import.folder_placeholder")}" onkeydown="if(event.key==='Enter') scanManualImportFolder(${showId})">
      <button class="btn btn-secondary" onclick="openFolderPicker('manual-import-path-input')"><i data-lucide="folder" class="ico-sm"></i> ${t("common.browse")}</button>
      <button class="btn btn-primary" onclick="scanManualImportFolder(${showId})"><i data-lucide="search" class="ico-sm"></i> ${t("manual_import.scan")}</button>
    </div>

    <div class="manual-import-summary-bar">
      <div id="manual-import-summary-text">
        ${t("manual_import.summary").replace("{total}", files.length).replace("{selected}", files.filter(f => f.matched_episode_id != null).length)}
      </div>
    </div>

    ${files.length ? `
    <div class="manual-import-bulk-toolbar">
      <div class="bulk-group">
        <span class="bulk-label"><i data-lucide="sliders" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Quality:' : 'Качество:'}</span></span>
        <select id="bulk-manual-import-quality" class="input input-small" style="width: 140px;">
          <option value="">— ${CURRENT_LANG === 'en' ? 'Quality' : 'Качество'} —</option>
          ${qualityOptions.map(q => `<option value="${q}">${q}</option>`).join("")}
        </select>
        <button type="button" class="btn btn-secondary btn-small" onclick="applyBulkManualImportQuality()">
          <i data-lucide="check" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Apply to selected' : 'Применить к выбранным'}</span>
        </button>
      </div>
      ${!isMovie ? `
      <div class="bulk-group">
        <span class="bulk-label"><i data-lucide="list-ordered" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Episodes:' : 'Серии:'}</span></span>
        <select id="bulk-manual-import-season" class="input input-small" style="width: 160px;">
          ${seasonsList.map(sn => `<option value="${sn}">${sn === 0 ? (CURRENT_LANG === 'en' ? 'Specials (Season 0)' : 'Спецвыпуски (Сезон 0)') : (CURRENT_LANG === 'en' ? `Season ${sn}` : `Сезон ${sn}`)}</option>`).join("")}
        </select>
        <span style="font-size:12px; color:var(--text-muted);">${CURRENT_LANG === 'en' ? 'from №:' : 'с серии:'}</span>
        <input type="number" id="bulk-manual-import-start-ep" class="input input-small" style="width: 58px;" min="0" value="1">
        <button type="button" class="btn btn-secondary btn-small" onclick="applyBulkManualImportEpisodes()">
          <i data-lucide="arrow-down-narrow-wide" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Assign sequentially' : 'Задать по порядку'}</span>
        </button>
      </div>` : `
      <div class="bulk-group">
        <button type="button" class="btn btn-secondary btn-small" onclick="applyBulkManualImportMovie()">
          <i data-lucide="film" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Assign movie to selected' : 'Сопоставить фильм для выбранных'}</span>
        </button>
      </div>`}
    </div>` : ""}

    <div class="manual-import-table-wrap">
      <table class="manual-import-table">
        <thead>
          <tr>
            <th style="width: 40px; text-align: center;">
              <input type="checkbox" id="manual-import-select-all" ${files.some(f => f.matched_episode_id != null) ? "checked" : ""} onchange="onManualImportSelectAll(this.checked)">
            </th>
            <th>${t("manual_import.col_file")}</th>
            <th>${t("manual_import.col_quality")}</th>
            <th>${isMovie ? (CURRENT_LANG === 'en' ? 'Movie' : 'Фильм') : (isSpecialsOnly ? (CURRENT_LANG === 'en' ? 'Special Episode' : 'Спецвыпуск') : t("manual_import.col_episode"))}</th>
            <th style="text-align: right;">${t("manual_import.col_status")}</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    </div>

    <div class="manual-import-footer">
      <button class="btn btn-secondary" onclick="closeModal('manual-import-modal')">${t("common.cancel")}</button>
      <button id="manual-import-submit-btn" class="btn btn-primary" onclick="executeManualImport(${showId})" ${!files.length ? "disabled" : ""}>
        <i data-lucide="download" class="ico-sm"></i> <span>${t("manual_import.btn_import")}</span>
      </button>
    </div>
  `;

  if (window.lucide) lucide.createIcons();
  onManualImportItemChange();
}

function applyBulkManualImportQuality() {
  const bulkSelect = document.getElementById("bulk-manual-import-quality");
  if (!bulkSelect || !bulkSelect.value) {
    toast(CURRENT_LANG === "en" ? "Select a quality first" : "Сначала выберите качество в списке", true);
    return;
  }
  const quality = bulkSelect.value;
  const checkboxes = Array.from(document.querySelectorAll(".manual-import-item-check"));
  const checkedBoxes = checkboxes.filter(cb => cb.checked);
  const targetBoxes = checkedBoxes.length > 0 ? checkedBoxes : checkboxes;

  targetBoxes.forEach(cb => {
    const idx = cb.getAttribute("data-idx");
    const qSelect = document.querySelector(`.manual-import-quality-select[data-idx="${idx}"]`);
    if (qSelect) {
      qSelect.value = quality;
    }
  });
  toast(CURRENT_LANG === "en" ? `Quality set to ${quality} for ${targetBoxes.length} files` : `Качество «${quality}» задано для ${targetBoxes.length} файлов`);
}

function applyBulkManualImportEpisodes() {
  const seasonSelect = document.getElementById("bulk-manual-import-season");
  const startEpInput = document.getElementById("bulk-manual-import-start-ep");
  if (!seasonSelect || seasonSelect.value === "") {
    toast(CURRENT_LANG === "en" ? "Select a season first" : "Сначала выберите сезон", true);
    return;
  }

  const seasonNum = parseInt(seasonSelect.value, 10);
  let startEpNum = parseInt(startEpInput?.value || "1", 10);
  if (isNaN(startEpNum) || startEpNum < 0) startEpNum = 1;

  if (!CURRENT_MANUAL_IMPORT_DATA || !CURRENT_MANUAL_IMPORT_DATA.episodes) return;
  const episodes = CURRENT_MANUAL_IMPORT_DATA.episodes;

  const seasonEpisodes = episodes
    .filter(e => e.season_number === seasonNum)
    .sort((a, b) => (a.episode_number || 0) - (b.episode_number || 0));

  if (!seasonEpisodes.length) {
    toast(CURRENT_LANG === "en" ? "No episodes found for this season" : "В этом сезоне нет серий", true);
    return;
  }

  const checkboxes = Array.from(document.querySelectorAll(".manual-import-item-check"));
  const checkedBoxes = checkboxes.filter(cb => cb.checked);
  const targetBoxes = checkedBoxes.length > 0 ? checkedBoxes : checkboxes;

  let currentEpIdx = seasonEpisodes.findIndex(e => e.episode_number >= startEpNum);
  if (currentEpIdx === -1) currentEpIdx = 0;

  let matchedCount = 0;
  targetBoxes.forEach(cb => {
    if (currentEpIdx < seasonEpisodes.length) {
      const targetEp = seasonEpisodes[currentEpIdx];
      const idx = cb.getAttribute("data-idx");
      const epSelect = document.querySelector(`.manual-import-episode-select[data-idx="${idx}"]`);
      const statusEl = document.getElementById(`manual-import-status-${idx}`);

      if (epSelect && targetEp) {
        epSelect.value = targetEp.id;
        cb.checked = true;
        if (statusEl) {
          statusEl.innerHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">${t("manual_import.ready")}</span>`;
        }
        matchedCount++;
        currentEpIdx++;
      }
    }
  });

  onManualImportItemChange();
  toast(CURRENT_LANG === "en" ? `Assigned ${matchedCount} episodes sequentially` : `Сопоставлено ${matchedCount} серий по порядку`);
}

function applyBulkManualImportMovie() {
  if (!CURRENT_MANUAL_IMPORT_DATA || !CURRENT_MANUAL_IMPORT_DATA.episodes) return;
  const ep = CURRENT_MANUAL_IMPORT_DATA.episodes[0];
  if (!ep) return;

  const checkboxes = Array.from(document.querySelectorAll(".manual-import-item-check"));
  const checkedBoxes = checkboxes.filter(cb => cb.checked);
  const targetBoxes = checkedBoxes.length > 0 ? checkedBoxes : checkboxes;

  targetBoxes.forEach(cb => {
    const idx = cb.getAttribute("data-idx");
    const epSelect = document.querySelector(`.manual-import-episode-select[data-idx="${idx}"]`);
    const statusEl = document.getElementById(`manual-import-status-${idx}`);
    if (epSelect) {
      epSelect.value = ep.id;
      cb.checked = true;
      if (statusEl) {
        statusEl.innerHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">${t("manual_import.ready")}</span>`;
      }
    }
  });

  onManualImportItemChange();
  toast(CURRENT_LANG === "en" ? "Movie assigned to selected files" : "Фильм сопоставлен для выбранных файлов");
}

function onManualImportSelectAll(checked) {
  const checkboxes = document.querySelectorAll(".manual-import-item-check");
  checkboxes.forEach(cb => {
    cb.checked = checked;
  });
  onManualImportItemChange();
}

function onManualImportEpisodeSelectChange(idx) {
  const select = document.querySelector(`.manual-import-episode-select[data-idx="${idx}"]`);
  const checkbox = document.querySelector(`.manual-import-item-check[data-idx="${idx}"]`);
  const statusEl = document.getElementById(`manual-import-status-${idx}`);
  const epId = select ? select.value : "";

  if (epId) {
    if (checkbox) checkbox.checked = true;
    if (statusEl) {
      statusEl.innerHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">${t("manual_import.ready")}</span>`;
    }
  } else {
    if (checkbox) checkbox.checked = false;
    if (statusEl) {
      statusEl.innerHTML = `<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444;">${t("manual_import.not_matched")}</span>`;
    }
  }
  onManualImportItemChange();
}

function onManualImportItemChange() {
  const checkboxes = document.querySelectorAll(".manual-import-item-check");
  let selectedCount = 0;
  let validSelectedCount = 0;
  const usedEpIds = new Set();
  const duplicateEpIds = new Set();

  checkboxes.forEach(cb => {
    if (cb.checked) {
      selectedCount++;
      const idx = cb.getAttribute("data-idx");
      const epSelect = document.querySelector(`.manual-import-episode-select[data-idx="${idx}"]`);
      if (epSelect && epSelect.value) {
        const val = epSelect.value;
        if (usedEpIds.has(val)) {
          duplicateEpIds.add(val);
        }
        usedEpIds.add(val);
        validSelectedCount++;
      }
    }
  });

  // Подсветка дублирующихся выбранных серий
  checkboxes.forEach(cb => {
    const idx = cb.getAttribute("data-idx");
    const epSelect = document.querySelector(`.manual-import-episode-select[data-idx="${idx}"]`);
    if (epSelect) {
      if (cb.checked && epSelect.value && duplicateEpIds.has(epSelect.value)) {
        epSelect.style.borderColor = "var(--danger, #ef4444)";
        epSelect.style.backgroundColor = "rgba(239, 68, 68, 0.1)";
      } else {
        epSelect.style.borderColor = "";
        epSelect.style.backgroundColor = "";
      }
    }
  });

  let warnEl = document.getElementById("manual-import-duplicate-warn");
  if (duplicateEpIds.size > 0) {
    if (!warnEl) {
      const tableWrap = document.querySelector(".manual-import-table-wrap");
      if (tableWrap) {
        warnEl = document.createElement("div");
        warnEl.id = "manual-import-duplicate-warn";
        warnEl.className = "alert alert-warning";
        warnEl.style.cssText = "margin: 8px 0; font-size: 12px; display: flex; align-items: center; gap: 6px; padding: 8px 12px; background: rgba(245, 158, 11, 0.15); border: 1px solid #f59e0b; border-radius: 6px; color: #f59e0b;";
        tableWrap.parentNode.insertBefore(warnEl, tableWrap.nextSibling);
      }
    }
    if (warnEl) {
      warnEl.innerHTML = `<i data-lucide="alert-triangle" class="ico-xs"></i> <span>${t("manual_import.warn_duplicate")}</span>`;
      if (window.lucide) lucide.createIcons();
    }
  } else if (warnEl) {
    warnEl.remove();
  }

  const total = checkboxes.length;
  const summaryEl = document.getElementById("manual-import-summary-text");
  if (summaryEl) {
    summaryEl.textContent = t("manual_import.summary").replace("{total}", total).replace("{selected}", selectedCount);
  }

  const submitBtn = document.getElementById("manual-import-submit-btn");
  if (submitBtn) {
    submitBtn.disabled = (validSelectedCount === 0);
    const span = submitBtn.querySelector("span");
    if (span) {
      span.textContent = `${t("manual_import.btn_import")} (${validSelectedCount})`;
    }
  }

  const selectAll = document.getElementById("manual-import-select-all");
  if (selectAll) {
    selectAll.checked = (total > 0 && selectedCount === total);
    selectAll.indeterminate = (selectedCount > 0 && selectedCount < total);
  }
}

async function executeManualImport(showId) {
  const submitBtn = document.getElementById("manual-import-submit-btn");
  const modeSelect = document.getElementById("manual-import-mode-select");
  const importMode = modeSelect ? modeSelect.value : "move";

  const rows = document.querySelectorAll(".manual-import-item-check:checked");
  const items = [];

  rows.forEach(cb => {
    const idx = cb.getAttribute("data-idx");
    const row = document.getElementById(`manual-import-row-${idx}`);
    const epSelect = document.querySelector(`.manual-import-episode-select[data-idx="${idx}"]`);
    const qSelect = document.querySelector(`.manual-import-quality-select[data-idx="${idx}"]`);

    const filePath = row?.getAttribute("data-filepath");
    const episodeId = epSelect ? parseInt(epSelect.value, 10) : null;
    const quality = qSelect ? qSelect.value : null;

    if (filePath && episodeId) {
      items.push({
        file_path: filePath,
        episode_id: episodeId,
        quality: quality,
      });
    }
  });

  if (!items.length) {
    toast(t("manual_import.not_matched"), true);
    return;
  }

  // Закрываем окно импорта
  closeModal("manual-import-modal");

  toast(
    CURRENT_LANG === "en"
      ? `Starting import of ${items.length} file(s)...`
      : `Запущен импорт ${items.length} файл(ов)...`,
    false
  );

  // Сразу опрашиваем задачи, чтобы в виджете "Фоновые операции" появилась активная задача
  loadTasksStatus(true);
  restartTasksPolling(1500);

  // Выполняем импорт в фоне
  (async () => {
    try {
      const res = await api(`/api/v1/shows/${showId}/manual-import/execute`, {
        method: "POST",
        body: JSON.stringify({
          import_mode: importMode,
          items: items,
        }),
      });

      toast(res.message || t("manual_import.success"), false);
      loadTasksStatus(true);
      await refreshShowModal();
      if (typeof loadShows === "function") {
        await loadShows();
      }
    } catch (e) {
      toast("Ошибка: " + e.message, true);
      loadTasksStatus(true);
    }
  })();
}

// ---------------------------------------------------------------------------
// ГЛОБАЛЬНЫЙ РУЧНОЙ ИМПОРТ
// ---------------------------------------------------------------------------

let CURRENT_GLOBAL_MANUAL_IMPORT_DATA = null;

async function openGlobalManualImportModal(customFolder = null) {
  CURRENT_MANUAL_IMPORT_SHOW_ID = null;
  openModal("manual-import-modal");
  const content = document.getElementById("manual-import-modal-content");
  content.innerHTML = `<div style="padding: 30px; text-align: center;"><p>${t("common.loading")}</p></div>`;

  try {
    const initialFolder = (customFolder || "").trim();
    await scanGlobalManualImportFolder(initialFolder);
  } catch (e) {
    content.innerHTML = `<p style="color:var(--danger); padding:20px;">${CURRENT_LANG === "en" ? "Error:" : "Ошибка:"} ${escapeHtml(formatToastMessage(e.message))}</p>`;
  }
}

async function scanGlobalManualImportFolder(folderPath = null) {
  const content = document.getElementById("manual-import-modal-content");
  const pathInputVal = document.getElementById("manual-import-path-input")?.value;
  const targetPath = (folderPath !== null ? folderPath : (pathInputVal || "")).trim();

  content.innerHTML = `
    <div class="manual-import-header">
      <div style="font-size: 16px; font-weight: 600; color: var(--text);">
        <i data-lucide="hard-drive-download" class="ico-sm" style="vertical-align: middle; margin-right: 6px;"></i>
        ${t("manual_import.title")}
      </div>
      <div class="manual-import-mode-row">
        <label style="font-size: 13px; color: var(--text-muted);">${t("manual_import.mode_label")}</label>
        <select id="manual-import-mode-select" class="input input-small" style="width: auto;">
          <option value="move">${t("manual_import.mode_move")}</option>
          <option value="copy">${t("manual_import.mode_copy")}</option>
        </select>
      </div>
    </div>

    <div class="manual-import-path-row" style="margin-bottom: 14px;">
      <input id="manual-import-path-input" class="input" type="text" value="${escapeHtml(targetPath)}" placeholder="${t("manual_import.folder_placeholder")}" onkeydown="if(event.key==='Enter') scanGlobalManualImportFolder()">
      <button class="btn btn-secondary" onclick="openFolderPicker('manual-import-path-input')" title="${t("common.browse")}"><i data-lucide="folder" class="ico-sm"></i> ${t("common.browse")}</button>
      <button class="btn btn-primary" onclick="scanGlobalManualImportFolder()"><i data-lucide="search" class="ico-sm"></i> ${t("manual_import.scan")}</button>
    </div>

    <div style="padding: 40px; text-align: center;">
      <p class="hint">${t("common.loading")}</p>
    </div>
  `;

  if (window.lucide) lucide.createIcons();

  try {
    const payload = targetPath ? { folder_path: targetPath } : {};
    const data = await api("/api/v1/shows/manual-import/scan-all", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    CURRENT_GLOBAL_MANUAL_IMPORT_DATA = data;
    renderGlobalManualImportView(data);
  } catch (e) {
    content.innerHTML = `
      <div class="manual-import-header">
        <div style="font-size: 16px; font-weight: 600; color: var(--text);">
          <i data-lucide="hard-drive-download" class="ico-sm" style="vertical-align: middle; margin-right: 6px;"></i>
          ${t("manual_import.title")}
        </div>
      </div>
      <div class="manual-import-path-row" style="margin-bottom: 14px;">
        <input id="manual-import-path-input" class="input" type="text" value="${escapeHtml(targetPath)}" placeholder="${t("manual_import.folder_placeholder")}">
        <button class="btn btn-secondary" onclick="openFolderPicker('manual-import-path-input')"><i data-lucide="folder" class="ico-sm"></i> ${t("common.browse")}</button>
        <button class="btn btn-primary" onclick="scanGlobalManualImportFolder()"><i data-lucide="search" class="ico-sm"></i> ${t("manual_import.scan")}</button>
      </div>
      <div style="padding: 20px; background: rgba(239, 68, 68, 0.1); border: 1px solid var(--danger); border-radius: 6px; color: var(--danger);">
        ${escapeHtml(formatToastMessage(e.message))}
      </div>
    `;
    if (window.lucide) lucide.createIcons();
  }
}

function renderGlobalManualImportView(data) {
  const content = document.getElementById("manual-import-modal-content");
  const files = data.files || [];
  const shows = data.shows || [];
  const episodesByShow = data.episodes_by_show || {};
  const currentMode = document.getElementById("manual-import-mode-select")?.value || "move";

  const qualityOptions = QUALITY_OPTIONS;

  let rowsHtml = "";
  if (!files.length) {
    rowsHtml = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 30px;">${t("manual_import.no_files")}</td></tr>`;
  } else {
    rowsHtml = files.map((file, idx) => {
      const isMatched = file.matched_show_id != null && file.matched_episode_id != null;
      const sizeStr = file.size_bytes ? formatBytes(file.size_bytes) : "";

      // Dropdown с тайтлами
      const showOptions = [
        `<option value="">${t("manual_import.select_show")}</option>`,
        ...shows.map(s => {
          const sel = s.id === file.matched_show_id ? "selected" : "";
          return `<option value="${s.id}" ${sel}>${escapeHtml(s.title)}${s.year ? ` (${s.year})` : ""}</option>`;
        })
      ].join("");

      // Dropdown с сериями или фильмом
      const currentShowEps = file.matched_show_id ? (episodesByShow[file.matched_show_id] || []) : [];
      const showMeta = shows.find(s => s.id === file.matched_show_id);
      const isMovie = Boolean(showMeta && showMeta.content_type === "movie");
      const isAnime = Boolean(showMeta && showMeta.content_type === "anime");

      const epOptions = [
        `<option value="">${t("manual_import.skip")}</option>`,
        ...currentShowEps.map(ep => {
          let label = "";
          if (isMovie) {
            label = `${escapeHtml(showMeta?.title || ep.title || (CURRENT_LANG === 'en' ? 'Movie' : 'Фильм'))}${showMeta?.year ? ` (${showMeta.year})` : ""}`;
          } else if (ep.season_number === 0) {
            label = `${CURRENT_LANG === 'en' ? 'Special' : 'Спецвыпуск'} ${ep.episode_number}: ${escapeHtml(ep.title || "—")}`;
          } else if (isAnime && ep.absolute_number != null) {
            label = `${CURRENT_LANG === 'en' ? 'Ep.' : 'Серия'} ${ep.absolute_number}: ${escapeHtml(ep.title || "—")} (S${pad(ep.season_number)}E${pad(ep.episode_number)})`;
          } else {
            label = `S${pad(ep.season_number)}E${pad(ep.episode_number)}: ${escapeHtml(ep.title || "—")}`;
          }
          const sel = ep.id === file.matched_episode_id ? "selected" : "";
          return `<option value="${ep.id}" ${sel}>${label}</option>`;
        })
      ].join("");

      // Dropdown с качеством
      const qOptions = qualityOptions.map(q => {
        const sel = (file.detected_quality && file.detected_quality.toLowerCase() === q.toLowerCase()) ? "selected" : "";
        return `<option value="${q}" ${sel}>${q}</option>`;
      }).join("");

      let statusBadge = "";
      if (file.existing_file) {
        statusBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b;" title="${escapeHtml(file.existing_file)}">${t("manual_import.overwrite")}</span>`;
      } else if (isMatched) {
        statusBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">${t("manual_import.ready")}</span>`;
      } else {
        statusBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444;">${t("manual_import.not_matched")}</span>`;
      }

      return `
        <tr id="global-manual-import-row-${idx}" data-idx="${idx}" data-filepath="${escapeHtml(file.file_path)}">
          <td style="width: 40px; text-align: center;">
            <input type="checkbox" class="global-manual-import-item-check" data-idx="${idx}" ${isMatched ? "checked" : ""} onchange="onGlobalManualImportItemChange()">
          </td>
          <td class="manual-import-file-cell">
            <div class="manual-import-file-name" title="${escapeHtml(file.file_path)}">${escapeHtml(file.relative_path || file.filename)}</div>
            <div class="manual-import-file-meta">${sizeStr}</div>
          </td>
          <td style="min-width: 180px;">
            <select class="input input-small global-manual-import-show-select" data-idx="${idx}" onchange="onGlobalManualImportShowChange(${idx})">
              ${showOptions}
            </select>
          </td>
          <td style="min-width: 220px;">
            <select class="input input-small global-manual-import-episode-select" data-idx="${idx}" onchange="onGlobalManualImportEpisodeChange(${idx})">
              ${epOptions}
            </select>
          </td>
          <td style="width: 130px;">
            <select class="input input-small global-manual-import-quality-select" data-idx="${idx}">
              ${qOptions}
            </select>
          </td>
          <td style="width: 120px; text-align: right;">
            <div id="global-manual-import-status-${idx}">${statusBadge}</div>
          </td>
        </tr>
      `;
    }).join("");
  }

  content.innerHTML = `
    <div class="manual-import-header">
      <div style="font-size: 16px; font-weight: 600; color: var(--text);">
        <i data-lucide="hard-drive-download" class="ico-sm" style="vertical-align: middle; margin-right: 6px;"></i>
        ${t("manual_import.title")}
      </div>
      <div class="manual-import-mode-row">
        <label style="font-size: 13px; color: var(--text-muted);">${t("manual_import.mode_label")}</label>
        <select id="manual-import-mode-select" class="input input-small" style="width: auto;">
          <option value="move" ${currentMode === "move" ? "selected" : ""}>${t("manual_import.mode_move")}</option>
          <option value="copy" ${currentMode === "copy" ? "selected" : ""}>${t("manual_import.mode_copy")}</option>
        </select>
      </div>
    </div>

    <div class="manual-import-path-row" style="margin-bottom: 12px;">
      <input id="manual-import-path-input" class="input" type="text" value="${escapeHtml(data.folder_path || "")}" placeholder="${t("manual_import.folder_placeholder")}" onkeydown="if(event.key==='Enter') scanGlobalManualImportFolder()">
      <button class="btn btn-secondary" onclick="openFolderPicker('manual-import-path-input')"><i data-lucide="folder" class="ico-sm"></i> ${t("common.browse")}</button>
      <button class="btn btn-primary" onclick="scanGlobalManualImportFolder()"><i data-lucide="search" class="ico-sm"></i> ${t("manual_import.scan")}</button>
    </div>

    <div class="manual-import-summary-bar">
      <div id="global-manual-import-summary-text">
        ${t("manual_import.summary").replace("{total}", files.length).replace("{selected}", files.filter(f => f.matched_show_id != null && f.matched_episode_id != null).length)}
      </div>
    </div>

    ${files.length ? `
    <div class="manual-import-bulk-toolbar">
      <div class="bulk-group">
        <span class="bulk-label"><i data-lucide="sliders" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Quality:' : 'Качество:'}</span></span>
        <select id="global-bulk-quality-select" class="input input-small" style="width: 140px;">
          <option value="">— ${CURRENT_LANG === 'en' ? 'Quality' : 'Качество'} —</option>
          ${qualityOptions.map(q => `<option value="${q}">${q}</option>`).join("")}
        </select>
        <button type="button" class="btn btn-secondary btn-small" onclick="applyGlobalBulkQuality()">
          <i data-lucide="check" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Apply to selected' : 'Применить к выбранным'}</span>
        </button>
      </div>
      <div class="bulk-group">
        <span class="bulk-label"><i data-lucide="tv" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Show:' : 'Тайтл:'}</span></span>
        <select id="global-bulk-show-select" class="input input-small" style="max-width: 220px;">
          <option value="">— ${CURRENT_LANG === 'en' ? 'Select show' : 'Выберите тайтл'} —</option>
          ${shows.map(s => `<option value="${s.id}">${escapeHtml(s.title)}${s.year ? ` (${s.year})` : ""}</option>`).join("")}
        </select>
        <button type="button" class="btn btn-secondary btn-small" onclick="applyGlobalBulkShow()">
          <i data-lucide="check" class="ico-xs"></i> <span>${CURRENT_LANG === 'en' ? 'Assign to selected' : 'Назначить для выбранных'}</span>
        </button>
      </div>
    </div>` : ""}

    <div class="manual-import-table-wrap">
      <table class="manual-import-table">
        <thead>
          <tr>
            <th style="width: 40px; text-align: center;">
              <input type="checkbox" id="global-manual-import-select-all" ${files.some(f => f.matched_show_id != null && f.matched_episode_id != null) ? "checked" : ""} onchange="onGlobalManualImportSelectAll(this.checked)">
            </th>
            <th>${t("manual_import.col_file")}</th>
            <th>${t("manual_import.col_show")}</th>
            <th>${t("manual_import.col_episode")}</th>
            <th>${t("manual_import.col_quality")}</th>
            <th style="text-align: right;">${t("manual_import.col_status")}</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    </div>

    <div class="manual-import-footer">
      <button class="btn btn-secondary" onclick="closeModal('manual-import-modal')">${t("common.cancel")}</button>
      <button id="global-manual-import-submit-btn" class="btn btn-primary" onclick="executeGlobalManualImport()" ${!files.length ? "disabled" : ""}>
        <i data-lucide="download" class="ico-sm"></i> <span>${t("manual_import.btn_import")}</span>
      </button>
    </div>
  `;

  if (window.lucide) lucide.createIcons();
  onGlobalManualImportItemChange();
}

function onGlobalManualImportShowChange(idx) {
  const showSelect = document.querySelector(`.global-manual-import-show-select[data-idx="${idx}"]`);
  const epSelect = document.querySelector(`.global-manual-import-episode-select[data-idx="${idx}"]`);
  const showId = showSelect ? parseInt(showSelect.value, 10) : null;
  if (!epSelect) return;

  const data = CURRENT_GLOBAL_MANUAL_IMPORT_DATA;
  if (!data) return;

  const shows = data.shows || [];
  const episodesByShow = data.episodes_by_show || {};
  const showEps = showId ? (episodesByShow[showId] || []) : [];
  const showMeta = shows.find(s => s.id === showId);
  const isMovie = Boolean(showMeta && showMeta.content_type === "movie");
  const isAnime = Boolean(showMeta && showMeta.content_type === "anime");

  const epOptions = [
    `<option value="">${t("manual_import.skip")}</option>`,
    ...showEps.map(ep => {
      let label = "";
      if (isMovie) {
        label = `${escapeHtml(showMeta?.title || ep.title || (CURRENT_LANG === 'en' ? 'Movie' : 'Фильм'))}${showMeta?.year ? ` (${showMeta.year})` : ""}`;
      } else if (ep.season_number === 0) {
        label = `${CURRENT_LANG === 'en' ? 'Special' : 'Спецвыпуск'} ${ep.episode_number}: ${escapeHtml(ep.title || "—")}`;
      } else if (isAnime && ep.absolute_number != null) {
        label = `${CURRENT_LANG === 'en' ? 'Ep.' : 'Серия'} ${ep.absolute_number}: ${escapeHtml(ep.title || "—")} (S${pad(ep.season_number)}E${pad(ep.episode_number)})`;
      } else {
        label = `S${pad(ep.season_number)}E${pad(ep.episode_number)}: ${escapeHtml(ep.title || "—")}`;
      }
      return `<option value="${ep.id}">${label}</option>`;
    })
  ].join("");

  epSelect.innerHTML = epOptions;
  onGlobalManualImportEpisodeChange(idx);
}

function onGlobalManualImportEpisodeChange(idx) {
  const showSelect = document.querySelector(`.global-manual-import-show-select[data-idx="${idx}"]`);
  const epSelect = document.querySelector(`.global-manual-import-episode-select[data-idx="${idx}"]`);
  const checkbox = document.querySelector(`.global-manual-import-item-check[data-idx="${idx}"]`);
  const statusEl = document.getElementById(`global-manual-import-status-${idx}`);

  const showId = showSelect ? showSelect.value : "";
  const epId = epSelect ? epSelect.value : "";

  if (showId && epId) {
    if (checkbox) checkbox.checked = true;
    if (statusEl) {
      statusEl.innerHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">${t("manual_import.ready")}</span>`;
    }
  } else {
    if (checkbox) checkbox.checked = false;
    if (statusEl) {
      statusEl.innerHTML = `<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444;">${t("manual_import.not_matched")}</span>`;
    }
  }
  onGlobalManualImportItemChange();
}

function onGlobalManualImportItemChange() {
  const checkboxes = document.querySelectorAll(".global-manual-import-item-check");
  let selectedCount = 0;
  let validSelectedCount = 0;

  checkboxes.forEach(cb => {
    if (cb.checked) {
      selectedCount++;
      const idx = cb.getAttribute("data-idx");
      const showSelect = document.querySelector(`.global-manual-import-show-select[data-idx="${idx}"]`);
      const epSelect = document.querySelector(`.global-manual-import-episode-select[data-idx="${idx}"]`);
      if (showSelect && showSelect.value && epSelect && epSelect.value) {
        validSelectedCount++;
      }
    }
  });

  const total = checkboxes.length;
  const summaryEl = document.getElementById("global-manual-import-summary-text");
  if (summaryEl) {
    summaryEl.textContent = t("manual_import.summary").replace("{total}", total).replace("{selected}", selectedCount);
  }

  const submitBtn = document.getElementById("global-manual-import-submit-btn");
  if (submitBtn) {
    submitBtn.disabled = (validSelectedCount === 0);
    const span = submitBtn.querySelector("span");
    if (span) {
      span.textContent = `${t("manual_import.btn_import")} (${validSelectedCount})`;
    }
  }

  const selectAll = document.getElementById("global-manual-import-select-all");
  if (selectAll) {
    selectAll.checked = (total > 0 && selectedCount === total);
    selectAll.indeterminate = (selectedCount > 0 && selectedCount < total);
  }
}

function onGlobalManualImportSelectAll(checked) {
  const checkboxes = document.querySelectorAll(".global-manual-import-item-check");
  checkboxes.forEach(cb => {
    cb.checked = checked;
  });
  onGlobalManualImportItemChange();
}

function applyGlobalBulkQuality() {
  const bulkSelect = document.getElementById("global-bulk-quality-select");
  if (!bulkSelect || !bulkSelect.value) {
    toast(CURRENT_LANG === "en" ? "Select a quality first" : "Сначала выберите качество в списке", true);
    return;
  }
  const quality = bulkSelect.value;
  const checkboxes = Array.from(document.querySelectorAll(".global-manual-import-item-check"));
  const checkedBoxes = checkboxes.filter(cb => cb.checked);
  const targetBoxes = checkedBoxes.length > 0 ? checkedBoxes : checkboxes;

  targetBoxes.forEach(cb => {
    const idx = cb.getAttribute("data-idx");
    const qSelect = document.querySelector(`.global-manual-import-quality-select[data-idx="${idx}"]`);
    if (qSelect) qSelect.value = quality;
  });
  toast(CURRENT_LANG === "en" ? `Quality set to ${quality} for ${targetBoxes.length} files` : `Качество «${quality}» задано для ${targetBoxes.length} файлов`);
}

function applyGlobalBulkShow() {
  const bulkSelect = document.getElementById("global-bulk-show-select");
  if (!bulkSelect || !bulkSelect.value) {
    toast(CURRENT_LANG === "en" ? "Select a show first" : "Сначала выберите тайтл в списке", true);
    return;
  }
  const showId = parseInt(bulkSelect.value, 10);
  const checkboxes = Array.from(document.querySelectorAll(".global-manual-import-item-check"));
  const checkedBoxes = checkboxes.filter(cb => cb.checked);
  const targetBoxes = checkedBoxes.length > 0 ? checkedBoxes : checkboxes;

  targetBoxes.forEach(cb => {
    const idx = cb.getAttribute("data-idx");
    const showSelect = document.querySelector(`.global-manual-import-show-select[data-idx="${idx}"]`);
    if (showSelect) {
      showSelect.value = showId;
      onGlobalManualImportShowChange(idx);
    }
  });
  toast(CURRENT_LANG === "en" ? `Show assigned to ${targetBoxes.length} files` : `Тайтл назначен для ${targetBoxes.length} файлов`);
}

async function executeGlobalManualImport() {
  const submitBtn = document.getElementById("global-manual-import-submit-btn");
  const modeSelect = document.getElementById("manual-import-mode-select");
  const importMode = modeSelect ? modeSelect.value : "move";

  const rows = document.querySelectorAll(".global-manual-import-item-check:checked");
  const items = [];

  rows.forEach(cb => {
    const idx = cb.getAttribute("data-idx");
    const row = document.getElementById(`global-manual-import-row-${idx}`);
    const showSelect = document.querySelector(`.global-manual-import-show-select[data-idx="${idx}"]`);
    const epSelect = document.querySelector(`.global-manual-import-episode-select[data-idx="${idx}"]`);
    const qSelect = document.querySelector(`.global-manual-import-quality-select[data-idx="${idx}"]`);

    const filePath = row?.getAttribute("data-filepath");
    const showId = showSelect ? parseInt(showSelect.value, 10) : null;
    const episodeId = epSelect ? parseInt(epSelect.value, 10) : null;
    const quality = qSelect ? qSelect.value : null;

    if (filePath && showId && episodeId) {
      items.push({
        file_path: filePath,
        show_id: showId,
        episode_id: episodeId,
        quality: quality,
      });
    }
  });

  if (!items.length) {
    toast(t("manual_import.not_matched"), true);
    return;
  }

  // Закрываем окно импорта
  closeModal("manual-import-modal");

  toast(
    CURRENT_LANG === "en"
      ? `Starting import of ${items.length} file(s)...`
      : `Запущен импорт ${items.length} файл(ов)...`,
    false
  );

  // Сразу опрашиваем задачи, чтобы в виджете "Фоновые операции" появилась активная задача
  loadTasksStatus(true);
  restartTasksPolling(1500);

  // Выполняем импорт в фоне
  (async () => {
    try {
      const res = await api("/api/v1/shows/manual-import/execute-all", {
        method: "POST",
        body: JSON.stringify({
          import_mode: importMode,
          items: items,
        }),
      });

      toast(res.message || t("manual_import.success"), false);
      loadTasksStatus(true);
      if (typeof loadShows === "function") {
        await loadShows();
      }
    } catch (e) {
      toast("Ошибка: " + e.message, true);
      loadTasksStatus(true);
    }
  })();
}

async function forceSearchShow(button, showId) {
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/shows/${showId}/search`, { method: "POST" });
      const count = (result.grabbed || []).length;
      toast(count ? `${t("dash.wanted")}: ${count}` : (result.status || t("common.none")));
      await refreshShowModal();
      loadShows();
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

// =============================================================================
// ИНТЕРАКТИВНЫЙ ПОИСК РЕЛИЗОВ
// =============================================================================

let INTERACTIVE_SEARCH_STATE = {
  showId: null,
  show: null,
  season: null,
  episode: null,
  customQuery: "",
  results: [],
  indexerFilter: "all",
  statusFilter: "all",
  page: 1,
  pageSize: 30,
};

async function searchReleasesForShow(button, showId) {
  openInteractiveSearch(showId);
}

async function openInteractiveSearch(showId, seasonNumber = null, episodeNumber = null, customQuery = null) {
  const show = CACHED_SHOWS.find(s => s.id === showId);
  const initialQuery = customQuery || (show ? show.title : "");

  INTERACTIVE_SEARCH_STATE = {
    showId: showId,
    show: show,
    season: seasonNumber,
    episode: episodeNumber,
    customQuery: initialQuery,
    results: [],
    indexerFilter: "all",
    statusFilter: "all",
    page: 1,
    pageSize: 30,
  };

  renderInteractiveSearchHeader();
  openModal("interactive-search-modal");
  await executeInteractiveSearch();
}

function formatEpisodeRange(episodes) {
  if (!episodes || !episodes.length) return "";
  if (episodes.length === 1) return `E${String(episodes[0]).padStart(2, "0")}`;
  
  const sorted = [...episodes].map(Number).filter(n => !isNaN(n)).sort((a, b) => a - b);
  if (!sorted.length) return "";

  const ranges = [];
  let start = sorted[0];
  let prev = sorted[0];

  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === prev + 1) {
      prev = sorted[i];
    } else {
      if (start === prev) {
        ranges.push(`E${String(start).padStart(2, "0")}`);
      } else {
        ranges.push(`E${String(start).padStart(2, "0")}-E${String(prev).padStart(2, "0")}`);
      }
      start = sorted[i];
      prev = sorted[i];
    }
  }
  if (start === prev) {
    ranges.push(`E${String(start).padStart(2, "0")}`);
  } else {
    ranges.push(`E${String(start).padStart(2, "0")}-E${String(prev).padStart(2, "0")}`);
  }

  const rangeStr = ranges.join(", ");
  return `${rangeStr} (${sorted.length} эп.)`;
}

function formatReleaseAge(ageDays, pubDateStr) {
  let display = "—";
  if (ageDays != null && !isNaN(ageDays)) {
    const days = Number(ageDays);
    if (days < 0.04) {
      display = `${Math.max(1, Math.round(days * 1440))}m`;
    } else if (days < 1.0) {
      display = `${Math.round(days * 24)}h`;
    } else if (days < 365) {
      display = `${Math.round(days)}d`;
    } else {
      display = `${(days / 365.25).toFixed(1)}y`;
    }
  }
  const titleAttr = pubDateStr ? `title="${escapeHtml(pubDateStr)}"` : "";
  return `<span ${titleAttr}>${display}</span>`;
}

function renderInteractiveSearchHeader() {
  const headerEl = document.getElementById("interactive-search-header");
  const state = INTERACTIVE_SEARCH_STATE;
  const show = state.show;
  const showTitle = show ? show.title : "Поиск релизов";

  let epBadge = "";
  if (show && show.content_type === "movie") {
    epBadge = `<span class="badge badge-primary">${t("settings.cat_movies")}</span>`;
  } else if (state.season !== null && state.episode !== null) {
    epBadge = `<span class="badge badge-primary">S${String(state.season).padStart(2, "0")}E${String(state.episode).padStart(2, "0")}</span>`;
  } else if (state.season !== null) {
    epBadge = `<span class="badge badge-secondary">${t("show.season")} ${state.season}</span>`;
  }

  headerEl.innerHTML = `
    <div class="interactive-search-title-row">
      <div style="display:flex; align-items:center; gap:8px;">
        <h3 style="margin:0; font-size:17px; font-weight:600;"><span style="color:var(--primary); font-weight:700;">Поиск:</span> ${escapeHtml(showTitle)} ${epBadge}</h3>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        <span class="hint" id="interactive-results-count"></span>
      </div>
    </div>

    <!-- Поисковая строка для ручного ввода произвольного запроса -->
    <div class="interactive-search-query-bar">
      <div class="search-input-wrap">
        <i data-lucide="search"></i>
        <input id="interactive-query-input" class="input" type="text" value="${escapeHtml(state.customQuery)}"
          placeholder="Введите название фильма, сериала или аниме для расширенного поиска..."
          onkeydown="if(event.key==='Enter') triggerInteractiveCustomSearch()">
      </div>
      <button class="btn btn-primary" id="interactive-search-btn" onclick="triggerInteractiveCustomSearch()">
        <i data-lucide="search" class="ico-sm"></i> <span>${t("common.search")}</span>
      </button>
      <button class="btn btn-secondary" onclick="resetInteractiveSearchQuery()" title="Сбросить на оригинал">
        <i data-lucide="rotate-ccw" class="ico-sm"></i>
      </button>
    </div>

    <!-- Фильтры результатов -->
    <div class="interactive-search-filter-row">
      <span>Фильтр:</span>
      <select id="interactive-indexer-filter" class="input input-small" style="max-width:180px;" onchange="onInteractiveFilterChange()">
        <option value="all">Все индексаторы</option>
      </select>
      <select id="interactive-status-filter" class="input input-small" style="max-width:180px;" onchange="onInteractiveFilterChange()">
        <option value="all">Все релизы</option>
        <option value="approved">Только одобренные</option>
        <option value="rejected">Отклонённые</option>
      </select>
    </div>
  `;
  if (window.lucide) lucide.createIcons();
}

async function triggerInteractiveCustomSearch() {
  const input = document.getElementById("interactive-query-input");
  if (!input) return;
  const q = input.value.trim();
  INTERACTIVE_SEARCH_STATE.customQuery = q;
  await executeInteractiveSearch();
}

function resetInteractiveSearchQuery() {
  const show = INTERACTIVE_SEARCH_STATE.show;
  if (!show) return;
  const input = document.getElementById("interactive-query-input");
  if (input) input.value = show.title;
  INTERACTIVE_SEARCH_STATE.customQuery = show.title;
  executeInteractiveSearch();
}

async function executeInteractiveSearch() {
  const bodyEl = document.getElementById("interactive-search-body");
  const countEl = document.getElementById("interactive-results-count");
  const searchBtn = document.getElementById("interactive-search-btn");
  const state = INTERACTIVE_SEARCH_STATE;

  bodyEl.innerHTML = `<div style="text-align:center; padding:40px;"><p style="color:var(--text-muted);"><i data-lucide="loader" class="ico-spin ico-lg"></i></p><p>${t("common.loading")}</p></div>`;
  if (window.lucide) lucide.createIcons();

  try {
    let results = [];
    if (state.customQuery) {
      let url = `/api/v1/indexers/search-custom?query=${encodeURIComponent(state.customQuery)}`;
      if (state.showId) url += `&show_id=${state.showId}`;
      if (state.season !== null) url += `&season=${state.season}`;
      if (state.episode !== null) url += `&episode=${state.episode}`;
      results = await api(url);
    } else if (state.showId) {
      results = await api(`/api/v1/indexers/search/${state.showId}`);
    }

    state.results = results || [];
    state.page = 1;

    // Обновляем список индексаторов в фильтре
    const indexers = Array.from(new Set(state.results.map(r => r.indexer).filter(Boolean)));
    const filterSelect = document.getElementById("interactive-indexer-filter");
    if (filterSelect) {
      filterSelect.innerHTML = `<option value="all">Все индексаторы (${state.results.length})</option>` +
        indexers.map(idx => `<option value="${escapeHtml(idx)}">${escapeHtml(idx)}</option>`).join("");
      filterSelect.value = state.indexerFilter;
    }

    if (countEl) countEl.textContent = `Найдено: ${state.results.length}`;
    renderInteractiveSearchTable();
  } catch (e) {
    if (e.message !== "unauthorized") {
      bodyEl.innerHTML = `<div style="padding:24px; color:var(--danger); text-align:center;"><p>${CURRENT_LANG === "en" ? "Search Error:" : "Ошибка поиска:"} ${escapeHtml(formatToastMessage(e.message))}</p></div>`;
    }
  }
}

function onInteractiveFilterChange() {
  const indexerSelect = document.getElementById("interactive-indexer-filter");
  const statusSelect = document.getElementById("interactive-status-filter");
  if (indexerSelect) INTERACTIVE_SEARCH_STATE.indexerFilter = indexerSelect.value;
  if (statusSelect) INTERACTIVE_SEARCH_STATE.statusFilter = statusSelect.value;
  INTERACTIVE_SEARCH_STATE.page = 1;
  renderInteractiveSearchTable();
}

function renderInteractiveSearchTable() {
  const bodyEl = document.getElementById("interactive-search-body");
  const state = INTERACTIVE_SEARCH_STATE;

  let filtered = state.results;
  if (state.indexerFilter !== "all") {
    filtered = filtered.filter(r => r.indexer === state.indexerFilter);
  }
  if (state.statusFilter === "approved") {
    filtered = filtered.filter(r => r.approved);
  } else if (state.statusFilter === "rejected") {
    filtered = filtered.filter(r => !r.approved);
  }

  if (!filtered.length) {
    bodyEl.innerHTML = `<div style="text-align:center; padding:48px; color:var(--text-muted);"><p style="font-size:15px;">${t("library.no_results")}</p><p class="hint">Попробуйте ввести другое название в поисковой строке выше</p></div>`;
    return;
  }

  const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
  const clampedPage = Math.min(Math.max(1, state.page), totalPages);
  state.page = clampedPage;
  const pageItems = filtered.slice((clampedPage - 1) * state.pageSize, clampedPage * state.pageSize);

  bodyEl.innerHTML = `
    <div class="interactive-search-table-wrap">
      <table class="interactive-search-table">
        <thead>
          <tr>
            <th style="width:30px; text-align:center;"></th>
            <th style="width:60px;">Возраст</th>
            <th>Релиз / Раздача</th>
            <th style="width:110px;">Индексатор</th>
            <th style="width:90px;">Размер</th>
            <th style="width:70px; text-align:center;">Сиды</th>
            <th style="width:140px;">Качество</th>
            <th style="width:130px;">Языки / Группа</th>
            <th style="width:110px; text-align:center;">Форматы / Счёт</th>
            <th style="width:100px; text-align:right;">Действие</th>
          </tr>
        </thead>
        <tbody>
          ${pageItems.map(r => renderInteractiveReleaseRow(r)).join("")}
        </tbody>
      </table>
    </div>
    ${renderInteractivePagination(clampedPage, totalPages)}
  `;
  if (window.lucide) lucide.createIcons();
}

function renderInteractiveReleaseRow(r) {
  const showId = INTERACTIVE_SEARCH_STATE.showId || 0;
  const isApproved = r.approved !== false;
  const rejections = r.rejections || [];

  // Иконка статуса и тултип
  let statusIconHtml = "";
  if (isApproved) {
    statusIconHtml = `
      <div class="rejection-status-wrap">
        <i data-lucide="check-circle" class="rejection-icon-approved"></i>
        <div class="rejection-tooltip">
          <div style="font-weight:600; color:#10b981; margin-bottom:2px;">Релиз одобрен</div>
          <div style="color:#d4d4d8;">Релиз соответствует критериям DecisionEngine и готов к загрузке.</div>
        </div>
      </div>`;
  } else {
    const listHtml = rejections.length
      ? `<ul>${rejections.map(rej => `<li>${escapeHtml(rej)}</li>`).join("")}</ul>`
      : `<div style="color:#d4d4d8; margin-top:4px;">${escapeHtml(r.status || "Релиз не соответствует критериям профиля")}</div>`;
    statusIconHtml = `
      <div class="rejection-status-wrap">
        <i data-lucide="alert-triangle" class="rejection-icon-warning"></i>
        <div class="rejection-tooltip">
          <div style="font-weight:600; color:#facc15; margin-bottom:2px;">Релиз отклонён:</div>
          ${listHtml}
        </div>
      </div>`;
  }

  // Возраст релиза
  const ageHtml = formatReleaseAge(r.age_days, r.publish_date);

  // Качество
  const qualityBadge = `<span class="badge-quality">${escapeHtml(r.quality || "SDTV")}</span>`;

  // Языки
  const langBadges = (r.languages || []).map(l => `<span class="badge-lang">${escapeHtml(l)}</span>`).join(" ");

  // Группа
  const groupBadge = r.release_group ? `<span class="badge-group">${escapeHtml(r.release_group)}</span>` : "";

  // Кастомные форматы
  const scoreVal = r.custom_format_score || 0;
  const scoreClass = scoreVal > 0 ? "positive" : (scoreVal < 0 ? "negative" : "");
  const scoreBadge = `<span class="badge-cf-score ${scoreClass}"><i data-lucide="sparkles" class="ico-xs"></i> ${scoreVal}</span>`;
  const cfList = (r.custom_formats || []).map(cf => `<span class="badge-cf-item" title="+${cf.score}">${escapeHtml(cf.name)}</span>`).join(" ");

  const isMovie = INTERACTIVE_SEARCH_STATE.show?.content_type === "movie" || r.parsed_kind === "movie";

  // Серии релиза в компактном виде — только для сериалов и аниме
  const seasonBadge = (!isMovie && r.parsed_season != null)
    ? `<span class="badge badge-outline">S${String(r.parsed_season).padStart(2, "0")}</span>`
    : "";
  const episodesBadge = (!isMovie && r.parsed_episodes && r.parsed_episodes.length)
    ? `<span class="badge badge-outline" title="Серии: ${r.parsed_episodes.join(', ')}">${escapeHtml(formatEpisodeRange(r.parsed_episodes))}</span>`
    : "";

  // Кнопка захвата
  const grabBtnText = isApproved ? "Захватить" : "Force Grab";
  const grabBtnClass = isApproved ? "btn-primary" : "btn-secondary";

  return `
    <tr class="${isApproved ? "approved-row" : "rejected-row"}">
      <td style="text-align:center;">${statusIconHtml}</td>
      <td class="mono" style="font-size:12px; color:var(--text-muted);">${ageHtml}</td>
      <td class="release-title-cell">
        ${r.page_url
          ? `<a href="${escapeHtml(r.page_url)}" target="_blank" rel="noopener" class="release-title-link">${escapeHtml(r.title)}</a>`
          : `<span class="release-title-link">${escapeHtml(r.title)}</span>`}
        <div class="release-meta-chips">
          ${seasonBadge}
          ${episodesBadge}
          ${r.matched_alias ? `<span class="hint" style="font-size:11px;">(Матч: ${escapeHtml(r.matched_alias)})</span>` : ""}
        </div>
      </td>
      <td><span class="badge badge-secondary">${escapeHtml(r.indexer)}</span></td>
      <td class="mono" style="font-size:12px;">${formatSize(r.size_bytes)}</td>
      <td class="mono" style="text-align:center; font-weight:600; color:${r.seeders > 5 ? "var(--accent)" : "inherit"};">${r.seeders}</td>
      <td>${qualityBadge}</td>
      <td>${langBadges} ${groupBadge}</td>
      <td style="text-align:center;">${scoreBadge} ${cfList ? `<div style="margin-top:2px;">${cfList}</div>` : ""}</td>
      <td style="text-align:right;">
        <button class="btn ${grabBtnClass} btn-small" onclick='grabRelease(this, ${showId}, ${JSON.stringify(r).replace(/'/g, "&apos;")})'>${grabBtnText}</button>
      </td>
    </tr>
  `;
}

function renderInteractivePagination(page, totalPages) {
  if (totalPages <= 1) return "";
  return `
    <div class="pagination-row" style="margin-top:12px; padding:8px 0; display:flex; justify-content:center; gap:6px;">
      <button class="btn btn-secondary btn-small" ${page <= 1 ? "disabled" : ""} onclick="goInteractiveSearchPage(1)">« 1</button>
      <button class="btn btn-secondary btn-small" ${page <= 1 ? "disabled" : ""} onclick="goInteractiveSearchPage(${page - 1})"><i data-lucide="chevron-left" class="ico-xs"></i></button>
      <span style="font-size:13px; padding:4px 10px; color:var(--text-muted);">Стр. ${page} из ${totalPages}</span>
      <button class="btn btn-secondary btn-small" ${page >= totalPages ? "disabled" : ""} onclick="goInteractiveSearchPage(${page + 1})"><i data-lucide="chevron-right" class="ico-xs"></i></button>
      <button class="btn btn-secondary btn-small" ${page >= totalPages ? "disabled" : ""} onclick="goInteractiveSearchPage(${totalPages})">${totalPages} »</button>
    </div>`;
}

function goInteractiveSearchPage(page) {
  INTERACTIVE_SEARCH_STATE.page = page;
  renderInteractiveSearchTable();
}

async function grabRelease(button, showId, result) {
  await withLoading(button, async () => {
    try {
      await api("/api/v1/indexers/grab", {
        method: "POST",
        body: JSON.stringify({
          show_id: showId,
          download_url: result.download_url,
          release_title: result.title,
          matched_alias: result.matched_alias || null,
          page_url: result.page_url || result.guid || null,
          season: INTERACTIVE_SEARCH_STATE.season,
          episode: INTERACTIVE_SEARCH_STATE.episode,
        }),
      });
      toast(t("history.event.grabbed"));
      button.textContent = "✓ Захвачен";
      button.disabled = true;
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

// =============================================================================
// ADD SHOW WIZARD
// =============================================================================

let WIZARD_STATE = { method: null, sourceId: null, selectedResult: null };

function openAddShowWizard() {
  WIZARD_STATE = { method: null, sourceId: null, selectedResult: null };
  renderWizardStep(1);
  openModal("wizard-modal");
}

function setWizardStepIndicator(step) {
  [1, 2, 3].forEach(n => {
    const el = document.getElementById(`wizard-step-${n}`);
    el.classList.toggle("active", n === step);
    el.classList.toggle("done", n < step);
  });
}

function renderWizardStep(step) {
  setWizardStepIndicator(step);
  const content = document.getElementById("wizard-content");

  if (step === 1) {
    content.innerHTML = `
      <div class="wizard-method-choice">
        <div class="wizard-method-card" onclick="chooseWizardMethod('metadata')">
          <div class="icon"><i data-lucide="search" style="width:28px;height:28px;"></i></div>
          <h4>${t("wizard.method_metadata_title")}</h4>
          <p>${t("wizard.method_metadata_desc")}</p>
        </div>
        <div class="wizard-method-card" onclick="chooseWizardMethod('manual')">
          <div class="icon"><i data-lucide="edit-3" style="width:28px;height:28px;"></i></div>
          <h4>${t("wizard.method_manual_title")}</h4>
          <p>${t("wizard.method_manual_desc")}</p>
        </div>
      </div>`;
    if (window.lucide) lucide.createIcons();
    return;
  }

  if (step === 2 && WIZARD_STATE.method === "metadata") {
    content.innerHTML = `
      <div class="form-row">
        <select id="wizard-source-select" class="input"></select>
        <input id="wizard-search-input" class="input input-grow" type="text" placeholder="${t("wizard.search_placeholder")}"
          onkeydown="if(event.key==='Enter') runWizardMetadataSearch()">
        <button class="btn btn-primary" onclick="runWizardMetadataSearch()">${t("common.search")}</button>
      </div>
      <div id="wizard-search-results" class="metadata-results" style="margin-top:14px;"></div>
      <div class="wizard-nav">
        <button class="btn btn-secondary" onclick="renderWizardStep(1)">${t("wizard.back")}</button>
      </div>`;
    loadSourcesIntoWizardSelect();
    return;
  }

  if (step === 2 && WIZARD_STATE.method === "manual") {
    content.innerHTML = `
      <div class="form-col">
        <label>${t("wizard.manual_title_label")}</label>
        <input id="wizard-manual-title" class="input" type="text" placeholder="${t("wizard.manual_title_placeholder")}">
        <label class="hint">${t("wizard.manual_aliases_label")}</label>
        <textarea id="wizard-manual-aliases" class="input mono" rows="4" placeholder="Крестьянин 999 уровня | ru&#10;Lv999 no Murabito | romaji"></textarea>
        <label>${t("wizard.manual_cover_label")}</label>
        <div class="cover-manual-row">
          <div class="cover-manual-preview" id="wizard-manual-cover-preview">${t("wizard.manual_no_cover")}</div>
          <div class="cover-manual-actions">
            <button type="button" class="btn btn-secondary btn-small" onclick="document.getElementById('wizard-manual-cover-file').click()">${t("wizard.manual_upload_cover")}</button>
            <input id="wizard-manual-cover-file" type="file" accept="image/*" style="display:none" onchange="onWizardManualCoverFile(event)">
            <input id="wizard-manual-cover-url" class="input input-small" type="text" placeholder="${t("wizard.manual_cover_url_placeholder")}" oninput="onWizardManualCoverUrl(this.value)">
          </div>
        </div>
      </div>
      <div class="wizard-nav">
        <button class="btn btn-secondary" onclick="renderWizardStep(1)">${t("wizard.back")}</button>
        <button class="btn btn-primary" onclick="proceedManualToStep3()">${t("wizard.next")}</button>
      </div>`;
    return;
  }

  if (step === 3) {
    loadQualityProfilesForWizard().then(() => renderWizardStep3Content());
  }
}

function getContentTypeLabels() {
  return {
    movie: t("settings.cat_movies"),
    series: t("settings.cat_series"),
    anime: t("settings.cat_anime")
  };
}

function guessContentTypeFromMetadata(result) {
  return result && result.content_type === "movie" ? "movie" : "series";
}

function onWizardManualCoverFile(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    WIZARD_STATE.manualCoverDataUrl = reader.result;
    document.getElementById("wizard-manual-cover-url").value = "";
    const preview = document.getElementById("wizard-manual-cover-preview");
    if (preview) preview.innerHTML = `<img src="${reader.result}" alt="">`;
  };
  reader.readAsDataURL(file);
}

function onWizardManualCoverUrl(url) {
  WIZARD_STATE.manualCoverDataUrl = null;
  WIZARD_STATE.manualCoverUrl = url.trim();
  const preview = document.getElementById("wizard-manual-cover-preview");
  if (preview) preview.innerHTML = url.trim() ? `<img src="${escapeHtml(url.trim())}" alt="">` : t("wizard.manual_no_cover");
}

function chooseWizardMethod(method) {
  WIZARD_STATE.method = method;
  renderWizardStep(2);
}

async function loadSourcesIntoWizardSelect() {
  const select = document.getElementById("wizard-source-select");
  if (!select) return;
  try {
    const items = await api("/api/v1/metadata-sources");
    CACHED_METADATA_SOURCES = items || [];
    const autoLabel = CURRENT_LANG === "en" ? "All Sources" : "Все источники";
    let optionsHtml = `<option value="all">${autoLabel}</option>`;
    if (items && items.length) {
      optionsHtml += items.map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join("");
    }
    select.innerHTML = optionsHtml;
  } catch (e) {
    console.error("loadSourcesIntoWizardSelect error:", e);
    select.innerHTML = `<option value="all">${CURRENT_LANG === "en" ? "All Sources" : "Все источники"}</option>`;
  }
}

let WIZARD_SEARCH_RESULTS = [];

async function runWizardMetadataSearch() {
  const sourceId = document.getElementById("wizard-source-select").value;
  const query = document.getElementById("wizard-search-input").value.trim();
  const resultsEl = document.getElementById("wizard-search-results");
  if (!query) return;

  resultsEl.innerHTML = `<p>${t("common.loading")}</p>`;
  try {
    let url = `/api/v1/metadata-sources/search?query=${encodeURIComponent(query)}`;
    if (sourceId && sourceId !== "all") {
      url = `/api/v1/metadata-sources/${sourceId}/search?query=${encodeURIComponent(query)}`;
    }
    const results = await api(url);
    WIZARD_SEARCH_RESULTS = results || [];
    if (!results.length) { resultsEl.innerHTML = `<p style='color:var(--text-muted)'>${t("library.no_results")}</p>`; return; }
    resultsEl.innerHTML = results.map((r, idx) => renderMetadataResultCard(r, idx, sourceId)).join("");
  } catch (e) {
    if (e.message !== "unauthorized") resultsEl.innerHTML = `<p style="color:var(--danger)">${CURRENT_LANG === "en" ? "Error:" : "Ошибка:"} ${escapeHtml(formatToastMessage(e.message))}</p>`;
  }
}

function renderMetadataResultCard(r, index, sourceId) {
  const badges = [
    r.year ? `<span class="meta-badge">${r.year}</span>` : "",
    r.rating ? `<span class="meta-badge meta-badge-rating">★ ${Number(r.rating).toFixed(1)}</span>` : "",
    r.content_type ? `<span class="meta-badge">${r.content_type === "movie" ? t("settings.cat_movies") : (r.content_type === "anime" ? t("settings.cat_anime") : t("settings.cat_series"))}</span>` : "",
    r.country ? `<span class="meta-badge">${escapeHtml(r.country)}</span>` : "",
    r.genre ? `<span class="meta-badge">${escapeHtml(r.genre)}</span>` : "",
  ].filter(Boolean).join("");

  return `
    <div class="metadata-result-card ${r.already_added ? "already-added" : ""}">
      <div class="metadata-result-poster" ${r.poster_url ? `style="background-image:url('${r.poster_url}')"` : ""}>
        ${r.poster_url ? "" : (r.title || "?").trim()[0]?.toUpperCase() || "?"}
      </div>
      <div class="metadata-result-info">
        <div class="metadata-result-title">${escapeHtml(r.title)}</div>
        <div class="metadata-result-badges">${badges}</div>
        ${r.overview ? `<p class="metadata-result-overview">${escapeHtml(r.overview)}</p>` : ""}
      </div>
      <div class="metadata-result-action">
        ${r.already_added
          ? `<span class="already-added-label">${t("wizard.already_in_library")}</span>`
          : `<button class="btn btn-primary btn-small" onclick="chooseWizardMetadataResultByIndex(${index})">${t("wizard.select")}</button>`}
      </div>
    </div>`;
}

function chooseWizardMetadataResultByIndex(index) {
  const result = WIZARD_SEARCH_RESULTS[index];
  if (!result) return;
  const sourceSelect = document.getElementById("wizard-source-select");
  const sourceId = (sourceSelect && sourceSelect.value !== "all") ? Number(sourceSelect.value) : (CACHED_METADATA_SOURCES[0]?.id || null);
  WIZARD_STATE.sourceId = sourceId;
  WIZARD_STATE.selectedResult = result;
  WIZARD_STATE.contentType = guessContentTypeFromMetadata(result);
  renderWizardStep(3);
}

function proceedManualToStep3() {
  const title = document.getElementById("wizard-manual-title").value.trim();
  if (!title) { toast(CURRENT_LANG === "en" ? "Title required" : "Введите название", true); return; }
  WIZARD_STATE.manualTitle = title;
  WIZARD_STATE.manualAliases = document.getElementById("wizard-manual-aliases").value;
  if (!WIZARD_STATE.contentType) WIZARD_STATE.contentType = "series";
  renderWizardStep(3);
}

async function loadQualityProfilesForWizard() {
  try { CACHED_QUALITY_PROFILES = await api("/api/v1/quality-profiles"); } catch (e) { CACHED_QUALITY_PROFILES = []; }
}

function renderWizardStep3Content() {
  const content = document.getElementById("wizard-content");
  const isMetadata = WIZARD_STATE.method === "metadata";
  const title = isMetadata ? WIZARD_STATE.selectedResult.title : WIZARD_STATE.manualTitle;
  const currentType = WIZARD_STATE.contentType || "series";

  content.innerHTML = `
    <p><strong>${escapeHtml(title)}</strong> ${isMetadata && WIZARD_STATE.selectedResult.year ? `(${WIZARD_STATE.selectedResult.year})` : ""}</p>
    <div class="form-col">
      <label>${t("wizard.category_label")} <span class="hint">${t("wizard.category_hint")}</span></label>
      <div class="chip-select" id="wizard-content-type-chips">
        ${Object.entries(getContentTypeLabels()).map(([val, label]) => `
          <button type="button" class="chip ${val === currentType ? "chip-selected" : ""}" data-value="${val}"
            onclick="selectWizardContentType('${val}')">${label}</button>
        `).join("")}
      </div>
      <label>${t("library.col_profile")}</label>
      <select id="wizard-quality-profile" class="input">
        <option value="">${t("common.any_quality")}</option>
        ${CACHED_QUALITY_PROFILES.map(qp => `<option value="${qp.id}">${escapeHtml(qp.name)}</option>`).join("")}
      </select>
      <label class="checkbox-row"><input id="wizard-monitored" type="checkbox" checked> <span>${t("wizard.monitor_immediately")}</span></label>
      <label class="checkbox-row" style="margin-top:2px;"><input id="wizard-autosearch" type="checkbox" checked> <span>${t("wizard.autosearch_after_add")}</span></label>
    </div>
    <div class="wizard-nav">
      <button class="btn btn-secondary" onclick="renderWizardStep(2)">${t("wizard.back")}</button>
      <button class="btn btn-primary" id="wizard-finish-btn" onclick="finishWizard(this)">${t("wizard.finish_btn")}</button>
    </div>`;
}

function selectWizardContentType(value) {
  WIZARD_STATE.contentType = value;
  document.querySelectorAll("#wizard-content-type-chips .chip").forEach(el => {
    el.classList.toggle("chip-selected", el.dataset.value === value);
  });
}

async function finishWizard(button) {
  await withLoading(button, async () => {
    const qualityProfileId = document.getElementById("wizard-quality-profile")?.value;
    const monitored = document.getElementById("wizard-monitored") ? document.getElementById("wizard-monitored").checked : true;
    const runAutoSearch = document.getElementById("wizard-autosearch") ? document.getElementById("wizard-autosearch").checked : true;
    const contentType = WIZARD_STATE.contentType || "series";

    try {
      let showId;
      let title = "";
      if (WIZARD_STATE.method === "metadata") {
        if (!WIZARD_STATE.selectedResult) {
          throw new Error(CURRENT_LANG === "en" ? "No title selected" : "Тайтл не выбран");
        }
        const result = await api("/api/v1/metadata-sources/import", {
          method: "POST",
          body: JSON.stringify({
            source_id: WIZARD_STATE.sourceId ? Number(WIZARD_STATE.sourceId) : null,
            external_id: String(WIZARD_STATE.selectedResult.external_id),
            path: null,
            content_type: contentType,
          }),
        });
        showId = result.show_id;
        title = result.title;
      } else {
        const aliasLines = (WIZARD_STATE.manualAliases || "").split("\n").map(l => l.trim()).filter(Boolean);
        const aliases = aliasLines.map(line => {
          const [text, lang] = line.split("|").map(p => p.trim());
          return { text: text || line, language: lang || "ru" };
        });
        const posterUrl = WIZARD_STATE.manualCoverDataUrl || WIZARD_STATE.manualCoverUrl || null;
        const show = await api("/api/v1/shows", {
          method: "POST",
          body: JSON.stringify({
            title: WIZARD_STATE.manualTitle, path: null, aliases,
            content_type: contentType, poster_url: posterUrl,
          }),
        });
        showId = show.id;
        title = show.title;
      }

      if (showId) {
        await api(`/api/v1/shows/${showId}`, {
          method: "PUT",
          body: JSON.stringify({
            quality_profile_id: qualityProfileId ? Number(qualityProfileId) : null,
            monitored,
          }),
        });
      }

      toast((CURRENT_LANG === "en" ? "Added to library: " : "Добавлено в библиотеку: ") + `«${title}»`);
      closeModal("wizard-modal");
      await loadShows();
      switchTab("library");

      if (runAutoSearch && showId) {
        toast(CURRENT_LANG === "en" ? "Starting auto-search…" : "Запуск автопоиска…");
        api(`/api/v1/shows/${showId}/search`, { method: "POST" }).then(res => {
          if (res && res.grabbed && res.grabbed.length > 0) {
            toast((CURRENT_LANG === "en" ? "Grabbed release: " : "Захвачен релиз: ") + res.grabbed.map(g => g.title || g).join(", "));
          }
          loadShows();
        }).catch(err => {
          console.warn("Auto-search error after adding:", err);
        });
      }
    } catch (e) {
      console.error("finishWizard error:", e);
      toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
    }
  });
}

// =============================================================================
// ACTIVITY / QUEUE
// =============================================================================

let QUEUE_DELETE_TARGET = { hash: null, name: "" };

async function loadQueue() {
  const tbody = document.querySelector("#queue-table tbody");
  if (!tbody) return;
  try {
    const items = await api("/api/v1/queue");
    const pct = (p) => Math.round((p || 0) * 100);
    const canManage = hasPermission("manage_activity") || hasPermission("manual_search");

    tbody.innerHTML = items.map(i => {
      const isPaused = (i.state || "").toLowerCase().includes("pause") ||
                       (i.state || "").toLowerCase().includes("stop") ||
                       (i.state || "").toLowerCase().includes("halt") ||
                       i.state === "0";
      const speedStr = i.download_speed > 0 ? `${(i.download_speed / (1024 * 1024)).toFixed(1)} MB/s` : "—";
      const etaStr = i.time_left || "—";
      const showLabel = i.show_title ? `<div style="font-weight:600; color:var(--text);">${escapeHtml(i.show_title)}</div>` : "";
      const epBadge = i.episode_label ? `<span class="badge badge-primary" style="margin-right:4px;">${escapeHtml(i.episode_label)}</span>` : "";
      const toggleTitle = isPaused
        ? (CURRENT_LANG === "en" ? "Resume download" : "Возобновить раздачу")
        : (CURRENT_LANG === "en" ? "Pause download" : "Приостановить раздачу");
      const toggleIcon = isPaused ? "play" : "pause";

      return `
        <tr>
          <td>
            ${showLabel}
            <div class="mono ellipsis-cell" style="font-size:12px; color:var(--text-muted);" title="${escapeHtml(i.name)}">
              ${epBadge}${escapeHtml(i.name)}
            </div>
          </td>
          <td><span class="badge badge-secondary">${escapeHtml(i.download_client)}</span></td>
          <td class="mono" style="font-size:12px;">${formatSize(i.size)}</td>
          <td>
            <div class="queue-speed-badge">${speedStr}</div>
            <div class="queue-eta-badge">${etaStr !== "—" ? `ETA: ${etaStr}` : ""}</div>
          </td>
          <td>
            <div class="queue-progress-bar-wrap">
              <div class="queue-progress-bar"><div class="queue-progress-fill" style="width:${pct(i.progress)}%"></div></div>
              <div class="queue-progress-meta">
                <span>${pct(i.progress)}%</span>
                <span>${formatSize(i.size * (i.progress || 0))}</span>
              </div>
            </div>
          </td>
          <td>
            <span class="badge ${isPaused ? "badge-secondary" : "badge-accent"}">${escapeHtml(i.state)}</span>
          </td>
          <td>
            ${canManage ? `
              <div class="row-actions">
                <button class="btn-icon-only ${isPaused ? "active" : ""}" title="${toggleTitle}" onclick="toggleQueueItemPause(this, '${i.hash}', ${isPaused})">
                  <i data-lucide="${toggleIcon}" class="ico-sm"></i>
                </button>
                <button class="btn-icon-only danger" title="${t("activity.delete_title")}" onclick="openQueueDeleteModal('${i.hash}', '${escapeHtml(i.name).replace(/'/g, "&apos;")}')">
                  <i data-lucide="trash-2" class="ico-sm"></i>
                </button>
              </div>
            ` : ""}
          </td>
        </tr>`;
    }).join("") || `<tr><td colspan="7" style="color:var(--text-muted); text-align:center; padding:30px;">${t("activity.empty")}</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {}
}

async function toggleQueueItemPause(button, hash, isCurrentlyPaused) {
  if (button) button.disabled = true;
  try {
    const action = isCurrentlyPaused ? "resume" : "pause";
    await api(`/api/v1/queue/${encodeURIComponent(hash)}/${action}`, { method: "POST" });
    toast(isCurrentlyPaused
      ? (CURRENT_LANG === "en" ? "Download resumed" : "Загрузка возобновлена")
      : (CURRENT_LANG === "en" ? "Download paused" : "Загрузка приостановлена")
    );
    await loadQueue();
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function pauseQueueItem(hash) {
  await toggleQueueItemPause(null, hash, false);
}

async function resumeQueueItem(hash) {
  await toggleQueueItemPause(null, hash, true);
}

function openQueueDeleteModal(hash, name) {
  QUEUE_DELETE_TARGET = { hash, name };
  const promptEl = document.getElementById("queue-delete-prompt");
  if (promptEl) promptEl.textContent = `Удалить раздачу «${name}» из очереди загрузчика?`;
  const chk = document.getElementById("queue-delete-files");
  if (chk) chk.checked = false;
  openModal("queue-delete-modal");
}

async function confirmDeleteQueueItem() {
  if (!QUEUE_DELETE_TARGET.hash) return;
  const deleteFiles = document.getElementById("queue-delete-files")?.checked || false;
  try {
    await api(`/api/v1/queue/${encodeURIComponent(QUEUE_DELETE_TARGET.hash)}?delete_files=${deleteFiles}`, { method: "DELETE" });
    toast(t("activity.deleted_toast"));
    closeModal("queue-delete-modal");
    loadQueue();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function triggerWantedSearch() {
  if (!hasPermission("manual_search")) {
    toast(CURRENT_LANG === "en" ? "Permission denied" : "Недостаточно прав", true);
    return;
  }
  const button = document.getElementById("wanted-search-btn");
  await withLoading(button, async () => {
    try {
      const result = await api("/api/v1/search/wanted", { method: "POST" });
      toast(t("dash.toast_grabbed_for_shows", { count: result.grabbed_shows }));
      loadQueue();
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

async function triggerManualCheckDownloads() {
  toast(CURRENT_LANG === "en" ? "Checking completed downloads..." : "Проверка завершённых загрузок...");
  try {
    const res = await api("/api/v1/queue/check", { method: "POST" });
    const count = res.processed || 0;
    if (count > 0) {
      toast(CURRENT_LANG === "en" ? `Imported ${count} completed release(s)!` : `Успешно перенесено релизов: ${count}`);
    } else {
      toast(CURRENT_LANG === "en" ? "No new 100% completed downloads to import." : "Нет новых завершённых загрузок для переноса.");
    }
    await loadQueue();
    if (typeof CURRENT_TAB !== "undefined" && CURRENT_TAB === "library" && typeof loadShows === "function") {
      await loadShows();
    }
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error checking downloads: " : "Ошибка проверки загрузок: ") + formatToastMessage(e.message), true);
  }
}

// =============================================================================
// CALENDAR / HISTORY
// =============================================================================

// =============================================================================
// CALENDAR
// =============================================================================

const CALENDAR_STATUS_LABELS = {
  ru: {
    unaired: "Не вышло", unmonitored: "Не мониторится", on_air: "В эфире",
    missing: "Отсутствует", downloading: "Скачивается", downloaded: "Скачано", premiere: "Премьера",
  },
  en: {
    unaired: "Unaired", unmonitored: "Unmonitored", on_air: "On Air",
    missing: "Missing", downloading: "Downloading", downloaded: "Downloaded", premiere: "Premiere",
  },
};
const CALENDAR_WEEKDAY_NAMES = {
  ru: ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"],
  en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
};

function calStatusLabel(status) {
  const dict = CALENDAR_STATUS_LABELS[CURRENT_LANG] || CALENDAR_STATUS_LABELS.ru;
  return dict[status] || status;
}

const DEFAULT_CALENDAR_SETTINGS = {
  view: "month",
  filter: "all",
  category: "all",
  status: "all",
  collapse_multi: true,
  show_info: true,
  finale_badge: true,
  unmet_badge: true,
  full_color: false,
  show_cinema: true,
  show_digital: true,
  first_day: 1, // 0 = воскресенье, 1 = понедельник
  week_header: "ddd_MM/DD",
  time_format: "24h",
};

function loadCalendarSettings() {
  try {
    const raw = localStorage.getItem("vbeacon_calendar_settings");
    if (raw) return Object.assign({}, DEFAULT_CALENDAR_SETTINGS, JSON.parse(raw));
  } catch (e) {}
  return Object.assign({}, DEFAULT_CALENDAR_SETTINGS);
}

let CALENDAR_SETTINGS = loadCalendarSettings();
let CALENDAR_ANCHOR = new Date();
CALENDAR_ANCHOR.setHours(0, 0, 0, 0);
let CALENDAR_EVENTS_MAP = {};

async function openCalendarSettingsModal() {
  document.getElementById("cal-set-collapse-multi").checked = CALENDAR_SETTINGS.collapse_multi;
  document.getElementById("cal-set-show-info").checked = CALENDAR_SETTINGS.show_info;
  document.getElementById("cal-set-finale-badge").checked = CALENDAR_SETTINGS.finale_badge;
  document.getElementById("cal-set-unmet-badge").checked = CALENDAR_SETTINGS.unmet_badge;
  document.getElementById("cal-set-full-color").checked = CALENDAR_SETTINGS.full_color;
  const cinemaCb = document.getElementById("cal-set-show-cinema");
  if (cinemaCb) cinemaCb.checked = CALENDAR_SETTINGS.show_cinema !== false;
  const digitalCb = document.getElementById("cal-set-show-digital");
  if (digitalCb) digitalCb.checked = CALENDAR_SETTINGS.show_digital !== false;
  document.getElementById("cal-set-first-day").value = String(CALENDAR_SETTINGS.first_day);
  document.getElementById("cal-set-week-header").value = CALENDAR_SETTINGS.week_header;
  document.getElementById("cal-set-time-format").value = CALENDAR_SETTINGS.time_format;
  try {
    const s = await api("/api/v1/settings");
    document.getElementById("cal-set-poll-enabled").checked = !!s.calendar_poll_enabled;
    document.getElementById("cal-set-poll-interval").value = s.calendar_poll_interval_minutes ?? 180;
    const seriesSourceEl = document.getElementById("cal-set-metadata-source-series");
    if (seriesSourceEl) seriesSourceEl.value = s.calendar_metadata_source_series || "skyhook";
    const movieSourceEl = document.getElementById("cal-set-metadata-source-movie");
    if (movieSourceEl) movieSourceEl.value = s.calendar_metadata_source_movie || "radarr";
  } catch (e) {}
  openModal("calendar-settings-modal");
}

async function saveCalendarSettings() {
  CALENDAR_SETTINGS.collapse_multi = document.getElementById("cal-set-collapse-multi").checked;
  CALENDAR_SETTINGS.show_info = document.getElementById("cal-set-show-info").checked;
  CALENDAR_SETTINGS.finale_badge = document.getElementById("cal-set-finale-badge").checked;
  CALENDAR_SETTINGS.unmet_badge = document.getElementById("cal-set-unmet-badge").checked;
  CALENDAR_SETTINGS.full_color = document.getElementById("cal-set-full-color").checked;
  const cinemaCb = document.getElementById("cal-set-show-cinema");
  if (cinemaCb) CALENDAR_SETTINGS.show_cinema = cinemaCb.checked;
  const digitalCb = document.getElementById("cal-set-show-digital");
  if (digitalCb) CALENDAR_SETTINGS.show_digital = digitalCb.checked;
  CALENDAR_SETTINGS.first_day = Number(document.getElementById("cal-set-first-day").value);
  CALENDAR_SETTINGS.week_header = document.getElementById("cal-set-week-header").value;
  CALENDAR_SETTINGS.time_format = document.getElementById("cal-set-time-format").value;
  try { localStorage.setItem("vbeacon_calendar_settings", JSON.stringify(CALENDAR_SETTINGS)); } catch (e) {}
  try {
    const seriesSrc = document.getElementById("cal-set-metadata-source-series")?.value || "skyhook";
    const movieSrc = document.getElementById("cal-set-metadata-source-movie")?.value || "radarr";
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({
        calendar_poll_enabled: document.getElementById("cal-set-poll-enabled").checked,
        calendar_poll_interval_minutes: Number(document.getElementById("cal-set-poll-interval").value) || 180,
        calendar_metadata_source_series: seriesSrc,
        calendar_metadata_source_movie: movieSrc,
        calendar_metadata_source: "auto",
      }),
    });
    toast(t("settings.toast_saved"));
  } catch (e) { toast("Ошибка сохранения настроек опроса: " + e.message, true); }
  closeModal("calendar-settings-modal");
  loadCalendar();
}

function setCalendarView(view) {
  CALENDAR_SETTINGS.view = view;
  try { localStorage.setItem("vbeacon_calendar_settings", JSON.stringify(CALENDAR_SETTINGS)); } catch (e) {}
  loadCalendar();
}

function setCalendarFilter(filter) {
  CALENDAR_SETTINGS.filter = filter;
  try { localStorage.setItem("vbeacon_calendar_settings", JSON.stringify(CALENDAR_SETTINGS)); } catch (e) {}
  loadCalendar();
}

function setCalendarCategoryFilter(cat) {
  CALENDAR_SETTINGS.category = cat;
  try { localStorage.setItem("vbeacon_calendar_settings", JSON.stringify(CALENDAR_SETTINGS)); } catch (e) {}
  loadCalendar();
}

function setCalendarStatusFilter(status) {
  CALENDAR_SETTINGS.status = status;
  try { localStorage.setItem("vbeacon_calendar_settings", JSON.stringify(CALENDAR_SETTINGS)); } catch (e) {}
  loadCalendar();
}

async function searchCalendarMissing() {
  if (!confirm(t("calendar.search_missing_confirm"))) return;
  const btn = document.getElementById("calendar-search-missing-btn");
  await withLoading(btn, async () => {
    try {
      const view = CALENDAR_SETTINGS.view;
      let daysBack = 14, daysForward = 60;
      if (view === "month") { daysBack = 14; daysForward = 45; }
      else if (view === "week" || view === "forecast") { daysBack = 7; daysForward = 14; }
      else if (view === "day") { daysBack = 1; daysForward = 1; }

      const payload = {
        days_back: daysBack,
        days_forward: daysForward,
        content_type: CALENDAR_SETTINGS.category || "all",
        monitored_only: CALENDAR_SETTINGS.filter === "monitored",
      };
      const res = await api("/api/v1/calendar/search-missing", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!res.searched_shows) {
        toast(CURRENT_LANG === "en" ? "No missing releases found in the selected period" : "Нет отсутствующих релизов за выбранный период");
      } else {
        toast(t("calendar.search_missing_started", { count: res.searched_shows, total: res.episodes_count || res.total_targets }));
      }
    } catch (e) {
      toast("Ошибка: " + e.message, true);
    }
  });
}

function openCalendarIcalModal() {
  const currentKey = document.getElementById("setting-apikey")?.value || "";
  const host = window.location.origin;
  const cat = CALENDAR_SETTINGS.category || "all";
  const mon = CALENDAR_SETTINGS.filter === "monitored";

  let q = `?content_type=${encodeURIComponent(cat)}&monitored_only=${mon}`;
  if (currentKey) q += `&apikey=${encodeURIComponent(currentKey)}`;

  const httpsUrl = `${host}/api/v1/calendar/aliasarr.ics${q}`;
  const webcalUrl = httpsUrl.replace(/^http/, "webcal");

  document.getElementById("cal-ical-feed-url").value = httpsUrl;
  document.getElementById("cal-ical-webcal-url").value = webcalUrl;
  openModal("calendar-ical-modal");
}

function copyCalendarIcalUrl(type) {
  const input = document.getElementById(type === "webcal" ? "cal-ical-webcal-url" : "cal-ical-feed-url");
  if (input) {
    input.select();
    navigator.clipboard.writeText(input.value);
    toast(t("calendar.ical_copied"));
  }
}

function openCalendarEventModal(eKey) {
  const e = (typeof eKey === "string" ? CALENDAR_EVENTS_MAP[eKey] : eKey) || {};
  const isMovie = e.content_type === "movie";
  const isAnime = e.content_type === "anime";
  const catName = isMovie ? t("calendar.cat_movies") : (isAnime ? t("calendar.cat_anime") : t("calendar.cat_series"));
  const catClass = isMovie ? "cat-movies" : (isAnime ? "cat-anime" : "cat-series");

  const epLabel = (e.season != null && e.episode != null) ? `S${pad2(e.season)}E${pad2(e.episode)}${e.absolute_episode ? ` (${e.absolute_episode})` : ''}` : "";
  const dateStr = e.air_date ? new Date(e.air_date).toLocaleDateString(CURRENT_LANG === "en" ? "en-US" : "ru-RU", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

  const posterUrl = e.poster_url || "/static/img/no-poster.svg";

  let badgesHtml = `<span class="badge ${catClass}">${catName}</span>`;
  badgesHtml += `<span class="status-pill status-${e.status}">${escapeHtml(calStatusLabel(e.status))}</span>`;
  if (e.rating) badgesHtml += `<span class="meta-badge meta-badge-rating">★ ${Number(e.rating).toFixed(1)}</span>`;

  let releaseBadgesHtml = "";
  if (isMovie && e.release_types && e.release_types.length) {
    if (e.release_types.includes("cinemas")) releaseBadgesHtml += `<span class="cal-release-badge cal-badge-cinema">🎬 ${t("calendar.badge_cinema")}</span>`;
    if (e.release_types.includes("digital")) releaseBadgesHtml += `<span class="cal-release-badge cal-badge-digital">💻 ${t("calendar.badge_digital")}</span>`;
    if (e.release_types.includes("physical")) releaseBadgesHtml += `<span class="cal-release-badge cal-badge-physical">💿 ${t("calendar.badge_physical")}</span>`;
  }

  const canManage = hasPermission("manage_library") || hasPermission("manage_calendar");

  const modalHtml = `
    <div class="cal-ev-modal-wrap">
      <div class="cal-ev-modal-header">
        <img class="cal-ev-modal-poster" src="${escapeHtml(posterUrl)}" alt="${escapeHtml(e.show_title || '')}" onerror="this.src='/static/img/no-poster.svg'">
        <div class="cal-ev-modal-info">
          <div class="cal-ev-modal-title">${escapeHtml(e.show_title || '')} ${e.year ? `<span style="font-size:14px; font-weight:normal; color:var(--text-muted);">(${e.year})</span>` : ""}</div>
          <div class="cal-ev-modal-sub">${epLabel ? `${epLabel} ${e.title ? "— " + escapeHtml(e.title) : ""}` : (e.title ? escapeHtml(e.title) : "")}</div>
          <div class="cal-ev-modal-badges">
            ${badgesHtml}
            ${releaseBadgesHtml}
          </div>
          ${e.overview ? `<div class="cal-ev-modal-overview">${escapeHtml(e.overview)}</div>` : ""}
        </div>
      </div>

      <div class="cal-ev-modal-details-grid">
        <div class="cal-ev-modal-details-item">
          <span class="label">${isMovie ? "Дата премьеры" : "Дата выхода серии"}:</span>
          <span class="val">${dateStr}</span>
        </div>
        <div class="cal-ev-modal-details-item">
          <span class="label">Отслеживание:</span>
          <span class="val">${e.monitored ? "Включено" : "Отключено"}</span>
        </div>
      </div>

      <div class="cal-ev-modal-actions">
        ${canManage ? `
          <button class="btn btn-secondary btn-small" onclick="closeModal('calendar-event-modal'); promptEditCalendarDate(${e.episode_id ?? "null"}, ${e.show_id}, '${escapeHtml(e.show_title || '').replace(/'/g, "\\'")}')">
            <i data-lucide="edit-2" class="ico-xs"></i> <span>${t("calendar.btn_edit_date")}</span>
          </button>
          <button class="btn btn-secondary btn-small" onclick="closeModal('calendar-event-modal'); openInteractiveSearch(${e.show_id}, ${e.episode_id && e.season != null ? e.season : 'null'}, ${e.episode_id && e.episode != null ? e.episode : 'null'})">
            <i data-lucide="search" class="ico-xs"></i> <span>${t("calendar.btn_manual_search")}</span>
          </button>
          <button class="btn btn-primary btn-small" onclick="closeModal('calendar-event-modal'); triggerAutoSearchForCalEvent(${e.show_id}, ${e.episode_id ?? "null"})">
            <i data-lucide="zap" class="ico-xs"></i> <span>${t("calendar.btn_auto_search")}</span>
          </button>
        ` : ""}
        <button class="btn btn-secondary btn-small" onclick="closeModal('calendar-event-modal'); openShowModal(${e.show_id})">
          <i data-lucide="external-link" class="ico-xs"></i> <span>${t("calendar.btn_open_card")}</span>
        </button>
      </div>
    </div>
  `;

  document.getElementById("cal-ev-modal-content").innerHTML = modalHtml;
  if (window.lucide) {
    lucide.createIcons({
      nameAttr: 'data-lucide',
      attrs: { stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }
    });
  }
  openModal("calendar-event-modal");
}

async function triggerAutoSearchForCalEvent(showId, episodeId) {
  try {
    let res;
    if (episodeId) {
      res = await api(`/api/v1/shows/${showId}/search-episode`, {
        method: "POST",
        body: JSON.stringify({ episode_ids: [episodeId] }),
      });
    } else {
      res = await api(`/api/v1/shows/${showId}/search`, { method: "POST" });
    }
    toast(res.grabbed ? "Релиз успешно захвачен!" : (res.message || "Поиск завершён"));
    loadCalendar();
  } catch (e) {
    toast("Ошибка автопоиска: " + e.message, true);
  }
}

function calendarGoToday() {
  CALENDAR_ANCHOR = new Date();
  CALENDAR_ANCHOR.setHours(0, 0, 0, 0);
  loadCalendar();
}

function calendarNav(dir) {
  const view = CALENDAR_SETTINGS.view;
  if (view === "month") {
    CALENDAR_ANCHOR.setMonth(CALENDAR_ANCHOR.getMonth() + dir);
  } else if (view === "week" || view === "forecast") {
    CALENDAR_ANCHOR.setDate(CALENDAR_ANCHOR.getDate() + dir * 7);
  } else {
    CALENDAR_ANCHOR.setDate(CALENDAR_ANCHOR.getDate() + dir);
  }
  loadCalendar();
}

function calStartOfWeek(date) {
  const d = new Date(date);
  const firstDay = CALENDAR_SETTINGS.first_day; // 0 = вс, 1 = пн
  const diff = (d.getDay() - firstDay + 7) % 7;
  d.setDate(d.getDate() - diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function calFormatWeekdayHeader(date) {
  const name = CALENDAR_WEEKDAY_NAMES[CURRENT_LANG === "en" ? "en" : "ru"][date.getDay()];
  const m = date.getMonth() + 1, d = date.getDate();
  switch (CALENDAR_SETTINGS.week_header) {
    case "ddd_MM/DD": return `${name} ${pad2(m)}/${pad2(d)}`;
    case "ddd_D/M": return `${name} ${d}/${m}`;
    case "ddd_DD/MM": return `${name} ${pad2(d)}/${pad2(m)}`;
    default: return `${name} ${m}/${d}`;
  }
}

function pad2(n) { return String(n).padStart(2, "0"); }

function calFormatTime(dateObj) {
  let h = dateObj.getHours(), min = dateObj.getMinutes();
  if (CALENDAR_SETTINGS.time_format === "12h") {
    const ampm = h >= 12 ? "pm" : "am";
    let h12 = h % 12; if (h12 === 0) h12 = 12;
    return min ? `${h12}:${pad2(min)}${ampm}` : `${h12}${ampm}`;
  }
  return `${pad2(h)}:${pad2(min)}`;
}

function calFormatDateLabel(date) {
  return date.toLocaleDateString(CURRENT_LANG === "en" ? "en-US" : "ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

function calFormatDateFull(date) {
  const isEn = CURRENT_LANG === "en";
  const weekday = date.toLocaleDateString(isEn ? "en-US" : "ru-RU", { weekday: "long" });
  const capitalizedWeekday = weekday.charAt(0).toUpperCase() + weekday.slice(1);
  const dateStr = date.toLocaleDateString(isEn ? "en-US" : "ru-RU", { day: "numeric", month: "long", year: "numeric" });
  return `${capitalizedWeekday}, ${dateStr}`;
}

function calGetRelativeDayBadge(date) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const target = new Date(date); target.setHours(0, 0, 0, 0);
  const diffDays = Math.round((target - today) / 86400000);
  if (diffDays === 0) {
    return `<span class="cal-relative-badge today">${t("calendar.badge_today")}</span>`;
  } else if (diffDays === 1) {
    return `<span class="cal-relative-badge tomorrow">${t("calendar.badge_tomorrow")}</span>`;
  } else if (diffDays === -1) {
    return `<span class="cal-relative-badge yesterday">${t("calendar.badge_yesterday")}</span>`;
  }
  return "";
}

async function loadCalendar() {
  const viewSelect = document.getElementById("calendar-view-select");
  if (viewSelect) viewSelect.value = CALENDAR_SETTINGS.view;
  const filterSelect = document.getElementById("calendar-filter-select");
  if (filterSelect) filterSelect.value = CALENDAR_SETTINGS.filter;
  const catSelect = document.getElementById("calendar-cat-select");
  if (catSelect) catSelect.value = CALENDAR_SETTINGS.category || "all";
  const statusSelect = document.getElementById("calendar-status-select");
  if (statusSelect) statusSelect.value = CALENDAR_SETTINGS.status || "all";

  const view = CALENDAR_SETTINGS.view;
  let rangeStart, rangeEnd, periodLabel;

  if (view === "month") {
    rangeStart = new Date(CALENDAR_ANCHOR.getFullYear(), CALENDAR_ANCHOR.getMonth(), 1);
    rangeStart = calStartOfWeek(rangeStart);
    rangeEnd = new Date(rangeStart); rangeEnd.setDate(rangeEnd.getDate() + 41);
    periodLabel = CALENDAR_ANCHOR.toLocaleDateString(CURRENT_LANG === "en" ? "en-US" : "ru-RU", { month: "long", year: "numeric" });
  } else if (view === "week") {
    rangeStart = calStartOfWeek(CALENDAR_ANCHOR);
    rangeEnd = new Date(rangeStart); rangeEnd.setDate(rangeEnd.getDate() + 6);
    periodLabel = `${calFormatDateLabel(rangeStart)} – ${calFormatDateLabel(rangeEnd)}`;
  } else if (view === "forecast") {
    rangeStart = new Date(CALENDAR_ANCHOR);
    rangeEnd = new Date(rangeStart); rangeEnd.setDate(rangeEnd.getDate() + 6);
    periodLabel = `${calFormatDateLabel(rangeStart)} – ${calFormatDateLabel(rangeEnd)}`;
  } else if (view === "day") {
    rangeStart = new Date(CALENDAR_ANCHOR);
    rangeEnd = new Date(CALENDAR_ANCHOR);
    periodLabel = calFormatDateLabel(rangeStart);
  } else { // agenda
    rangeStart = new Date(CALENDAR_ANCHOR);
    rangeEnd = new Date(rangeStart); rangeEnd.setDate(rangeEnd.getDate() + 30);
    periodLabel = `${calFormatDateLabel(rangeStart)} – ${calFormatDateLabel(rangeEnd)}`;
  }
  const labelEl = document.getElementById("calendar-period-label");
  if (labelEl) labelEl.textContent = periodLabel;

  const daysBack = Math.max(0, Math.round((new Date() - rangeStart) / 86400000));
  const daysForward = Math.max(1, Math.round((rangeEnd - new Date()) / 86400000) + 1);

  const bodyEl = document.getElementById("calendar-body");
  try {
    const monitoredOnly = CALENDAR_SETTINGS.filter === "monitored";
    const cat = CALENDAR_SETTINGS.category || "all";
    const st = CALENDAR_SETTINGS.status || "all";
    const entries = await api(`/api/v1/calendar?days_forward=${daysForward}&days_back=${daysBack}&monitored_only=${monitoredOnly}&content_type=${encodeURIComponent(cat)}&status_filter=${encodeURIComponent(st)}`);

    CALENDAR_EVENTS_MAP = {};
    const byDay = {};
    entries.forEach(e => {
      if (!e.air_date) return;
      const keyMap = `${e.show_id}_${e.episode_id || 'prem'}`;
      CALENDAR_EVENTS_MAP[keyMap] = e;

      const d = new Date(e.air_date);
      if (d < rangeStart || d > rangeEnd) return;
      const key = tzDayKey(d);
      (byDay[key] = byDay[key] || []).push(e);
    });

    if (view === "month" || view === "week") {
      if (window.innerWidth <= 768) {
        // На мобильных устройствах отображаем адаптивную ленту расписания
        bodyEl.innerHTML = renderCalendarLegend() + renderCalendarAgendaList(byDay, rangeStart, rangeEnd);
      } else {
        bodyEl.innerHTML = renderCalendarLegend() + renderCalendarGrid(rangeStart, view === "month" ? 42 : 7, byDay);
      }
    } else if (view === "day") {
      bodyEl.innerHTML = renderCalendarLegend() + renderCalendarAgendaList({ [rangeStart.toDateString()]: byDay[rangeStart.toDateString()] || [] }, rangeStart, rangeEnd);
    } else { // forecast / agenda
      bodyEl.innerHTML = renderCalendarLegend() + renderCalendarAgendaList(byDay, rangeStart, rangeEnd);
    }
  } catch (e) {
    bodyEl.innerHTML = `<p style="color:var(--danger)">${CURRENT_LANG === "en" ? "Calendar loading error:" : "Ошибка загрузки календаря:"} ${escapeHtml(formatToastMessage(e.message))}</p>`;
  }

  if (window.lucide) {
    lucide.createIcons({
      nameAttr: 'data-lucide',
      attrs: { stroke: 'currentColor', 'stroke-width': '2.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }
    });
  }
}

function renderCalendarLegend() {
  const badgeStatuses = ["unaired", "on_air", "downloading", "unmonitored", "missing", "downloaded"];

  let badgesHtml = `<div class="calendar-legend-group">`;
  badgeStatuses.forEach(s => {
    badgesHtml += `<span class="calendar-legend-item status-${s}">${escapeHtml(calStatusLabel(s))}</span>`;
  });
  badgesHtml += `</div>`;

  let iconsHtml = `
    <div class="calendar-legend-icons">
      <div class="calendar-legend-icon-item"><i data-lucide="play-circle"></i> ${t("calendar.premiere")}</div>
      <div class="calendar-legend-icon-item"><i data-lucide="pause-circle"></i> ${t("calendar.season_finale")}</div>
      <div class="calendar-legend-icon-item"><i data-lucide="stop-circle"></i> ${t("calendar.series_finale")}</div>
    </div>
  `;

  return `<div class="calendar-legend">${badgesHtml} ${iconsHtml}</div>`;
}

function renderCalendarGrid(startDate, numDays, byDay) {
  const weekdayNames = CALENDAR_WEEKDAY_NAMES[CURRENT_LANG === "en" ? "en" : "ru"];
  const order = [];
  for (let i = 0; i < 7; i++) order.push((CALENDAR_SETTINGS.first_day + i) % 7);
  const header = order.map(i => `<div class="calendar-weekday-header">${weekdayNames[i]}</div>`).join("");

  const today = new Date(); today.setHours(0, 0, 0, 0);
  const currentMonth = CALENDAR_ANCHOR.getMonth();

  let cells = "";
  for (let i = 0; i < numDays; i++) {
    const d = new Date(startDate); d.setDate(d.getDate() + i);
    const key = d.toDateString();
    const events = (byDay[key] || []).sort((a, b) => new Date(a.air_date) - new Date(b.air_date));
    const isToday = d.toDateString() === today.toDateString();
    const outside = numDays === 42 && d.getMonth() !== currentMonth;

    const maxShown = CALENDAR_SETTINGS.collapse_multi ? 3 : events.length;
    const shown = events.slice(0, maxShown);
    const restCount = events.length - shown.length;

    const eventsHtml = shown.map(e => renderCalendarEventChip(e)).join("") +
      (restCount > 0 ? `<div class="calendar-event-more">+${restCount} ${t("calendar.more_events")}</div>` : "");

    cells += `<div class="calendar-day-cell ${outside ? "outside-month" : ""} ${isToday ? "is-today" : ""}">
      <div class="calendar-day-number">${d.getDate()}</div>
      ${eventsHtml}
    </div>`;
  }

  return `<div class="calendar-grid">${header}${cells}</div>`;
}

function truncateCalendarTitle(str, maxLen = 35) {
  if (!str) return "";
  const trimmed = str.trim();
  if (trimmed.length <= maxLen) return trimmed;
  return trimmed.slice(0, maxLen - 1).trim() + "…";
}

function renderCalendarEventChip(e) {
  const isMovie = e.content_type === "movie";
  const eKey = `${e.show_id}_${e.episode_id || 'prem'}`;

  // Фильмы: только Premiere
  const isPremiere = (e.entry_type === "premiere") || (!isMovie && e.entry_type === "episode" && e.episode === 1);

  const titleLower = (e.title || "").toLowerCase();
  const isSeriesFinale = !isMovie && CALENDAR_SETTINGS.finale_badge && e.entry_type === "episode" && (titleLower.includes("финал сериала") || titleLower.includes("series finale"));
  const isSeasonFinale = !isMovie && CALENDAR_SETTINGS.finale_badge && e.entry_type === "episode" && (titleLower.includes("финал сезона") || titleLower.includes("season finale") || (!isSeriesFinale && (titleLower.includes("финал") || titleLower.includes("finale"))));

  let iconHtml = "";
  if (isPremiere) {
    iconHtml = `<i data-lucide="play-circle" style="width: 14px; height: 14px;"></i>`;
  } else if (isSeriesFinale) {
    iconHtml = `<i data-lucide="stop-circle" style="width: 14px; height: 14px;"></i>`;
  } else if (isSeasonFinale) {
    iconHtml = `<i data-lucide="pause-circle" style="width: 14px; height: 14px;"></i>`;
  }

  const epLabel = (CALENDAR_SETTINGS.show_info && e.season != null && e.episode != null)
    ? `${e.season}x${pad2(e.episode)}${e.absolute_episode ? ` (${e.absolute_episode})` : ''}` : "";

  let movieBadge = "";
  if (isMovie && e.release_types && e.release_types.length) {
    if (e.release_types.includes("cinemas") && CALENDAR_SETTINGS.show_cinema !== false) {
      movieBadge = `<span class="cal-release-badge cal-badge-cinema"><i data-lucide="clapperboard" class="ico-xs"></i><span>${t("calendar.badge_cinema")}</span></span>`;
    } else if (e.release_types.includes("digital") && CALENDAR_SETTINGS.show_digital !== false) {
      movieBadge = `<span class="cal-release-badge cal-badge-digital"><i data-lucide="monitor" class="ico-xs"></i><span>${t("calendar.badge_digital")}</span></span>`;
    }
  }

  let timeStr = "";
  if (e.air_date) {
    const d = new Date(e.air_date);
    const dEnd = new Date(d.getTime() + 24 * 60000);
    timeStr = `${calFormatTime(d)} - ${calFormatTime(dEnd)}`;
  }

  const canManageLib = hasPermission("manage_library") || hasPermission("manage_calendar");
  const fullTooltip = `${e.show_title || ""}${epLabel ? " — " + epLabel : ""}${e.title ? " — " + e.title : ""}`;
  const displayShowTitle = truncateCalendarTitle(e.show_title, 35);
  const displayEpTitle = e.title ? truncateCalendarTitle(e.title, 30) : (isMovie ? t("calendar.movie_premiere") : "TBA");

  return `<div class="calendar-event ${CALENDAR_SETTINGS.full_color ? "calendar-full-color" : ""} status-${e.status}"
      title="${escapeHtml(fullTooltip)}" onclick="openCalendarEventModal('${eKey}')">
    <div class="cal-ev-top">
      <div class="cal-ev-title" title="${escapeHtml(e.show_title)}">${escapeHtml(displayShowTitle)}</div>
      <div style="display:flex; align-items:center; gap:4px; flex-shrink:0;">
        ${movieBadge}
        ${iconHtml ? `<div class="cal-ev-icon">${iconHtml}</div>` : ""}
      </div>
    </div>
    <div class="cal-ev-mid">
      <div class="cal-ev-ep-title" title="${e.title ? escapeHtml(e.title) : ''}">${escapeHtml(displayEpTitle)}</div>
      ${epLabel ? `<div class="cal-ev-ep-num">${epLabel}</div>` : ""}
    </div>
    <div class="cal-ev-bot">
      <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${timeStr}</div>
      ${canManageLib ? `<span class="cal-event-edit" title="${t('calendar.btn_edit_date')}" onclick="event.stopPropagation(); promptEditCalendarDate(${e.episode_id ?? "null"}, ${e.show_id}, '${escapeHtml(e.show_title).replace(/'/g, "&apos;")}')"><i data-lucide="pencil" style="width: 12px; height: 12px;"></i></span>` : ""}
    </div>
  </div>`;
}

async function promptEditCalendarDate(episodeId, showId, showTitle) {
  if (!hasPermission("manage_library")) {
    toast(CURRENT_LANG === "en" ? "Permission denied" : "Недостаточно прав для изменения календаря", true);
    return;
  }
  // Возможность сменить дату выхода конкретной серии/фильма в календаре
  // или вернуть тайтл обратно в список "неопределённая дата".
  const current = prompt(
    t("calendar.prompt_air_date", { title: showTitle }),
    new Date().toISOString().slice(0, 10)
  );
  if (current === null) return; // отмена

  try {
    if (current.trim() === "") {
      if (episodeId) {
        await api(`/api/v1/episodes/${episodeId}/air-date`, { method: "PUT", body: JSON.stringify({ air_date: null }) });
      } else {
        await api(`/api/v1/calendar/${showId}/move-to-waiting`, { method: "POST" });
      }
      toast(t("calendar.toast_removed"));
    } else {
      const parsed = new Date(current);
      if (isNaN(parsed.getTime())) { toast(t("calendar.toast_invalid_date"), true); return; }
      if (episodeId) {
        await api(`/api/v1/episodes/${episodeId}/air-date`, { method: "PUT", body: JSON.stringify({ air_date: parsed.toISOString() }) });
      } else {
        await api(`/api/v1/calendar/${showId}/move-to-calendar`, { method: "POST", body: JSON.stringify({ air_date: parsed.toISOString() }) });
      }
      toast(t("calendar.toast_date_updated"));
    }
    loadCalendar();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

function renderCalendarAgendaList(byDay, rangeStart, rangeEnd) {
  let keys = Object.keys(byDay).filter(k => (byDay[k] || []).length > 0);
  // Для day/forecast/agenda/month(mobile) перечисляем дни по порядку, если передан диапазон
  if (rangeStart && rangeEnd) {
    keys = [];
    const cursor = new Date(rangeStart);
    while (cursor <= rangeEnd) {
      keys.push(cursor.toDateString());
      cursor.setDate(cursor.getDate() + 1);
    }
    // На мобильных при месячном/недельном просмотре скрываем дни совсем без релизов, если их много,
    // но оставляем сегодняшний день (isToday), чтобы список оставался компактным и информативным!
    const todayStr = new Date().toDateString();
    keys = keys.filter(k => (byDay[k] || []).length > 0 || k === todayStr);
  }

  if (!keys.length) {
    return `<p class="hint" style="text-align:center; padding:28px 12px; font-size:13px;">${t("calendar.no_events_in_period")}</p>`;
  }
  keys.sort((a, b) => new Date(a) - new Date(b));

  const canManageLib = hasPermission("manage_library") || hasPermission("manage_calendar");
  const todayStr = new Date().toDateString();

  return `<div class="calendar-agenda-list">${keys.map(key => {
    const events = (byDay[key] || []).sort((a, b) => new Date(a.air_date) - new Date(b.air_date));
    const dateObj = new Date(key);
    const isToday = dateObj.toDateString() === todayStr;
    const relBadge = calGetRelativeDayBadge(dateObj);

    const countLabel = events.length
      ? `${events.length} ${t("calendar.events_count")}`
      : "";

    const cardsHtml = events.length
      ? events.map(e => {
          const eKey = `${e.show_id}_${e.episode_id || 'prem'}`;
          const isMovie = e.content_type === "movie";
          const isAnime = e.content_type === "anime";
          const posterStyle = e.poster_url ? `style="background-image:url('${e.poster_url}')"` : "";
          const epCode = (e.season != null && e.episode != null)
            ? `S${pad2(e.season)}E${pad2(e.episode)}${e.absolute_episode ? ` (${e.absolute_episode})` : ''}` : "";
          const epName = isMovie ? t("calendar.movie_premiere") : (e.title ? escapeHtml(truncateCalendarTitle(e.title, 50)) : "TBA");

          const isPremiere = (e.entry_type === "premiere") || (!isMovie && e.entry_type === "episode" && e.episode === 1);
          const titleLower = (e.title || "").toLowerCase();
          const isSeriesFinale = !isMovie && CALENDAR_SETTINGS.finale_badge && e.entry_type === "episode" && (titleLower.includes("финал сериала") || titleLower.includes("series finale"));
          const isSeasonFinale = !isMovie && CALENDAR_SETTINGS.finale_badge && e.entry_type === "episode" && (titleLower.includes("финал сезона") || titleLower.includes("season finale") || (!isSeriesFinale && (titleLower.includes("финал") || titleLower.includes("finale"))));

          let iconHtml = "";
          if (isPremiere) {
            iconHtml = `<i data-lucide="play-circle" style="width: 14px; height: 14px;"></i>`;
          } else if (isSeriesFinale) {
            iconHtml = `<i data-lucide="stop-circle" style="width: 14px; height: 14px;"></i>`;
          } else if (isSeasonFinale) {
            iconHtml = `<i data-lucide="pause-circle" style="width: 14px; height: 14px;"></i>`;
          }

          let movieBadge = "";
          if (isMovie && e.release_types && e.release_types.length) {
            if (e.release_types.includes("cinemas") && CALENDAR_SETTINGS.show_cinema !== false) {
              movieBadge = `<span class="cal-release-badge cal-badge-cinema"><i data-lucide="clapperboard" class="ico-xs"></i><span>${t("calendar.badge_cinema")}</span></span>`;
            } else if (e.release_types.includes("digital") && CALENDAR_SETTINGS.show_digital !== false) {
              movieBadge = `<span class="cal-release-badge cal-badge-digital"><i data-lucide="monitor" class="ico-xs"></i><span>${t("calendar.badge_digital")}</span></span>`;
            }
          }

          let timeStr = "";
          if (e.air_date) {
            const d = new Date(e.air_date);
            timeStr = calFormatTime(d);
          }

          const catName = isMovie ? t("calendar.cat_movies") : (isAnime ? t("calendar.cat_anime") : t("calendar.cat_series"));
          const catClass = isMovie ? "cat-movies" : (isAnime ? "cat-anime" : "cat-series");
          const cardTitle = truncateCalendarTitle(e.show_title, 60);

          return `<div class="calendar-card status-${e.status}" onclick="openCalendarEventModal('${eKey}')">
            <div class="cal-card-poster" ${posterStyle}>
              ${!e.poster_url ? `<i data-lucide="${isMovie ? 'film' : (isAnime ? 'tv-2' : 'tv')}" class="cal-card-no-poster-ico"></i>` : ''}
            </div>
            <div class="cal-card-body">
              <div class="cal-card-header">
                <div class="cal-card-title" title="${escapeHtml(e.show_title)}">${escapeHtml(cardTitle)} ${e.year ? `<span class="cal-card-year">(${e.year})</span>` : ''}</div>
                <div class="cal-card-badges">
                  ${movieBadge}
                  ${iconHtml ? `<span class="cal-badge-finale" title="${isPremiere ? t('calendar.premiere') : (isSeriesFinale ? t('calendar.series_finale') : t('calendar.season_finale'))}">${iconHtml}</span>` : ""}
                </div>
              </div>
              <div class="cal-card-subtitle">
                ${epCode ? `<span class="cal-ep-pill">${epCode}</span>` : ''}
                <span class="cal-ep-name">${epName}</span>
              </div>
              <div class="cal-card-footer">
                ${timeStr ? `
                  <span class="cal-card-time">
                    <i data-lucide="clock" class="cal-ico-time"></i> ${timeStr}
                  </span>
                ` : ''}
                <span class="badge ${catClass}" style="font-size: 10px; padding: 1px 5px;">${catName}</span>
                <span class="status-pill status-${e.status}" style="margin-left:auto;">${escapeHtml(calStatusLabel(e.status))}</span>
              </div>
            </div>
            <div class="cal-card-actions" onclick="event.stopPropagation()">
              ${canManageLib ? `
                <button class="cal-btn-action" title="${t('calendar.btn_auto_search')}" onclick="triggerAutoSearchForCalEvent(${e.show_id}, ${e.episode_id ?? 'null'})">
                  <i data-lucide="zap"></i>
                </button>
                <button class="cal-btn-action" title="${t('calendar.btn_manual_search')}" onclick="openInteractiveSearch(${e.show_id}, ${e.season ?? 'null'}, ${e.episode ?? 'null'})">
                  <i data-lucide="search"></i>
                </button>
                <button class="cal-btn-action" title="${t('calendar.btn_edit_date')}" onclick="promptEditCalendarDate(${e.episode_id ?? 'null'}, ${e.show_id}, '${escapeHtml(e.show_title || '').replace(/'/g, "\\'")}')">
                  <i data-lucide="edit-2"></i>
                </button>
              ` : `
                <button class="cal-btn-action" title="${t('calendar.btn_open_card')}" onclick="openShowModal(${e.show_id})">
                  <i data-lucide="external-link"></i>
                </button>
              `}
            </div>
          </div>`;
        }).join("")
      : `<p class="hint" style="margin:0 0 4px; padding: 6px 10px; font-size:12px;">${t("calendar.no_releases_day")}</p>`;

    return `<div class="calendar-day-group">
      <div class="calendar-day-header ${isToday ? 'is-today' : ''}">
        <div class="cal-day-title-wrap">
          <span class="cal-day-date">${calFormatDateFull(dateObj)}</span>
          ${relBadge}
        </div>
        ${countLabel ? `<span class="cal-day-count">${countLabel}</span>` : ''}
      </div>
      <div class="calendar-day-cards">
        ${cardsHtml}
      </div>
    </div>`;
  }).join("")}</div>`;
}



async function loadHistory() {
  const tbody = document.querySelector("#history-table tbody");
  try {
    const entries = await api("/api/v1/history");
    tbody.innerHTML = entries.map(e => `
      <tr>
        <td class="mono col-time" style="font-size:11.5px; white-space:nowrap;">${formatDateTZ(e.created_at)}</td>
        <td>
          ${escapeHtml(e.show_title)}
          ${e.matched_alias ? `<div class="hint">${CURRENT_LANG === "en" ? "by alias" : "по алиасу"} «${escapeHtml(e.matched_alias)}»</div>` : ""}
        </td>
        <td class="mono" style="max-width:320px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(e.release_title)}</td>
        <td>${escapeHtml(t("history.event." + e.event_type) !== "history.event." + e.event_type ? t("history.event." + e.event_type) : e.event_type)}</td>
      </tr>`).join("") || `<tr><td colspan="4" style="color:var(--text-muted)">${t("history.empty")}</td></tr>`;
  } catch (e) {}
}

// =============================================================================
// SETTINGS: GENERAL
// =============================================================================

function updateMinSeedsAvailability() {
  const prefer = document.getElementById("setting-prefer-seeded").checked;
  const minSeedsInput = document.getElementById("setting-min-seeds");
  minSeedsInput.disabled = prefer;
  minSeedsInput.classList.toggle("input-disabled-dim", prefer);
}

async function loadGeneralSettings() {
  try {
    const s = await api("/api/v1/settings");
    const keyInp = document.getElementById("setting-apikey");
    if (keyInp) keyInp.value = s.api_key || "";

    document.getElementById("setting-language").value = s.language || "ru";
    document.getElementById("setting-theme").value = s.theme || "dark";
    document.getElementById("setting-timezone").value = s.timezone || "UTC";
    APP_TIMEZONE = s.timezone || "UTC";
    localStorage.setItem("vbeacon_timezone", APP_TIMEZONE);

    document.getElementById("setting-root-movies").value = s.root_folder_movies || "";
    document.getElementById("setting-root-series").value = s.root_folder_series || "";
    document.getElementById("setting-root-anime").value = s.root_folder_anime || "";
    document.getElementById("setting-download-movies").value = s.download_folder_movies || "";
    document.getElementById("setting-download-series").value = s.download_folder_series || "";
    document.getElementById("setting-download-anime").value = s.download_folder_anime || "";
    document.getElementById("setting-template-movie").value = s.rename_template_movie || "";
    document.getElementById("setting-template-series").value = s.rename_template_series || "";
    document.getElementById("setting-template-anime").value = s.rename_template_anime || "";

    const sfSeries = document.getElementById("setting-season-folder-series");
    if (sfSeries) sfSeries.value = s.season_folder_template_series || "Сезон {season}";
    const sfAnime = document.getElementById("setting-season-folder-anime");
    if (sfAnime) sfAnime.value = s.season_folder_template_anime || "Сезон {season}";

    const importExtraCb = document.getElementById("setting-import-extra-files");
    if (importExtraCb) importExtraCb.checked = s.import_extra_files !== false;
    const extraExtsInp = document.getElementById("setting-extra-file-extensions");
    if (extraExtsInp) extraExtsInp.value = s.extra_file_extensions || "srt, ass, sub, idx, vtt, nfo, mka, ttf, otf, woff";

    document.getElementById("setting-min-seeds").value = s.min_seeds ?? 0;
    document.getElementById("setting-prefer-seeded").checked = !!s.prefer_most_seeded;
    updateMinSeedsAvailability();
    document.getElementById("setting-monitor-interval").value = s.monitor_interval_minutes ?? 15;
    document.getElementById("setting-download-check-interval").value = s.download_check_interval_seconds ?? (s.download_check_interval_minutes ? s.download_check_interval_minutes * 60 : 30);
    const trackerEl = document.getElementById("setting-tracker-interval");
    if (trackerEl) trackerEl.value = s.tracker_check_interval_minutes ?? 30;
    const unairedEl = document.getElementById("setting-unaired-interval");
    if (unairedEl) unairedEl.value = s.unaired_check_interval_minutes ?? 10;

    applyTheme(s.theme || "dark");
    applyLanguage(s.language || "ru");

    const hintEl = document.getElementById("apikey-source-hint");
    const regenBtn = document.getElementById("regenerate-key-btn");
    if (s.api_key_source === "env") {
      if (hintEl) hintEl.textContent = t("settings.apikey_source_env");
      if (regenBtn) regenBtn.disabled = true;
    } else {
      if (hintEl) hintEl.textContent = t("settings.apikey_source_auto");
      if (regenBtn) regenBtn.disabled = false;
    }
  } catch (e) {}

  try {
    const authStatus = await fetch("/api/v1/auth/status").then(r => r.json());
    document.getElementById("security-login-enabled").checked = authStatus.login_required;
    document.getElementById("security-username").value = authStatus.username || "admin";
  } catch (e) {}
}

async function saveInterfaceSettings(btn) {
  await withLoading(btn, async () => {
    try {
      const language = document.getElementById("setting-language").value;
      const theme = document.getElementById("setting-theme").value;
      const timezone = document.getElementById("setting-timezone").value;
      await api("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({
          language,
          theme,
          timezone,
        }),
      });
      applyTheme(theme);
      applyLanguage(language);
      APP_TIMEZONE = timezone;
      localStorage.setItem("vbeacon_timezone", APP_TIMEZONE);
      refreshActiveTab();
      toast(t("settings.toast_saved"));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

async function saveFolderSettings(btn) {
  await withLoading(btn, async () => {
    try {
      const body = {
        root_folder_movies: document.getElementById("setting-root-movies").value,
        root_folder_series: document.getElementById("setting-root-series").value,
        root_folder_anime: document.getElementById("setting-root-anime").value,
        download_folder_movies: document.getElementById("setting-download-movies").value,
        download_folder_series: document.getElementById("setting-download-series").value,
        download_folder_anime: document.getElementById("setting-download-anime").value,
        rename_template_movie: document.getElementById("setting-template-movie").value,
        rename_template_series: document.getElementById("setting-template-series").value,
        rename_template_anime: document.getElementById("setting-template-anime").value,
        season_folder_template_series: document.getElementById("setting-season-folder-series")?.value ?? "Сезон {season}",
        season_folder_template_anime: document.getElementById("setting-season-folder-anime")?.value ?? "Сезон {season}",
      };
      const extraCb = document.getElementById("setting-import-extra-files");
      if (extraCb) body.import_extra_files = extraCb.checked;
      const extraExts = document.getElementById("setting-extra-file-extensions");
      if (extraExts) body.extra_file_extensions = extraExts.value;

      await api("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      toast(t("settings.toast_saved"));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

async function saveExtraFilesSettings(btn) {
  await withLoading(btn, async () => {
    try {
      await api("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({
          import_extra_files: document.getElementById("setting-import-extra-files").checked,
          extra_file_extensions: document.getElementById("setting-extra-file-extensions").value,
        }),
      });
      toast(t("settings.toast_saved"));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

async function saveAutoSearchSettings(btn) {
  await withLoading(btn, async () => {
    try {
      const dlSec = Number(document.getElementById("setting-download-check-interval").value) || 30;
      await api("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({
          min_seeds: Number(document.getElementById("setting-min-seeds").value) || 0,
          prefer_most_seeded: document.getElementById("setting-prefer-seeded").checked,
          monitor_interval_minutes: Number(document.getElementById("setting-monitor-interval").value) || 15,
          download_check_interval_seconds: dlSec,
          download_check_interval_minutes: Math.max(1, Math.round(dlSec / 60)),
          tracker_check_interval_minutes: Number(document.getElementById("setting-tracker-interval")?.value) || 30,
          unaired_check_interval_minutes: Number(document.getElementById("setting-unaired-interval")?.value) || 10,
        }),
      });
      toast(t("settings.toast_saved"));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

async function saveGeneralSettings() {
  await saveInterfaceSettings();
  await saveFolderSettings();
  await saveAutoSearchSettings();
}

async function regenerateApiKey(button) {
  const confirmed = await confirmModal(
    t("settings.confirm_regenerate_key"),
    { danger: false }
  );
  if (!confirmed) return;
  await withLoading(button, async () => {
    try {
      const s = await api("/api/v1/settings/regenerate-api-key", { method: "POST" });
      document.getElementById("setting-apikey").value = s.api_key;
      API_KEY = s.api_key;
      localStorage.setItem("aliasarr_api_key", API_KEY);
      toast(t("settings.toast_key_regenerated"));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

// =============================================================================
// СПРАВОЧНИК ШАБЛОНОВ ПЕРЕИМЕНОВАНИЯ (SONARR СТИЛЬ)
// =============================================================================

const SONARR_TEMPLATES_DATA = {
  series: {
    defaultTemplate: "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
    presets: [
      {
        template: "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
        preview: "The Series Title's! - S01E01 - Episode Title WEBDL-1080p Proper",
        desc: "Стандартный формат по умолчанию"
      },
      {
        template: "{Series TitleYear} - S{season:00}E{episode:00} - {Episode CleanTitle} {Quality Full}",
        preview: "The Series Title's! (2010) - S01E01 - Episode Title WEBDL-1080p Proper",
        desc: "С годом выпуска и очищенным названием серии"
      },
      {
        template: "{Series TitleYear} - {season:0}x{episode:00} - {Episode CleanTitle} {Quality Full}",
        preview: "The Series Title's! (2010) - 1x01 - Episode Title WEBDL-1080p Proper",
        desc: "Формат сезона и серии 1x01"
      },
      {
        template: "{Series.CleanTitleYear}.S{season:00}E{episode:00}.{Episode.CleanTitle}.{Quality.Full}",
        preview: "The.Series.Title's!.2010.S01E01.Episode.Title.WEBDL-1080p.Proper",
        desc: "Точечный формат (dot-separated)"
      }
    ],
    sections: [
      {
        title: "Сериалы",
        note: "При необходимости можно управлять обрезкой до максимального количества символов, включая многоточие (...). Поддерживается обрезка как с конца (например, {Series Title:30}), так и с начала (например, {Series Title:-30}).",
        tokens: [
          { token: "{Series Title}", example: "The Series Title's!" },
          { token: "{Series CleanTitle}", example: "The Series Titles!" },
          { token: "{Series TitleYear}", example: "The Series Title's! (2010)" },
          { token: "{Series CleanTitleYear}", example: "The Series Titles! 2010" },
          { token: "{Series TitleWithoutYear}", example: "The Series Title's!" },
          { token: "{Series CleanTitleWithoutYear}", example: "The Series Titles!" },
          { token: "{Series TitleThe}", example: "Series Title's!, The" },
          { token: "{Series CleanTitleThe}", example: "Series Titles!, The" },
          { token: "{Series TitleTheYear}", example: "Series Title's!, The (2010)" },
          { token: "{Series CleanTitleTheYear}", example: "Series Titles!, The 2010" },
          { token: "{Series TitleTheWithoutYear}", example: "Series Title's!, The" },
          { token: "{Series CleanTitleTheWithoutYear}", example: "Series Titles!, The" },
          { token: "{Series TitleFirstCharacter}", example: "T" },
          { token: "{Series Year}", example: "2010" }
        ]
      },
      {
        title: "Идентификатор сериала",
        tokens: [
          { token: "{ImdbId}", example: "tt12345" },
          { token: "{TvdbId}", example: "12345" },
          { token: "{TmdbId}", example: "11223" },
          { token: "{TvMazeId}", example: "54321" }
        ]
      },
      {
        title: "Папка сезона (Сериалы / Аниме)",
        note: "Используется для формирования имени папки сезона внутри тайтла.",
        tokens: [
          { token: "Сезон {season}", example: "Сезон 1" },
          { token: "Сезон {season:00}", example: "Сезон 01" },
          { token: "Season {season}", example: "Season 1" },
          { token: "Season {season:00}", example: "Season 01" },
          { token: "S{season:00}", example: "S01" },
          { token: "S{season}", example: "S1" }
        ]
      },
      {
        title: "Сезон и Эпизод",
        tokens: [
          { token: "{season:0}", example: "1" },
          { token: "{season:00}", example: "01" },
          { token: "{episode:0}", example: "1" },
          { token: "{episode:00}", example: "01" }
        ]
      },
      {
        title: "Дата выхода в эфир",
        tokens: [
          { token: "{Air-Date}", example: "2016-03-20" },
          { token: "{Air Date}", example: "2016 03 20" }
        ]
      },
      {
        title: "Название эпизода",
        note: "При необходимости можно управлять усечением до максимального количества символов, включая многоточие (...) (например, {Episode Title:30} или {Episode Title:-30}).",
        tokens: [
          { token: "{Episode Title}", example: "Episode's Title" },
          { token: "{Episode CleanTitle}", example: "Episodes Title" }
        ]
      },
      {
        title: "Качество",
        tokens: [
          { token: "{Quality Full}", example: "WEBDL-1080p Proper" },
          { token: "{Quality Title}", example: "WEBDL-1080p" }
        ]
      },
      {
        title: "Медиа данные",
        note: "MediaInfo Full/AudioLanguages/SubtitleLanguages поддерживает суффикс :EN+DE, позволяющий фильтровать языки, включенные в имя файла. Используйте -DE, чтобы исключить определенные языки. Например {MediaInfo Full:EN+DE}.",
        tokens: [
          { token: "{MediaInfo Simple}", example: "x264 DTS" },
          { token: "{MediaInfo Full}", example: "x264 DTS [EN+DE]" },
          { token: "{MediaInfo AudioCodec}", example: "DTS" },
          { token: "{MediaInfo AudioChannels}", example: "5.1" },
          { token: "{MediaInfo AudioLanguages}", example: "[EN+DE]" },
          { token: "{MediaInfo SubtitleLanguages}", example: "[DE]" },
          { token: "{MediaInfo VideoCodec}", example: "x264" },
          { token: "{MediaInfo VideoBitDepth}", example: "10" },
          { token: "{MediaInfo VideoDynamicRange}", example: "HDR" },
          { token: "{MediaInfo VideoDynamicRangeType}", example: "DV HDR10" }
        ]
      },
      {
        title: "Другое",
        tokens: [
          { token: "{Release Group}", example: "Rls Grp" },
          { token: "{Custom Formats}", example: "iNTERNAL" },
          { token: "{Custom Format:FormatName}", example: "AMZN" }
        ]
      },
      {
        title: "Оригинал",
        tokens: [
          { token: "{Original Title}", example: "The.Series.Title's!.S01E01.WEBDL.1080p.x264-EVOLVE" },
          { token: "{Original Filename}", example: "the.series.title's!.s01e01.webdl.1080p.x264-evolve" }
        ]
      }
    ]
  },
  anime: {
    defaultTemplate: "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
    presets: [
      {
        template: "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
        preview: "The Series Title's! - S01E01 - Episode Title WEBDL-1080p Proper",
        desc: "Стандартный формат по умолчанию"
      },
      {
        template: "{Series TitleYear} - S{season:00}E{episode:00} - {absolute:000} - {Episode CleanTitle} {Quality Full}",
        preview: "The Series Title's! (2010) - S01E01 - 001 - Episode Title WEBDL-1080p Proper",
        desc: "С сезоном, абсолютным номером и качеством"
      },
      {
        template: "{Series TitleYear} - {season:0}x{episode:00} - {absolute:000} - {Episode CleanTitle} {Quality Full}",
        preview: "The Series Title's! (2010) - 1x01 - 001 - Episode Title WEBDL-1080p Proper",
        desc: "Формат 1x01 с абсолютным номером 001"
      },
      {
        template: "{Series.CleanTitleYear}.S{season:00}E{episode:00}.{absolute:000}.{Episode.CleanTitle}.{Quality.Full}",
        preview: "The.Series.Title's!.2010.S01E01.001.Episode.Title.WEBDL-1080p.Proper",
        desc: "Точечный формат аниме"
      },
      {
        template: "{Series Title} - {absolute:00} ({Quality Title})",
        preview: "The Series Title's! - 01 (WEBDL-1080p)",
        desc: "Компактный формат (только абсолютный номер)"
      }
    ],
    sections: [
      {
        title: "Абсолютный номер эпизода (Аниме)",
        tokens: [
          { token: "{absolute:0}", example: "1" },
          { token: "{absolute:00}", example: "01" },
          { token: "{absolute:000}", example: "001" }
        ]
      },
      {
        title: "Сериалы / Аниме",
        note: "При необходимости можно управлять обрезкой до максимального количества символов (например, {Series Title:30} или {Series Title:-30}).",
        tokens: [
          { token: "{Series Title}", example: "The Series Title's!" },
          { token: "{Series CleanTitle}", example: "The Series Titles!" },
          { token: "{Series TitleYear}", example: "The Series Title's! (2010)" },
          { token: "{Series CleanTitleYear}", example: "The Series Titles! 2010" },
          { token: "{Series TitleWithoutYear}", example: "The Series Title's!" },
          { token: "{Series CleanTitleWithoutYear}", example: "The Series Titles!" },
          { token: "{Series TitleThe}", example: "Series Title's!, The" },
          { token: "{Series CleanTitleThe}", example: "Series Titles!, The" },
          { token: "{Series TitleTheYear}", example: "Series Title's!, The (2010)" },
          { token: "{Series CleanTitleTheYear}", example: "Series Titles!, The 2010" },
          { token: "{Series TitleTheWithoutYear}", example: "Series Title's!, The" },
          { token: "{Series CleanTitleTheWithoutYear}", example: "Series Titles!, The" },
          { token: "{Series TitleFirstCharacter}", example: "T" },
          { token: "{Series Year}", example: "2010" }
        ]
      },
      {
        title: "Идентификатор",
        tokens: [
          { token: "{ImdbId}", example: "tt12345" },
          { token: "{TvdbId}", example: "12345" },
          { token: "{TmdbId}", example: "11223" },
          { token: "{TvMazeId}", example: "54321" }
        ]
      },
      {
        title: "Сезон и Эпизод",
        tokens: [
          { token: "{season:0}", example: "1" },
          { token: "{season:00}", example: "01" },
          { token: "{episode:0}", example: "1" },
          { token: "{episode:00}", example: "01" }
        ]
      },
      {
        title: "Дата выхода в эфир",
        tokens: [
          { token: "{Air-Date}", example: "2016-03-20" },
          { token: "{Air Date}", example: "2016 03 20" }
        ]
      },
      {
        title: "Название эпизода",
        tokens: [
          { token: "{Episode Title}", example: "Episode's Title" },
          { token: "{Episode CleanTitle}", example: "Episodes Title" }
        ]
      },
      {
        title: "Качество",
        tokens: [
          { token: "{Quality Full}", example: "WEBDL-1080p Proper" },
          { token: "{Quality Title}", example: "WEBDL-1080p" }
        ]
      },
      {
        title: "Медиа данные",
        tokens: [
          { token: "{MediaInfo Simple}", example: "x264 DTS" },
          { token: "{MediaInfo Full}", example: "x264 DTS [EN+DE]" },
          { token: "{MediaInfo AudioCodec}", example: "DTS" },
          { token: "{MediaInfo AudioChannels}", example: "5.1" },
          { token: "{MediaInfo AudioLanguages}", example: "[EN+DE]" },
          { token: "{MediaInfo SubtitleLanguages}", example: "[DE]" },
          { token: "{MediaInfo VideoCodec}", example: "x264" },
          { token: "{MediaInfo VideoBitDepth}", example: "10" },
          { token: "{MediaInfo VideoDynamicRange}", example: "HDR" },
          { token: "{MediaInfo VideoDynamicRangeType}", example: "DV HDR10" }
        ]
      },
      {
        title: "Другое и Оригинал",
        tokens: [
          { token: "{Release Group}", example: "Rls Grp" },
          { token: "{Custom Formats}", example: "iNTERNAL" },
          { token: "{Custom Format:FormatName}", example: "AMZN" },
          { token: "{Release Hash}", example: "ABCDEFGH" },
          { token: "{Original Title}", example: "The.Series.Title's!.S01E01.WEBDL.1080p.x264-EVOLVE" },
          { token: "{Original Filename}", example: "the.series.title's!.s01e01.webdl.1080p.x264-evolve" }
        ]
      }
    ]
  },
  movie: {
    defaultTemplate: "{Movie Title} ({Release Year}) {Quality Full}",
    presets: [
      {
        template: "{Movie Title} ({Release Year}) {Quality Full}",
        preview: "The Movie Title (2010) Bluray-1080p Proper",
        desc: "Стандартный формат по умолчанию (Название_фильма (год) качество)"
      },
      {
        template: "{Movie CleanTitleYear} {Quality Full}",
        preview: "The Movie Title 2010 Bluray-1080p Proper",
        desc: "Без скобок"
      },
      {
        template: "{Movie.CleanTitleYear}.{Quality.Full}",
        preview: "The.Movie.Title.2010.Bluray-1080p.Proper",
        desc: "Точечный формат фильма (dot-separated)"
      }
    ],
    sections: [
      {
        title: "Фильмы",
        tokens: [
          { token: "{Movie Title}", example: "The Movie Title" },
          { token: "{Movie CleanTitle}", example: "The Movie Title" },
          { token: "{Movie TitleYear}", example: "The Movie Title (2010)" },
          { token: "{Movie CleanTitleYear}", example: "The Movie Title 2010" },
          { token: "{Release Year}", example: "2010" },
          { token: "{Quality Full}", example: "Bluray-1080p Proper" },
          { token: "{Quality Title}", example: "Bluray-1080p" }
        ]
      },
      {
        title: "Идентификаторы и Медиа данные",
        tokens: [
          { token: "{ImdbId}", example: "tt12345" },
          { token: "{TmdbId}", example: "11223" },
          { token: "{MediaInfo Simple}", example: "x264 DTS" },
          { token: "{MediaInfo Full}", example: "x264 DTS [EN+RU]" },
          { token: "{Original Title}", example: "The.Movie.Title.2010.1080p.BluRay.x264-EVOLVE" },
          { token: "{Original Filename}", example: "the.movie.title.2010.1080p.bluray.x264-evolve" }
        ]
      }
    ]
  }
};

const DEFAULT_TEMPLATES = {
  series: SONARR_TEMPLATES_DATA.series.defaultTemplate,
  anime: SONARR_TEMPLATES_DATA.anime.defaultTemplate,
  movie: SONARR_TEMPLATES_DATA.movie.defaultTemplate,
};

let TEMPLATES_HELP_CURRENT_CAT = "series";

function openTemplatesHelpModal() {
  switchTemplatesHelpTab(TEMPLATES_HELP_CURRENT_CAT);
  openModal("templates-help-modal");
}

function onTemplatesHelpTargetChange() {
  const targetId = document.getElementById("templates-help-target").value;
  const input = document.getElementById(targetId);
  const editor = document.getElementById("templates-help-editor");
  if (editor) editor.value = input ? input.value : "";
  renderTemplatesHelpPreview();
}

function onTemplatesHelpEditorInput() {
  const targetId = document.getElementById("templates-help-target").value;
  const input = document.getElementById(targetId);
  const editor = document.getElementById("templates-help-editor");
  if (input && editor) input.value = editor.value;
  renderTemplatesHelpPreview();
}

function switchTemplatesHelpTab(cat) {
  TEMPLATES_HELP_CURRENT_CAT = cat;
  document.querySelectorAll("#templates-help-tabs .template-cat-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.cat === cat);
  });

  const targetSelect = document.getElementById("templates-help-target");
  const defaultTargetByCat = {
    series: "setting-template-series",
    anime: "setting-template-anime",
    movie: "setting-template-movie",
  };
  if (targetSelect) targetSelect.value = defaultTargetByCat[cat];
  onTemplatesHelpTargetChange();

  const data = SONARR_TEMPLATES_DATA[cat] || SONARR_TEMPLATES_DATA.series;
  const body = document.getElementById("templates-help-body");
  if (body) {
    let html = "";

    const TPL_DESC_EN = {
      "Стандартный формат по умолчанию": "Default standard format",
      "С сезоном, абсолютным номером и качеством": "With season, absolute number and quality",
      "Формат 1x01 с абсолютным номером 001": "1x01 format with absolute number 001",
      "Точечный формат аниме": "Dot-separated anime format",
      "Компактный формат (только абсолютный номер)": "Compact format (absolute number only)",
      "Стандартный формат по умолчанию (Название_фильма (год) качество)": "Default standard format (Movie_Title (year) quality)",
      "Без скобок": "Without brackets",
      "Точечный формат фильма (dot-separated)": "Dot-separated movie format",
    };

    const TPL_TITLE_EN = {
      "Сериалы": "Series",
      "Сериалы / Аниме": "Series / Anime",
      "Фильмы": "Movies",
      "Абсолютный номер эпизода (Аниме)": "Absolute Episode Number (Anime)",
      "Идентификатор": "Identifiers",
      "Идентификаторы и Медиа данные": "Identifiers and Media Info",
      "Сезон и Эпизод": "Season and Episode",
      "Дата выхода в эфир": "Air Date",
      "Название эпизода": "Episode Title",
      "Качество": "Quality",
      "Медиа данные": "Media Info",
      "Другое": "Other",
      "Другое и Оригинал": "Other and Original",
      "Оригинал": "Original",
    };

    const isEn = CURRENT_LANG === "en";

    // Presets
    if (data.presets && data.presets.length > 0) {
      html += `
        <div class="template-section">
          <div class="template-section-title">${isEn ? "Preset formats (click to apply)" : "Готовые форматы (кликните для применения)"}</div>
          <div class="template-presets-grid">
            ${data.presets.map(p => `
              <div class="template-preset-btn" onclick="applyTemplatePreset('${escapeHtml(p.template).replace(/'/g, "\\'")}')">
                <div class="template-preset-code">${escapeHtml(p.template)}</div>
                <div class="template-preset-desc">${escapeHtml(isEn ? (TPL_DESC_EN[p.desc] || p.desc) : p.desc)}: <span style="font-family:var(--font-mono); color:var(--text);">${escapeHtml(p.preview)}</span></div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    // Sections & Tokens
    if (data.sections && data.sections.length > 0) {
      data.sections.forEach(sec => {
        const secTitle = isEn ? (TPL_TITLE_EN[sec.title] || sec.title) : sec.title;
        let secNote = sec.note || "";
        if (isEn && secNote) {
          secNote = secNote
            .replace("При необходимости можно управлять обрезкой до максимального количества символов (например, {Series Title:30} или {Series Title:-30}).", "Truncation can be controlled by character limit (e.g. {Series Title:30} or {Series Title:-30}).")
            .replace("MediaInfo Full/AudioLanguages/SubtitleLanguages поддерживает суффикс :EN+DE, позволяющий фильтровать языки, включенные в имя файла. Используйте -DE, чтобы исключить определенные языки. Например {MediaInfo Full:EN+DE}.", "MediaInfo Full/AudioLanguages/SubtitleLanguages supports :EN+DE suffix to filter languages in filename. Use -DE to exclude languages, e.g. {MediaInfo Full:EN+DE}.");
        }
        html += `
          <div class="template-section">
            <div class="template-section-title">${escapeHtml(secTitle)}</div>
            ${secNote ? `<div class="template-token-note">${escapeHtml(secNote)}</div>` : ''}
            <table class="template-tokens-table">
              <tbody>
                ${sec.tokens.map(t => `
                  <tr onclick="insertTemplatePlaceholder('${t.token.replace(/'/g, "\\'")}')" title="${isEn ? "Insert " + escapeHtml(t.token) + " into editor" : "Вставить " + escapeHtml(t.token) + " в редактор"}">
                    <td style="width: 40%;"><span class="template-token-code">${escapeHtml(t.token)}</span></td>
                    <td style="width: 60%;"><span class="template-token-example">${escapeHtml(t.example)}</span></td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `;
      });
    }

    body.innerHTML = html;
  }

  const defaultEl = document.getElementById("templates-help-default");
  if (defaultEl) defaultEl.textContent = data.defaultTemplate || "";
  renderTemplatesHelpPreview();
}

function applyTemplatePreset(tpl) {
  const editor = document.getElementById("templates-help-editor");
  if (editor) {
    editor.value = tpl;
    onTemplatesHelpEditorInput();
  }
  toast(t("settings.toast_template_applied"));
}

function copyDefaultTemplateToField() {
  const cat = TEMPLATES_HELP_CURRENT_CAT;
  const editor = document.getElementById("templates-help-editor");
  const data = SONARR_TEMPLATES_DATA[cat] || SONARR_TEMPLATES_DATA.series;
  if (editor) {
    editor.value = data.defaultTemplate || "";
    onTemplatesHelpEditorInput();
  }
  toast(t("settings.toast_default_template_inserted"));
}

function insertTemplatePlaceholder(placeholder) {
  const editor = document.getElementById("templates-help-editor");
  if (!editor) return;
  const start = editor.selectionStart ?? editor.value.length;
  const end = editor.selectionEnd ?? editor.value.length;
  editor.value = editor.value.slice(0, start) + placeholder + editor.value.slice(end);
  const newPos = start + placeholder.length;
  editor.focus();
  editor.setSelectionRange(newPos, newPos);
  onTemplatesHelpEditorInput();
}

function formatSonarrTemplatePreview(template, cat) {
  if (!template || !template.trim()) return "—";
  const isMovie = cat === "movie";

  return template.replace(/\{([^}]+)\}/g, (match, rawToken) => {
    let token = rawToken.trim();
    let maxLen = null;
    let fromStart = false;

    if (!/^(season|episode|absolute):\d+[a-z]?$/i.test(token)) {
      const mLen = token.match(/^(.+?):(-?\d+)$/);
      if (mLen) {
        token = mLen[1].trim();
        const num = parseInt(mLen[2], 10);
        maxLen = Math.abs(num);
        fromStart = num < 0;
      }
    }

    const norm = token.replace(/\./g, " ").trim().toLowerCase();
    let val = "";

    if (norm === "series title" || norm === "show_title" || norm === "movie title") {
      val = isMovie ? "The Movie Title" : "The Series Title's!";
    } else if (norm === "series cleantitle" || norm === "movie cleantitle") {
      val = isMovie ? "The Movie Title" : "The Series Titles!";
    } else if (norm === "series titleyear" || norm === "movie titleyear") {
      val = isMovie ? "The Movie Title (2010)" : "The Series Title's! (2010)";
    } else if (norm === "series cleantitleyear" || norm === "movie cleantitleyear") {
      val = isMovie ? "The Movie Title 2010" : "The Series Titles! 2010";
    } else if (norm === "series titlewithoutyear") {
      val = "The Series Title's!";
    } else if (norm === "series cleantitlewithoutyear") {
      val = "The Series Titles!";
    } else if (norm === "series titlethe") {
      val = "Series Title's!, The";
    } else if (norm === "series cleantitlethe") {
      val = "Series Titles!, The";
    } else if (norm === "series titletheyear") {
      val = "Series Title's!, The (2010)";
    } else if (norm === "series cleantitletheyear") {
      val = "Series Titles!, The 2010";
    } else if (norm === "series titlethewithoutyear") {
      val = "Series Title's!, The";
    } else if (norm === "series cleantitlethewithoutyear") {
      val = "Series Titles!, The";
    } else if (norm === "series titlefirstcharacter") {
      val = "T";
    } else if (norm === "series year" || norm === "release year" || norm === "year") {
      val = "2010";
    } else if (norm === "imdbid") {
      val = "tt12345";
    } else if (norm === "tvdbid") {
      val = "12345";
    } else if (norm === "tmdbid") {
      val = "11223";
    } else if (norm === "tvmazeid") {
      val = "54321";
    } else if (norm === "season:0" || norm === "season") {
      val = "1";
    } else if (norm === "season:00" || norm === "season:02d") {
      val = "01";
    } else if (norm === "episode:0" || norm === "episode") {
      val = "1";
    } else if (norm === "episode:00" || norm === "episode:02d") {
      val = "01";
    } else if (norm === "absolute:0" || norm === "absolute") {
      val = "1";
    } else if (norm === "absolute:00") {
      val = "01";
    } else if (norm === "absolute:000" || norm === "absolute:03d") {
      val = "001";
    } else if (norm === "air-date") {
      val = "2016-03-20";
    } else if (norm === "air date") {
      val = "2016 03 20";
    } else if (norm === "episode title" || norm === "episode_title") {
      val = "Episode Title";
    } else if (norm === "episode cleantitle") {
      val = "Episodes Title";
    } else if (norm === "quality full") {
      val = isMovie ? "Bluray-1080p Proper" : "WEBDL-1080p Proper";
    } else if (norm === "quality title" || norm === "quality") {
      val = isMovie ? "Bluray-1080p" : "WEBDL-1080p";
    } else if (norm === "mediainfo simple") {
      val = "x264 DTS";
    } else if (norm === "mediainfo full") {
      val = "x264 DTS [EN+DE]";
    } else if (norm === "mediainfo audiocodec") {
      val = "DTS";
    } else if (norm === "mediainfo audiochannels") {
      val = "5.1";
    } else if (norm === "mediainfo audiolanguages") {
      val = "[EN+DE]";
    } else if (norm === "mediainfo subtitlelanguages") {
      val = "[DE]";
    } else if (norm === "mediainfo videocodec") {
      val = "x264";
    } else if (norm === "mediainfo videobitdepth") {
      val = "10";
    } else if (norm === "mediainfo videodynamicrange") {
      val = "HDR";
    } else if (norm === "mediainfo videodynamicrangetype") {
      val = "DV HDR10";
    } else if (norm === "release group") {
      val = "Rls Grp";
    } else if (norm === "custom formats") {
      val = "iNTERNAL";
    } else if (norm.startsWith("custom format:")) {
      val = "AMZN";
    } else if (norm === "release hash") {
      val = "ABCDEFGH";
    } else if (norm === "original title") {
      val = isMovie ? "The.Movie.Title.2010.1080p.BluRay.x264-EVOLVE" : "The.Series.Title's!.S01E01.WEBDL.1080p.x264-EVOLVE";
    } else if (norm === "original filename") {
      val = isMovie ? "the.movie.title.2010.1080p.bluray.x264-evolve" : "the.series.title's!.s01e01.webdl.1080p.x264-evolve";
    } else {
      return match;
    }

    if (maxLen !== null && val.length > maxLen) {
      val = fromStart
        ? (maxLen > 3 ? "..." + val.slice(-(maxLen - 3)) : val.slice(-maxLen))
        : (maxLen > 3 ? val.slice(0, maxLen - 3) + "..." : val.slice(0, maxLen));
    }

    return val;
  });
}

function renderTemplatesHelpPreview() {
  const targetId = document.getElementById("templates-help-target")?.value || "setting-template-series";
  const editor = document.getElementById("templates-help-editor");
  const previewEl = document.getElementById("templates-help-preview");
  if (!editor || !previewEl) return;

  const cat = targetId === "setting-template-movie" ? "movie" : (targetId === "setting-template-anime" ? "anime" : "series");

  try {
    previewEl.textContent = formatSonarrTemplatePreview(editor.value || "", cat) || "—";
  } catch (e) {
    previewEl.textContent = (CURRENT_LANG === "en" ? "Template error: " : "Ошибка в шаблоне: ") + e.message;
  }
}

// Пересчитываем превью при вводе в поля шаблонов и при смене активного поля справочника
document.addEventListener("DOMContentLoaded", () => {
  ["setting-template-series", "setting-template-anime", "setting-template-movie"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", renderTemplatesHelpPreview);
  });
  const targetSelect = document.getElementById("templates-help-target");
  if (targetSelect) targetSelect.addEventListener("change", renderTemplatesHelpPreview);
});

// =============================================================================
// SETTINGS: SECURITY & SESSION TIMEOUT
// =============================================================================

function toggleSecurityLocalAuthFields() {
  const loginEnabled = document.getElementById("security-login-enabled")?.checked;
  const wrap = document.getElementById("security-local-auth-wrap");
  const wrap2fa = document.getElementById("security-2fa-wrap");
  if (wrap) {
    wrap.style.display = loginEnabled ? "block" : "none";
  }
  if (wrap2fa) {
    wrap2fa.style.display = loginEnabled ? "block" : "none";
  }
}

function toggleSecurity2FAPolicy() {
  const is2fa = document.getElementById("security-2fa-enabled")?.checked;
  const policyWrap = document.getElementById("security-2fa-policy-wrap");
  if (policyWrap) {
    policyWrap.style.display = is2fa ? "block" : "none";
  }
}

async function loadSecuritySettings() {
  try {
    loadSslSettings();
    const [authStatus, settings, me] = await Promise.all([
      fetch("/api/v1/auth/status").then(r => r.json()),
      api("/api/v1/settings"),
      api("/api/v1/auth/me").catch(() => null),
    ]);
    const isOwner = CURRENT_USER ? !!CURRENT_USER.is_owner : true;
    const loginCb = document.getElementById("security-login-enabled");
    if (loginCb) {
      loginCb.checked = !!authStatus.auth_required || !!settings.login_enabled;
      loginCb.disabled = !isOwner;
    }

    const localAuthCb = document.getElementById("security-auth-disabled-for-local");
    if (localAuthCb) {
      localAuthCb.checked = authStatus.auth_disabled_for_local_addresses !== false && settings.auth_disabled_for_local_addresses !== false;
      localAuthCb.disabled = !isOwner;
    }

    const totp2faCb = document.getElementById("security-2fa-enabled");
    if (totp2faCb) {
      totp2faCb.checked = !!authStatus.totp_2fa_enabled || !!settings.totp_2fa_enabled;
      totp2faCb.disabled = !isOwner;
    }

    const totp2faPolicy = document.getElementById("security-2fa-policy");
    if (totp2faPolicy) {
      totp2faPolicy.value = authStatus.totp_2fa_policy || settings.totp_2fa_policy || "users_choice";
      totp2faPolicy.disabled = !isOwner;
    }

    const ipInfo = document.getElementById("security-current-ip-info");
    if (ipInfo && authStatus.client_ip) {
      const isLocal = !!authStatus.is_local;
      const badgeText = isLocal ? t("settings.local_ip_badge") : t("settings.remote_ip_badge");
      const badgeClass = isLocal ? "status-downloaded" : "status-wanted";
      ipInfo.innerHTML = `
        <span>${t("settings.current_ip")} <strong>${escapeHtml(authStatus.client_ip)}</strong></span>
        <span class="status-pill ${badgeClass}">${escapeHtml(badgeText)}</span>
      `;
    }

    toggleSecurityLocalAuthFields();
    toggleSecurity2FAPolicy();
    
    const userInp = document.getElementById("security-username");
    if (userInp) {
      userInp.value = authStatus.username || settings.username || "admin";
      userInp.disabled = !isOwner;
    }

    const dispInp = document.getElementById("security-display-name");
    if (dispInp) {
      dispInp.value = (me && isOwner ? me.display_name : "") || (CURRENT_USER ? CURRENT_USER.display_name : "") || "";
      dispInp.disabled = !isOwner;
    }
    
    const pwdInp = document.getElementById("security-password");
    if (pwdInp) {
      pwdInp.disabled = !isOwner;
      pwdInp.placeholder = isOwner ? t("settings.new_password_placeholder") : (CURRENT_LANG === "en" ? "Only master admin can change security settings" : "Только главный администратор может изменять параметры безопасности");
    }

    const saveBtn = document.getElementById("security-save-btn");
    if (saveBtn) saveBtn.disabled = !isOwner;
  } catch (e) {
    console.error("loadSecuritySettings error:", e);
  }
}

// =============================================================================
// SETTINGS: SSL / HTTPS (Self-signed auto-renewing certificate)
// =============================================================================

async function loadSslSettings() {
  const card = document.getElementById("card-ssl-settings");
  if (!card) return;
  try {
    const data = await api("/api/v1/settings/ssl");
    const enabledInput = document.getElementById("ssl-enabled");
    const portInput = document.getElementById("ssl-port");
    const autoRenewInput = document.getElementById("ssl-auto-renew");
    const statusBadge = document.getElementById("ssl-status-badge");
    const validToEl = document.getElementById("ssl-cert-valid-to");
    const daysLeftEl = document.getElementById("ssl-cert-days-left");
    const subjectEl = document.getElementById("ssl-cert-subject");
    const fpEl = document.getElementById("ssl-cert-fingerprint");

    if (enabledInput) enabledInput.checked = !!data.ssl_enabled;
    if (portInput) portInput.value = data.ssl_port || Number(window.location.port) || 8989;
    if (autoRenewInput) autoRenewInput.checked = true;

    if (statusBadge) {
      if (data.ssl_enabled) {
        statusBadge.className = "badge badge-success";
        statusBadge.textContent = "HTTPS (SSL on)";
      } else {
        statusBadge.className = "badge badge-secondary";
        statusBadge.textContent = "HTTP (SSL off)";
      }
    }

    const cert = data.cert_info || {};
    if (validToEl) {
      validToEl.textContent = cert.valid_to ? formatDateTZ(cert.valid_to) : (CURRENT_LANG === "en" ? "Not issued" : "Не выпущен");
    }
    if (daysLeftEl) {
      const days = cert.days_remaining != null ? cert.days_remaining : 0;
      daysLeftEl.textContent = `${days} ${CURRENT_LANG === "en" ? "days remaining" : "дней осталось"}`;
      daysLeftEl.style.color = days < 30 ? "var(--warning)" : "var(--text)";
    }
    if (subjectEl) {
      subjectEl.textContent = cert.subject || "aliasarr.local, localhost, 127.0.0.1";
    }
    if (fpEl) {
      fpEl.textContent = cert.fingerprint_sha256 || "—";
    }

    toggleSslFields();
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    console.error("loadSslSettings error:", e);
  }
}

function toggleSslFields() {
  const isEnabled = document.getElementById("ssl-enabled")?.checked;
  const detailsBox = document.getElementById("ssl-details-box");
  if (detailsBox) {
    detailsBox.style.opacity = isEnabled ? "1" : "0.75";
  }
}

let SSL_REDIRECT_TIMER = null;
let SSL_REDIRECT_URL = "";

function executeSslRedirect() {
  if (SSL_REDIRECT_TIMER) clearInterval(SSL_REDIRECT_TIMER);
  if (SSL_REDIRECT_URL) {
    window.location.href = SSL_REDIRECT_URL;
  }
}

async function saveSslSettings(btn) {
  const enabled = !!document.getElementById("ssl-enabled")?.checked;
  const detectedPort = Number(window.location.port) || Number(document.getElementById("ssl-port")?.value) || 8989;
  const port = detectedPort;
  const autoRenew = true;
  const currentProto = window.location.protocol; // "http:" or "https:"

  await withLoading(btn, async () => {
    try {
      const data = await api("/api/v1/settings/ssl", {
        method: "POST",
        body: JSON.stringify({
          ssl_enabled: enabled,
          ssl_port: port,
          ssl_auto_renew: true,
        }),
      });
      toast(t("settings.toast_ssl_saved"));
      await loadSslSettings();

      // Если пользователь включил SSL, находясь на HTTP:
      if (enabled && currentProto === "http:") {
        const targetHost = window.location.hostname;
        const targetPort = port;
        const targetUrl = targetPort === 443 ? `https://${targetHost}/` : `https://${targetHost}:${targetPort}/`;
        SSL_REDIRECT_URL = targetUrl;

        const titleEl = document.getElementById("ssl-redirect-title");
        const msgEl = document.getElementById("ssl-redirect-message");
        const linkEl = document.getElementById("ssl-redirect-link");
        const noticeEl = document.getElementById("ssl-redirect-notice");
        const btnTextEl = document.getElementById("ssl-redirect-btn-text");

        if (titleEl) titleEl.innerHTML = `<i data-lucide="shield-check" class="ico-sm" style="color:var(--teal);"></i> <span>${CURRENT_LANG === "en" ? "Switching to HTTPS (SSL)" : "Переход на HTTPS (SSL)"}</span>`;
        if (msgEl) msgEl.textContent = CURRENT_LANG === "en" 
          ? "HTTPS protocol has been activated. The web server is restarting with the SSL certificate and will switch to the secure connection:"
          : "Безопасный протокол HTTPS успешно активирован. Веб-сервер перезапускается с SSL-сертификатом и переходит на защищённое соединение:";
        if (linkEl) {
          linkEl.href = targetUrl;
          linkEl.textContent = targetUrl;
        }
        if (noticeEl) noticeEl.style.display = "block";

        let countdown = 5;
        if (btnTextEl) btnTextEl.textContent = `${CURRENT_LANG === "en" ? "Go to HTTPS" : "Перейти на HTTPS"} (${countdown}с)`;
        
        openModal("ssl-redirect-modal");
        if (window.lucide) lucide.createIcons();

        if (SSL_REDIRECT_TIMER) clearInterval(SSL_REDIRECT_TIMER);
        SSL_REDIRECT_TIMER = setInterval(() => {
          countdown -= 1;
          if (countdown <= 0) {
            clearInterval(SSL_REDIRECT_TIMER);
            executeSslRedirect();
          } else if (btnTextEl) {
            btnTextEl.textContent = `${CURRENT_LANG === "en" ? "Go to HTTPS" : "Перейти на HTTPS"} (${countdown}с)`;
          }
        }, 1000);
      }
      // Если пользователь выключил SSL, находясь на HTTPS:
      else if (!enabled && currentProto === "https:") {
        const targetHost = window.location.hostname;
        const targetPort = port;
        const targetUrl = targetPort === 80 ? `http://${targetHost}/` : `http://${targetHost}:${targetPort}/`;
        SSL_REDIRECT_URL = targetUrl;

        const titleEl = document.getElementById("ssl-redirect-title");
        const msgEl = document.getElementById("ssl-redirect-message");
        const linkEl = document.getElementById("ssl-redirect-link");
        const noticeEl = document.getElementById("ssl-redirect-notice");
        const btnTextEl = document.getElementById("ssl-redirect-btn-text");

        if (titleEl) titleEl.innerHTML = `<i data-lucide="shield-off" class="ico-sm" style="color:var(--text-muted);"></i> <span>${CURRENT_LANG === "en" ? "Switching to HTTP" : "Переход на HTTP"}</span>`;
        if (msgEl) msgEl.textContent = CURRENT_LANG === "en"
          ? "HTTPS protocol has been disabled. Switching back to HTTP connection:"
          : "HTTPS протокол отключён. Возврат на стандартное HTTP подключение:";
        if (linkEl) {
          linkEl.href = targetUrl;
          linkEl.textContent = targetUrl;
        }
        if (noticeEl) noticeEl.style.display = "none";

        let countdown = 4;
        if (btnTextEl) btnTextEl.textContent = `${CURRENT_LANG === "en" ? "Go to HTTP" : "Перейти на HTTP"} (${countdown}с)`;
        
        openModal("ssl-redirect-modal");
        if (window.lucide) lucide.createIcons();

        if (SSL_REDIRECT_TIMER) clearInterval(SSL_REDIRECT_TIMER);
        SSL_REDIRECT_TIMER = setInterval(() => {
          countdown -= 1;
          if (countdown <= 0) {
            clearInterval(SSL_REDIRECT_TIMER);
            executeSslRedirect();
          } else if (btnTextEl) {
            btnTextEl.textContent = `${CURRENT_LANG === "en" ? "Go to HTTP" : "Перейти на HTTP"} (${countdown}с)`;
          }
        }, 1000);
      }
    } catch (e) {
      toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
    }
  });
}

async function regenerateSslCert(btn) {
  const confirmed = await confirmModal(
    CURRENT_LANG === "en"
      ? "Regenerate self-signed SSL certificate for 100 years?"
      : "Перевыпустить самоподписанный SSL-сертификат на 100 лет?",
    { danger: false }
  );
  if (!confirmed) return;

  await withLoading(btn, async () => {
    try {
      const data = await api("/api/v1/settings/ssl/regenerate", { method: "POST" });
      toast(t("settings.toast_ssl_regenerated"));
      await loadSslSettings();
    } catch (e) {
      toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
    }
  });
}

async function saveSecuritySettings(btn) {
  const isOwner = CURRENT_USER ? !!CURRENT_USER.is_owner : true;
  if (!isOwner) {
    toast(CURRENT_LANG === "en" ? "Only master administrator can change security settings" : "Только главный администратор может изменять параметры безопасности", true);
    return;
  }
  const loginEnabled = document.getElementById("security-login-enabled").checked;
  const authDisabledForLocal = document.getElementById("security-auth-disabled-for-local")?.checked ?? true;
  const totp2faEnabled = document.getElementById("security-2fa-enabled")?.checked ?? false;
  const totp2faPolicy = document.getElementById("security-2fa-policy")?.value || "users_choice";
  const username = document.getElementById("security-username").value.trim() || "admin";
  const displayName = document.getElementById("security-display-name")?.value.trim();
  const password = document.getElementById("security-password").value;

  await withLoading(btn, async () => {
    try {
      const credResp = await api("/api/v1/auth/credentials", {
        method: "PUT",
        body: JSON.stringify({ 
          login_enabled: loginEnabled,
          auth_disabled_for_local_addresses: authDisabledForLocal,
          totp_2fa_enabled: totp2faEnabled,
          totp_2fa_policy: totp2faPolicy,
          username: username, 
          display_name: displayName,
          password: password ? password : null 
        }),
      });
      document.getElementById("security-password").value = "";
      if (CURRENT_USER) {
        if (credResp.username) CURRENT_USER.username = credResp.username;
        if (credResp.display_name) CURRENT_USER.display_name = credResp.display_name;
        updateUserProfileUI(CURRENT_USER);
      }
      toast(loginEnabled ? t("settings.toast_login_enabled") : t("settings.toast_security_saved"));
      await loadSecuritySettings();
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

// =============================================================================
// SETTINGS: USERS & RBAC
// =============================================================================

let EDITING_USER_ID = null;
let RESETTING_PASSWORD_USER_ID = null;

function toggleUserFormAdminMode() {
  const isAdmin = document.getElementById("user-form-is-admin")?.checked;
  const permsBox = document.getElementById("user-form-permissions-box");
  if (permsBox) {
    permsBox.style.opacity = isAdmin ? "0.5" : "1";
    permsBox.style.pointerEvents = isAdmin ? "none" : "auto";
  }
}

function resetUserForm() {
  EDITING_USER_ID = null;
  const titleEl = document.getElementById("user-form-title");
  if (titleEl) titleEl.textContent = t("users.add_title");
  
  const userInp = document.getElementById("user-form-username");
  if (userInp) { userInp.value = ""; userInp.disabled = false; }

  const dispInp = document.getElementById("user-form-display-name");
  if (dispInp) dispInp.value = "";

  const pwdInp = document.getElementById("user-form-password");
  if (pwdInp) pwdInp.value = "";

  const pwdWrap = document.getElementById("user-form-password-wrap");
  if (pwdWrap) pwdWrap.style.display = "flex";

  const timeoutSel = document.getElementById("user-form-session-timeout");
  if (timeoutSel) timeoutSel.value = "43200";

  const adminCb = document.getElementById("user-form-is-admin");
  if (adminCb) { adminCb.checked = false; adminCb.disabled = false; }

  document.querySelectorAll(".user-perm-check").forEach(cb => {
    cb.checked = true;
    cb.disabled = false;
  });
  toggleUserFormAdminMode();

  const permHint = document.getElementById("user-form-self-perm-hint");
  if (permHint) permHint.style.display = "none";

  const submitBtn = document.getElementById("user-form-submit-btn");
  if (submitBtn) submitBtn.textContent = t("common.add");

  const cancelBtn = document.getElementById("user-form-cancel-btn");
  if (cancelBtn) cancelBtn.style.display = "none";
}

function editUser(u) {
  EDITING_USER_ID = u.id;
  const titleEl = document.getElementById("user-form-title");
  if (titleEl) titleEl.textContent = t("users.edit_title", { name: u.display_name || u.username });

  const userInp = document.getElementById("user-form-username");
  if (userInp) { userInp.value = u.username; userInp.disabled = !!u.is_owner; }

  const dispInp = document.getElementById("user-form-display-name");
  if (dispInp) dispInp.value = u.display_name || "";

  const pwdWrap = document.getElementById("user-form-password-wrap");
  if (pwdWrap) pwdWrap.style.display = "none"; // Пароль меняется через отдельную кнопку

  const timeoutSel = document.getElementById("user-form-session-timeout");
  if (timeoutSel) timeoutSel.value = String(u.session_timeout_minutes || 43200);

  const isEditingSelf = CURRENT_USER && CURRENT_USER.id === u.id;
  const isOwner = CURRENT_USER && !!CURRENT_USER.is_owner;
  const blockPermissions = isEditingSelf && !isOwner;

  const adminCb = document.getElementById("user-form-is-admin");
  if (adminCb) {
    adminCb.checked = !!u.is_admin;
    adminCb.disabled = !!u.is_owner || blockPermissions;
  }

  const perms = u.permissions || {};
  document.querySelectorAll(".user-perm-check").forEach(cb => {
    cb.checked = u.is_admin || !!perms[cb.value];
    cb.disabled = blockPermissions;
  });
  toggleUserFormAdminMode();

  const permHint = document.getElementById("user-form-self-perm-hint");
  if (permHint) {
    if (blockPermissions) {
      permHint.textContent = CURRENT_LANG === "en"
        ? "You cannot modify your own permissions or admin role"
        : "Вы не можете изменять собственные права доступа и роль администратора";
      permHint.style.display = "block";
    } else {
      permHint.style.display = "none";
    }
  }

  const submitBtn = document.getElementById("user-form-submit-btn");
  if (submitBtn) submitBtn.textContent = t("common.save");

  const cancelBtn = document.getElementById("user-form-cancel-btn");
  if (cancelBtn) cancelBtn.style.display = "inline-block";
}

function copyTextToClipboard(text, msg) {
  if (!text) return;
  navigator.clipboard.writeText(text);
  toast(msg || t("settings.toast_key_copied"));
}

async function adminRegenerateUserApiKey(userId, username) {
  const confirmed = await confirmModal(
    CURRENT_LANG === "en"
      ? `Generate a new API key for user @${username}?`
      : `Сгенерировать новый API-ключ для пользователя @${username}?`
  );
  if (!confirmed) return;
  try {
    const res = await api(`/api/v1/users/${userId}/regenerate-api-key`, { method: "POST" });
    copyTextToClipboard(res.api_key, CURRENT_LANG === "en" ? "API key generated and copied to clipboard" : "API-ключ сгенерирован и скопирован в буфер");
    loadUsers();
  } catch (e) {
    toast(formatToastMessage(e.message), true);
  }
}

async function adminRevokeUserApiKey(userId, username) {
  const confirmed = await confirmModal(
    CURRENT_LANG === "en"
      ? `Revoke API key for user @${username}?`
      : `Отозвать API-ключ у пользователя @${username}?`
  );
  if (!confirmed) return;
  try {
    await api(`/api/v1/users/${userId}/revoke-api-key`, { method: "DELETE" });
    toast(CURRENT_LANG === "en" ? "API key revoked" : "API-ключ отозван");
    loadUsers();
  } catch (e) {
    toast(formatToastMessage(e.message), true);
  }
}

async function loadUsers() {
  const tbody = document.querySelector("#users-table tbody");
  if (!tbody) return;
  try {
    const users = await api("/api/v1/users");
    const isCurrentUserOwner = CURRENT_USER ? !!CURRENT_USER.is_owner : false;

    tbody.innerHTML = users.map(u => {
      const avatarHtml = u.avatar
        ? `<img src="${escapeHtml(u.avatar)}" style="width:28px; height:28px; border-radius:50%; object-fit:cover;">`
        : `<div style="width:28px; height:28px; border-radius:50%; background:var(--accent); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:12px;">${escapeHtml((u.display_name || u.username || "U").charAt(0).toUpperCase())}</div>`;

      const roleText = u.is_owner ? t("users.role_owner") : (u.is_admin ? t("users.role_admin") : t("users.role_user"));
      const roleBadge = `<span class="user-role-badge ${u.is_admin ? "admin" : "user"}">${escapeHtml(roleText)}</span>`;
      const statusBadge = `<span class="${u.enabled ? "status-badge-active" : "status-badge-disabled"}">${u.enabled ? t("users.active") : t("users.disabled")}</span>`;
      const is2FA = !!u.totp_enabled;
      const badge2fa = is2FA
        ? `<span class="badge badge-success" style="display:inline-flex; align-items:center; gap:4px;"><i data-lucide="shield-check" class="ico-sm" style="width:12px; height:12px;"></i> <span>${t("users.2fa_enabled")}</span></span>`
        : `<span class="badge badge-secondary" style="opacity:0.65;">${t("users.2fa_disabled")}</span>`;
      const lastLogin = u.last_login_at ? formatDateTZ(u.last_login_at) : `<span style="color:var(--text-muted)">${t("users.never_logged_in")}</span>`;

      const canManageThisUser = !u.is_owner || isCurrentUserOwner;

      // Пользователи не могут видеть api-key друг друга, кроме главного администратора
      let apiKeyActionHtml = "";
      if (isCurrentUserOwner) {
        if (u.api_key) {
          apiKeyActionHtml = `<button class="btn btn-secondary btn-small" title="${CURRENT_LANG === 'en' ? 'Copy User API Key' : 'Скопировать API-ключ пользователя'}" onclick="copyTextToClipboard('${u.api_key}')"><i data-lucide="copy" class="ico-sm"></i></button>`;
        } else if (u.can_use_api_key) {
          apiKeyActionHtml = `<button class="btn btn-secondary btn-small" title="${CURRENT_LANG === 'en' ? 'Generate API Key for user' : 'Сгенерировать API-ключ пользователю'}" onclick="adminRegenerateUserApiKey(${u.id}, '${escapeHtml(u.username)}')"><i data-lucide="key" class="ico-sm"></i></button>`;
        }
      }

      // Кнопки 2FA:
      let totpActionHtml = "";
      if (canManageThisUser) {
        if (is2FA) {
          totpActionHtml = `<button class="btn btn-secondary btn-small danger" title="${CURRENT_LANG === 'en' ? 'Disable 2FA for user' : 'Отключить 2FA для пользователя'}" onclick="adminResetUser2FA(${u.id}, '${escapeHtml(u.username)}')"><i data-lucide="shield-off" class="ico-sm"></i></button>`;
        } else {
          totpActionHtml = `<button class="btn btn-secondary btn-small" title="${CURRENT_LANG === 'en' ? 'Setup 2FA for user' : 'Настроить 2FA для пользователя'}" onclick="adminSetupUser2FA(${u.id}, '${escapeHtml(u.username)}')"><i data-lucide="shield-check" class="ico-sm"></i></button>`;
        }
      }

      return `
        <tr>
          <td>${avatarHtml}</td>
          <td>
            <strong>${escapeHtml(u.display_name || u.username)}</strong>
            ${u.display_name && u.display_name !== u.username ? `<span class="hint" style="margin-left:6px;">@${escapeHtml(u.username)}</span>` : ""}
          </td>
          <td>${roleBadge}</td>
          <td>${statusBadge}</td>
          <td>${badge2fa}</td>
          <td class="mono" style="font-size:12px;">${lastLogin}</td>
          <td>
            <div class="row-actions">
              ${apiKeyActionHtml}
              ${totpActionHtml}
              ${canManageThisUser ? `<button class="btn btn-secondary btn-small" title="${t("users.btn_reset_pwd")}" onclick="openUserPasswordResetModal(${u.id}, '${escapeHtml(u.username)}')"><i data-lucide="lock" class="ico-sm"></i></button>` : ""}
              ${canManageThisUser ? `<button class="btn-icon-only" title="${t("common.edit")}" onclick='editUser(${JSON.stringify(u).replace(/'/g, "&apos;")})'><i data-lucide="edit-2" class="ico-sm"></i></button>` : ""}
              ${!u.is_owner && (!CURRENT_USER || CURRENT_USER.id !== u.id) ? `<button class="btn-icon-only danger" title="${t("common.delete")}" onclick="removeUser(${u.id}, '${escapeHtml(u.username)}')"><i data-lucide="trash-2" class="ico-sm"></i></button>` : ""}
            </div>
          </td>
        </tr>
      `;
    }).join("") || `<tr><td colspan="7" style="color:var(--text-muted)">—</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="color:var(--danger)">${escapeHtml(formatToastMessage(e.message))}</td></tr>`;
  }
}

async function submitUser() {
  const username = document.getElementById("user-form-username")?.value.trim() || "";
  const displayName = document.getElementById("user-form-display-name")?.value.trim() || "";
  const sessionTimeout = Number(document.getElementById("user-form-session-timeout")?.value) || 43200;
  const isAdmin = !!document.getElementById("user-form-is-admin")?.checked;

  const perms = {};
  document.querySelectorAll(".user-perm-check").forEach(cb => {
    perms[cb.value] = cb.checked;
  });

  if (!username) {
    toast(CURRENT_LANG === "en" ? "Username required" : "Укажите имя пользователя", true);
    return;
  }

  try {
    if (EDITING_USER_ID) {
      await api(`/api/v1/users/${EDITING_USER_ID}`, {
        method: "PUT",
        body: JSON.stringify({
          display_name: displayName || username,
          is_admin: isAdmin,
          permissions: perms,
          session_timeout_minutes: sessionTimeout,
        }),
      });
      toast(t("settings.toast_saved"));
    } else {
      const password = document.getElementById("user-form-password")?.value || "";
      if (!password || password.length < 4) {
        toast(t("profile.pwd_too_short"), true);
        return;
      }
      await api("/api/v1/users", {
        method: "POST",
        body: JSON.stringify({
          username,
          display_name: displayName || username,
          password,
          is_admin: isAdmin,
          permissions: perms,
          session_timeout_minutes: sessionTimeout,
        }),
      });
      toast(t("common.add"));
    }
    resetUserForm();
    loadUsers();
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
  }
}

function openUserPasswordResetModal(userId, username) {
  RESETTING_PASSWORD_USER_ID = userId;
  document.getElementById("user-pwd-modal-subtitle").textContent = `${t("users.modal_reset_title")}: ${username}`;
  document.getElementById("user-pwd-new").value = "";
  openModal("user-pwd-modal");
}

async function submitUserPasswordReset() {
  const newPassword = document.getElementById("user-pwd-new").value;
  if (!newPassword || newPassword.length < 4) {
    toast(t("profile.pwd_too_short"), true);
    return;
  }
  try {
    await api(`/api/v1/users/${RESETTING_PASSWORD_USER_ID}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    });
    toast(t("profile.pwd_changed_toast"));
    closeModal("user-pwd-modal");
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
  }
}

async function removeUser(userId, username) {
  const confirmed = await confirmModal(`${t("common.delete")} @${username}?`);
  if (!confirmed) return;
  try {
    await api(`/api/v1/users/${userId}`, { method: "DELETE" });
    toast(t("common.delete"));
    loadUsers();
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
  }
}

// =============================================================================
// SETTINGS: AUDIT LOG VIEWER
// =============================================================================

let AUDIT_PAGE = 1;
let AUDIT_SEARCH_TIMER = null;

function translateAuditDescription(desc) {
  if (!desc || CURRENT_LANG !== "en") return desc;
  let s = String(desc);
  s = s.replace(/^Очищены записи аудита старше (\d+) дней \((\d+) записей\)/g, 'Purged audit records older than $1 days ($2 records)');
  s = s.replace(/^Неудачная попытка входа под именем '([^']+)'/g, 'Failed login attempt for username \'$1\'');
  s = s.replace(/^Неудачная попытка входа для пользователя '([^']+)'/g, 'Failed login attempt for user \'$1\'');
  s = s.replace(/^Пользователь '([^']+)' успешно вошел в систему( \(локальная сеть\))?/g, 'User \'$1\' logged in successfully$2');
  s = s.replace(/ \(локальная сеть\)/g, ' (local network)');
  s = s.replace(/^Неверный 2FA TOTP код для пользователя '([^']+)'/g, 'Invalid 2FA TOTP code for user \'$1\'');
  s = s.replace(/^Пользователь '([^']+)' успешно подтвердил вход через 2FA TOTP/g, 'User \'$1\' verified login via 2FA TOTP successfully');
  s = s.replace(/^Пользователь '([^']+)' включил двухфакторную аутентификацию 2FA TOTP/g, 'User \'$1\' enabled 2FA TOTP');
  s = s.replace(/^Пользователь '([^']+)' отключил двухфакторную аутентификацию 2FA TOTP/g, 'User \'$1\' disabled 2FA TOTP');
  s = s.replace(/^Пользователь '([^']+)' вышел из системы/g, 'User \'$1\' logged out');
  s = s.replace(/^Пользователь '([^']+)' обновил профиль (\(.*?\))/g, 'User \'$1\' updated profile $2');
  s = s.replace(/^Пользователь '([^']+)' (?:сменил свой|изменил) пароль/g, 'User \'$1\' changed password');
  s = s.replace(/^Пользователь '([^']+)' обновил аватар/g, 'User \'$1\' updated avatar');
  s = s.replace(/^Обновлен аватар пользователя '([^']+)'/g, 'Updated avatar for user \'$1\'');
  s = s.replace(/^Обновлены настройки аутентификации \(вход по паролю: (.*?), локальный доступ без пароля: (.*?)\)/g, 'Authentication settings updated (password login: $1, local access bypass: $2)');
  s = s.replace(/^Обновлены настройки аутентификации (.*)/g, 'Authentication settings updated $1');
  s = s.replace(/^Пользователь '([^']+)' сгенерировал новый персональный API-ключ/g, 'User \'$1\' generated a new personal API key');
  s = s.replace(/^Пользователь '([^']+)' отозвал(?: свой)? персональный API-ключ/g, 'User \'$1\' revoked personal API key');
  s = s.replace(/^Обновлены общие настройки системы/g, 'System general settings updated');
  s = s.replace(/^Сгенерирован новый системный API-ключ/g, 'New system API key generated');
  s = s.replace(/^Обновлены настройки SSL\/HTTPS \(включен: (.*?), порт: (.*?)\)/g, 'SSL/HTTPS settings updated (enabled: $1, port: $2)');
  s = s.replace(/^Обновлены настройки SSL\/HTTPS (.*)/g, 'SSL/HTTPS settings updated $1');
  s = s.replace(/^Перевыпущен самоподписанный SSL-сертификат Aliasarr/g, 'Aliasarr self-signed SSL certificate regenerated');
  s = s.replace(/^Создан пользователь '([^']+)' \(роль: ([^\)]+)\)/g, 'Created user \'$1\' (role: $2)');
  s = s.replace(/^Создан новый пользователь '([^']+)'/g, 'Created new user \'$1\'');
  s = s.replace(/^Обновлены параметры пользователя '([^']+)'/g, 'Updated parameters for user \'$1\'');
  s = s.replace(/^Обновлены данные пользователя '([^']+)'/g, 'Updated data for user \'$1\'');
  s = s.replace(/^Администратор сбросил пароль пользователю '([^']+)'/g, 'Administrator reset password for user \'$1\'');
  s = s.replace(/^Удалён пользователь '([^']+)' \(id=([^\)]+)\)/g, 'Deleted user \'$1\' (id=$2)');
  s = s.replace(/^Удален пользователь '([^']+)'/g, 'Deleted user \'$1\'');
  s = s.replace(/^Главный администратор сгенерировал новый API-ключ для пользователя '([^']+)'/g, 'Master administrator generated new API key for user \'$1\'');
  s = s.replace(/^Главный администратор отозвал API-ключ у пользователя '([^']+)'/g, 'Master administrator revoked API key from user \'$1\'');
  s = s.replace(/^Администратор '([^']+)' настроил 2FA TOTP для пользователя '([^']+)'/g, 'Administrator \'$1\' configured 2FA TOTP for user \'$2\'');
  s = s.replace(/^Администратор '([^']+)' сбросил 2FA TOTP для пользователя '([^']+)'/g, 'Administrator \'$1\' reset 2FA TOTP for user \'$2\'');
  s = s.replace(/^Администратор включил 2FA TOTP для пользователя '([^']+)'/g, 'Administrator enabled 2FA TOTP for user \'$1\'');
  s = s.replace(/^Администратор отключил 2FA TOTP у пользователя '([^']+)'/g, 'Administrator disabled 2FA TOTP for user \'$1\'');
  s = s.replace(/^Обновлены настройки приложения/g, 'Application settings updated');
  return s;
}

function debounceAuditSearch() {
  clearTimeout(AUDIT_SEARCH_TIMER);
  AUDIT_SEARCH_TIMER = setTimeout(() => {
    AUDIT_PAGE = 1;
    loadAuditLogs(1);
  }, 300);
}

function auditActionBadge(action) {
  let cls = "auth";
  if (action.startsWith("user.")) cls = "user";
  else if (action.startsWith("show.") || action.startsWith("release.")) cls = "show";
  else if (action.startsWith("settings.")) cls = "settings";
  else if (action.includes("delete") || action.includes("failed") || action.includes("block")) cls = "danger";
  return `<span class="action-badge ${cls}">${escapeHtml(action)}</span>`;
}

async function loadAuditLogs(page = 1) {
  AUDIT_PAGE = page;
  const tbody = document.querySelector("#audit-table tbody");
  if (!tbody) return;

  const search = document.getElementById("audit-search")?.value.trim() || "";
  const action = document.getElementById("audit-filter-action")?.value || "";

  let url = `/api/v1/audit?page=${AUDIT_PAGE}&page_size=50`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (action) url += `&action=${encodeURIComponent(action)}`;

  try {
    const data = await api(url);
    const items = data.items || [];
    tbody.innerHTML = items.map(a => `
      <tr>
        <td class="mono col-time" style="font-size:12px;">${formatTimezoneDate(a.created_at)}</td>
        <td class="col-user"><strong>${escapeHtml(a.username || "system")}</strong></td>
        <td class="col-action">${auditActionBadge(a.action)}</td>
        <td class="col-desc" style="word-break:break-word;">${escapeHtml(translateAuditDescription(a.description))}</td>
        <td class="mono col-ip" style="font-size:11px; color:var(--text-muted);">${escapeHtml(a.ip_address || "—")}</td>
      </tr>
    `).join("") || `<tr><td colspan="5" style="color:var(--text-muted)">${t("audit.empty")}</td></tr>`;

    // Render pagination
    const pagEl = document.getElementById("audit-pagination");
    if (pagEl) {
      pagEl.innerHTML = `
        <span class="hint">${CURRENT_LANG === "en" ? "Page" : "Страница"} ${data.page} / ${data.total_pages || 1} (${data.total} ${CURRENT_LANG === "en" ? "records" : "записей"})</span>
        <div style="display:flex; gap:6px;">
          <button class="btn btn-secondary btn-small" ${data.page <= 1 ? "disabled" : ""} onclick="loadAuditLogs(${data.page - 1})"><i data-lucide="chevron-left" class="ico-xs"></i></button>
          <button class="btn btn-secondary btn-small" ${data.page >= data.total_pages ? "disabled" : ""} onclick="loadAuditLogs(${data.page + 1})"><i data-lucide="chevron-right" class="ico-xs"></i></button>
        </div>
      `;
    }
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger)">${escapeHtml(formatToastMessage(e.message))}</td></tr>`;
  }
}

function copyApiKey() {
  const input = document.getElementById("setting-apikey");
  input.select();
  navigator.clipboard?.writeText(input.value).then(() => toast(t("settings.toast_key_copied")));
}

// =============================================================================
// SETTINGS: INDEXERS (create / edit / delete / test)
// =============================================================================

let EDITING_INDEXER_ID = null;

// Категории Torznab больше не используются в UI — на практике трекеры присваивают
// категории иначе, чем ожидает Jackett/Prowlarr, из-за чего валидные релизы
// пропадали из поиска. Индексатор ищет без ограничения по cat=.

function indexerAvailabilityBadge(i) {
  if (i.last_check_ok === null || i.last_check_ok === undefined) {
    return `<span class="status-pill status-unmonitored"><i data-lucide="circle" class="ico-xs"></i> ${CURRENT_LANG === "en" ? "unknown" : "неизвестно"}</span>`;
  }
  if (i.last_check_ok) {
    return `<span class="status-pill status-downloaded"><i data-lucide="check-circle" class="ico-xs"></i> ${CURRENT_LANG === "en" ? "available" : "доступен"}</span>`;
  }
  return `<span class="status-pill status-missing"><i data-lucide="x-circle" class="ico-xs"></i> ${CURRENT_LANG === "en" ? "unavailable" : "недоступен"}</span>`;
}

async function loadIndexers() {
  const tbody = document.querySelector("#indexers-table tbody");
  try {
    const items = await api("/api/v1/indexers");
    tbody.innerHTML = items.map(i => `
      <tr>
        <td>${escapeHtml(i.name)}</td>
        <td>${escapeHtml(i.type)}</td>
        <td class="mono" style="max-width:220px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(i.base_url)}</td>
        <td>${i.priority}</td>
        <td>${indexerAvailabilityBadge(i)}</td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-only" title="Test" onclick="testIndexer(this, ${i.id})"><i data-lucide="arrow-left-right" class="ico-sm"></i></button>
            <button class="btn-icon-only" title="Check" onclick="syncIndexerAvailability(this, ${i.id})"><i data-lucide="refresh-cw" class="ico-sm"></i></button>
            <button class="btn-icon-only" title="${t("common.edit")}" onclick='editIndexer(${JSON.stringify(i).replace(/'/g, "&apos;")})'><i data-lucide="edit-2" class="ico-sm"></i></button>
            <button class="btn-icon-only danger" title="${t("common.delete")}" onclick="removeIndexer(${i.id})"><i data-lucide="trash-2" class="ico-sm"></i></button>
          </div>
        </td>
      </tr>`).join("") || `<tr><td colspan="6" style="color:var(--text-muted)">—</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {}

  try {
    const s = await api("/api/v1/settings");
    document.getElementById("idx-check-enabled").checked = !!s.indexer_check_enabled;
    document.getElementById("idx-check-interval").value = s.indexer_check_interval_minutes ?? 30;
    document.getElementById("idx-check-retries").value = s.indexer_check_retries ?? 3;
    document.getElementById("idx-check-delay").value = s.indexer_check_retry_delay_seconds ?? 5;
  } catch (e) {}
}

async function syncIndexerAvailability(button, id) {
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/indexers/${id}/check`, { method: "POST" });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Indexer is available" : "Индексатор доступен") : (CURRENT_LANG === "en" ? "Indexer unavailable" : "Индексатор недоступен"));
      toast(msg, !result.success);
      loadIndexers();
    } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
  });
}

async function saveIndexerCheckSettings(btn) {
  await withLoading(btn, async () => {
    try {
      await api("/api/v1/settings", {
        method: "PUT",
        body: JSON.stringify({
          indexer_check_enabled: document.getElementById("idx-check-enabled").checked,
          indexer_check_interval_minutes: Number(document.getElementById("idx-check-interval").value) || 30,
          indexer_check_retries: Number(document.getElementById("idx-check-retries").value) || 3,
          indexer_check_retry_delay_seconds: Number(document.getElementById("idx-check-delay").value) || 5,
        }),
      });
      toast(t("settings.toast_saved"));
    } catch (e) { toast("Ошибка: " + e.message, true); }
  });
}

function onIndexerTypeChange() {
  const type = document.getElementById("idx-type").value;
  const urlInput = document.getElementById("idx-url");
  const keyInput = document.getElementById("idx-key");
  const isEn = CURRENT_LANG === "en";
  if (type === "torznab") {
    urlInput.placeholder = isEn ? "Base URL (e.g. http://localhost:9696/1/api)" : "Base URL (напр. http://localhost:9696/1/api)";
    keyInput.placeholder = "API key (Prowlarr / Jackett)";
  } else if (type === "newznab") {
    urlInput.placeholder = isEn ? "Base URL (e.g. https://api.nzbgeek.info)" : "Base URL (напр. https://api.nzbgeek.info)";
    keyInput.placeholder = "API key (Newznab)";
  } else if (type === "nyaa") {
    urlInput.placeholder = isEn ? "Base URL (default https://nyaa.si)" : "Base URL (по умолчанию https://nyaa.si)";
    keyInput.placeholder = isEn ? "Not required (leave empty)" : "Не требуется (оставьте пустым)";
    if (!urlInput.value) urlInput.value = "https://nyaa.si";
  } else if (type === "torrent_rss") {
    urlInput.placeholder = isEn ? "RSS feed URL (e.g. https://site.com/rss.xml)" : "URL RSS-фида (напр. https://site.com/rss.xml)";
    keyInput.placeholder = isEn ? "Passkey (if required)" : "Passkey (если требуется)";
  } else if (type === "iptorrents") {
    urlInput.placeholder = isEn ? "IPTorrents RSS feed URL" : "URL RSS-ленты IPTorrents";
    keyInput.placeholder = "Passkey / Download certificate";
  } else if (type === "torrentleech") {
    urlInput.placeholder = isEn ? "TorrentLeech RSS feed URL" : "URL RSS-ленты TorrentLeech";
    keyInput.placeholder = "Passkey";
  }
}

async function testIndexerAdhoc(button) {
  const payload = {
    name: document.getElementById("idx-name").value.trim() || "Test",
    type: document.getElementById("idx-type").value,
    base_url: document.getElementById("idx-url").value.trim(),
    api_key: document.getElementById("idx-key").value.trim() || null,
    priority: Number(document.getElementById("idx-priority").value) || 25,
  };
  if (!payload.base_url) {
    const errMsg = CURRENT_LANG === "en" ? "Specify indexer URL" : "Укажите URL индексатора";
    toast(errMsg, true);
    showInlineStatus("idx-test-result", errMsg, false);
    return;
  }
  await withLoading(button, async () => {
    try {
      const result = await api("/api/v1/indexers/test", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Connection test successful" : "Тест подключения: успешно") : (CURRENT_LANG === "en" ? "Connection test failed" : "Тест подключения: ошибка"));
      toast(msg, !result.success);
      showInlineStatus("idx-test-result", msg, result.success);
    } catch (e) {
      const errMsg = (CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message;
      toast(errMsg, true);
      showInlineStatus("idx-test-result", errMsg, false);
    }
  });
}

function editIndexer(i) {
  EDITING_INDEXER_ID = i.id;
  document.getElementById("idx-form-title").textContent = `${t("common.edit")}: ${i.name}`;
  document.getElementById("idx-name").value = i.name;
  document.getElementById("idx-type").value = i.type;
  document.getElementById("idx-url").value = i.base_url;
  document.getElementById("idx-key").value = i.api_key || "";
  document.getElementById("idx-priority").value = i.priority;
  onIndexerTypeChange();
  clearInlineStatus("idx-test-result");
  document.getElementById("idx-submit-btn").textContent = t("common.save");
  document.getElementById("idx-cancel-btn").style.display = "inline-block";
  document.getElementById("idx-form-title").scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetIndexerForm() {
  EDITING_INDEXER_ID = null;
  document.getElementById("idx-form-title").textContent = t("indexers.add_title");
  ["idx-name", "idx-url", "idx-key"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("idx-type").value = "torznab";
  document.getElementById("idx-priority").value = 25;
  onIndexerTypeChange();
  clearInlineStatus("idx-test-result");
  document.getElementById("idx-submit-btn").textContent = t("common.add");
  document.getElementById("idx-cancel-btn").style.display = "none";
}

async function submitIndexer() {
  const payload = {
    name: document.getElementById("idx-name").value.trim(),
    type: document.getElementById("idx-type").value,
    base_url: document.getElementById("idx-url").value.trim(),
    api_key: document.getElementById("idx-key").value.trim() || null,
    priority: Number(document.getElementById("idx-priority").value) || 25,
  };
  if (!payload.name || !payload.base_url) { toast(CURRENT_LANG === "en" ? "Name and URL required" : "Заполните имя и URL", true); return; }
  try {
    if (EDITING_INDEXER_ID) {
      await api(`/api/v1/indexers/${EDITING_INDEXER_ID}`, { method: "PUT", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    } else {
      await api("/api/v1/indexers", { method: "POST", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    }
    resetIndexerForm();
    loadIndexers();
  } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
}

async function testIndexer(button, id) {
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/indexers/${id}/test`, { method: "POST" });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Connection test successful" : "Тест подключения: успешно") : (CURRENT_LANG === "en" ? "Connection test failed" : "Тест подключения: ошибка"));
      toast(msg, !result.success);
    } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
  });
}

async function removeIndexer(id) {
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  await api(`/api/v1/indexers/${id}`, { method: "DELETE" });
  loadIndexers();
}

// =============================================================================
// SETTINGS: DOWNLOAD CLIENTS
// =============================================================================

function dcAvailabilityBadge(d) {
  if (d.is_available === true) {
    return `<span class="status-pill status-available"><i data-lucide="check-circle" class="ico-xs"></i> ${t("dc.status_available")}</span>`;
  }
  if (d.is_available === false) {
    return `<span class="status-pill status-missing" title="${escapeHtml(d.last_error || "")}"><i data-lucide="x-circle" class="ico-xs"></i> ${t("dc.status_unavailable")}</span>`;
  }
  return `<span class="status-pill" style="opacity:0.75;"><i data-lucide="help-circle" class="ico-xs"></i> ${t("dc.status_untested")}</span>`;
}

async function loadDownloadClients() {
  const tbody = document.querySelector("#dc-table tbody");
  try {
    const items = await api("/api/v1/download-clients");
    tbody.innerHTML = items.map(d => `
      <tr>
        <td><strong>${escapeHtml(d.name)}</strong></td>
        <td><span class="badge badge-subtle">${escapeHtml(d.type)}</span></td>
        <td class="mono">${escapeHtml(d.host)}${d.port ? ":" + d.port : ""}</td>
        <td>${dcAvailabilityBadge(d)}</td>
        <td>${d.is_default ? '<i data-lucide="check" class="ico-sm" style="color:var(--accent)"></i>' : ""}</td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-only" title="Test" onclick="testDownloadClient(this, ${d.id})"><i data-lucide="arrow-left-right" class="ico-sm"></i></button>
            <button class="btn-icon-only" title="Check" onclick="syncDownloadClientAvailability(this, ${d.id})"><i data-lucide="refresh-cw" class="ico-sm"></i></button>
            <button class="btn-icon-only" title="${t("common.edit")}" onclick='editDownloadClient(${JSON.stringify(d).replace(/'/g, "&apos;")})'><i data-lucide="edit-2" class="ico-sm"></i></button>
            <button class="btn-icon-only danger" title="${t("common.delete")}" onclick="removeDownloadClient(${d.id})"><i data-lucide="trash-2" class="ico-sm"></i></button>
          </div>
        </td>
      </tr>`).join("") || `<tr><td colspan="6" style="color:var(--text-muted)">—</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {}
}

async function syncDownloadClientAvailability(button, id) {
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/download-clients/${id}/check`, { method: "POST" });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Client is available" : "Загрузчик доступен") : (CURRENT_LANG === "en" ? "Client unavailable" : "Загрузчик недоступен"));
      toast(msg, !result.success);
      loadDownloadClients();
    } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
  });
}

function onDownloadClientTypeChange() {
  const type = document.getElementById("dc-type").value;
  const netFields = document.getElementById("dc-network-fields");
  const bhFields = document.getElementById("dc-blackhole-fields");
  const hostInput = document.getElementById("dc-host");
  const portInput = document.getElementById("dc-port");
  const userInput = document.getElementById("dc-user");
  const passInput = document.getElementById("dc-pass");

  if (type === "blackhole") {
    netFields.style.display = "none";
    bhFields.style.display = "block";
    return;
  }
  netFields.style.display = "block";
  bhFields.style.display = "none";

  const isEn = CURRENT_LANG === "en";
  if (type === "qbittorrent") {
    hostInput.placeholder = isEn ? "Host (e.g. localhost or qbittorrent)" : "Host (напр. localhost или qbittorrent)";
    portInput.placeholder = "8080";
    userInput.placeholder = isEn ? "Username (admin)" : "Логин (admin)";
    passInput.placeholder = isEn ? "Password (adminadmin)" : "Пароль (adminadmin)";
    if (!portInput.value || portInput.value === "9091" || portInput.value === "8112" || portInput.value === "6800" || portInput.value === "6789") portInput.value = "8080";
  } else if (type === "transmission") {
    hostInput.placeholder = isEn ? "Host (e.g. localhost or transmission)" : "Host (напр. localhost или transmission)";
    portInput.placeholder = "9091";
    userInput.placeholder = isEn ? "Username (optional)" : "Логин (необязательно)";
    passInput.placeholder = isEn ? "Password (optional)" : "Пароль (необязательно)";
    if (!portInput.value || portInput.value === "8080" || portInput.value === "8112") portInput.value = "9091";
  } else if (type === "deluge") {
    hostInput.placeholder = isEn ? "Host (e.g. localhost or deluge)" : "Host (напр. localhost или deluge)";
    portInput.placeholder = "8112";
    userInput.placeholder = isEn ? "Username (not used)" : "Логин (не используется)";
    passInput.placeholder = isEn ? "Web UI Password (deluge)" : "Пароль Web UI (deluge)";
    if (!portInput.value || portInput.value === "8080" || portInput.value === "9091") portInput.value = "8112";
  } else if (type === "rtorrent") {
    hostInput.placeholder = isEn ? "Host (e.g. localhost or rtorrent)" : "Host (напр. localhost или rtorrent)";
    portInput.placeholder = isEn ? "80 or 8080" : "80 или 8080";
    userInput.placeholder = isEn ? "HTTP-Auth Username (if any)" : "Логин HTTP-Auth (если есть)";
    passInput.placeholder = isEn ? "HTTP-Auth Password" : "Пароль HTTP-Auth";
  } else if (type === "aria2") {
    hostInput.placeholder = isEn ? "Host (e.g. localhost or aria2)" : "Host (напр. localhost или aria2)";
    portInput.placeholder = "6800";
    userInput.placeholder = isEn ? "Username (not used)" : "Логин (не используется)";
    passInput.placeholder = "RPC Secret Token";
    if (!portInput.value || portInput.value === "8080" || portInput.value === "9091") portInput.value = "6800";
  } else if (type === "sabnzbd") {
    hostInput.placeholder = isEn ? "Host (e.g. localhost or sabnzbd)" : "Host (напр. localhost или sabnzbd)";
    portInput.placeholder = "8080";
    userInput.placeholder = isEn ? "Username (not used)" : "Логин (не используется)";
    passInput.placeholder = "SABnzbd API Key";
    if (!portInput.value || portInput.value === "9091" || portInput.value === "6800") portInput.value = "8080";
  } else if (type === "nzbget") {
    hostInput.placeholder = isEn ? "Host (e.g. localhost or nzbget)" : "Host (напр. localhost или nzbget)";
    portInput.placeholder = "6789";
    userInput.placeholder = isEn ? "Username (nzbget)" : "Логин (nzbget)";
    passInput.placeholder = isEn ? "Password (tegbzn6789)" : "Пароль (tegbzn6789)";
    if (!portInput.value || portInput.value === "8080" || portInput.value === "9091") portInput.value = "6789";
  }
}

function editDownloadClient(d) {
  EDITING_DC_ID = d.id;
  document.getElementById("dc-form-title").textContent = `${t("common.edit")}: ${d.name}`;
  document.getElementById("dc-name").value = d.name;
  document.getElementById("dc-type").value = d.type;
  onDownloadClientTypeChange();
  if (d.type === "blackhole") {
    document.getElementById("dc-watch-dir").value = d.host;
  } else {
    document.getElementById("dc-host").value = d.host;
    document.getElementById("dc-port").value = d.port;
    document.getElementById("dc-user").value = d.username || "";
  }
  document.getElementById("dc-pass").value = "";
  document.getElementById("dc-category").value = d.category || "aliasarr";
  document.getElementById("dc-seed-time-limit").value = d.seed_time_limit !== null && d.seed_time_limit !== undefined ? d.seed_time_limit : "";
  document.getElementById("dc-seed-ratio-limit").value = d.seed_ratio_limit !== null && d.seed_ratio_limit !== undefined ? d.seed_ratio_limit : "";
  document.getElementById("dc-default").checked = d.is_default;
  document.getElementById("dc-submit-btn").textContent = t("common.save");
  document.getElementById("dc-cancel-btn").style.display = "inline-block";
}

function resetDownloadClientForm() {
  EDITING_DC_ID = null;
  document.getElementById("dc-form-title").textContent = t("clients.add_title");
  ["dc-name", "dc-host", "dc-port", "dc-user", "dc-pass", "dc-watch-dir", "dc-seed-time-limit", "dc-seed-ratio-limit"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  document.getElementById("dc-type").value = "qbittorrent";
  document.getElementById("dc-category").value = "aliasarr";
  document.getElementById("dc-default").checked = false;
  onDownloadClientTypeChange();
  clearInlineStatus("dc-test-result");
  document.getElementById("dc-submit-btn").textContent = t("common.add");
  document.getElementById("dc-cancel-btn").style.display = "none";
}

async function submitDownloadClient() {
  const type = document.getElementById("dc-type").value;
  let host = document.getElementById("dc-host").value.trim();
  let port = Number(document.getElementById("dc-port").value) || 0;
  if (type === "blackhole") {
    host = document.getElementById("dc-watch-dir").value.trim() || "/data/torrents/watch";
    port = 0;
  }
  const seedTimeVal = document.getElementById("dc-seed-time-limit")?.value?.trim();
  const seedRatioVal = document.getElementById("dc-seed-ratio-limit")?.value?.trim();

  const payload = {
    name: document.getElementById("dc-name").value.trim(),
    type: type,
    host: host,
    port: port,
    username: document.getElementById("dc-user").value.trim() || null,
    password: document.getElementById("dc-pass").value.trim() || null,
    category: document.getElementById("dc-category").value.trim() || "aliasarr",
    is_default: document.getElementById("dc-default").checked,
    seed_time_limit: seedTimeVal !== "" && !isNaN(Number(seedTimeVal)) ? Number(seedTimeVal) : null,
    seed_ratio_limit: seedRatioVal !== "" && !isNaN(Number(seedRatioVal)) ? Number(seedRatioVal) : null,
  };
  if (!payload.name || !payload.host || (type !== "blackhole" && !payload.port)) {
    toast(CURRENT_LANG === "en" ? "Fill required fields" : "Заполните обязательные поля", true);
    return;
  }
  try {
    if (EDITING_DC_ID) {
      await api(`/api/v1/download-clients/${EDITING_DC_ID}`, { method: "PUT", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    } else {
      await api("/api/v1/download-clients", { method: "POST", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    }
    resetDownloadClientForm();
    loadDownloadClients();
  } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
}

async function testDownloadClientAdhoc(button) {
  const type = document.getElementById("dc-type").value;
  let host = document.getElementById("dc-host").value.trim();
  let port = Number(document.getElementById("dc-port").value) || 0;
  if (type === "blackhole") {
    host = document.getElementById("dc-watch-dir").value.trim() || "/data/torrents/watch";
    port = 0;
  }
  const payload = {
    name: document.getElementById("dc-name").value.trim() || "Test",
    type: type,
    host: host,
    port: port,
    username: document.getElementById("dc-user").value.trim() || null,
    password: document.getElementById("dc-pass").value.trim() || null,
    category: document.getElementById("dc-category").value.trim() || "aliasarr",
    is_default: document.getElementById("dc-default").checked,
  };
  if (type !== "blackhole" && (!payload.host || !payload.port)) {
    const errMsg = CURRENT_LANG === "en" ? "Specify host and port" : "Укажите хост и порт";
    toast(errMsg, true);
    showInlineStatus("dc-test-result", errMsg, false);
    return;
  }
  await withLoading(button, async () => {
    try {
      const result = await api("/api/v1/download-clients/test", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Connection test successful" : "Тест подключения: успешно") : (CURRENT_LANG === "en" ? "Connection test failed" : "Тест подключения: ошибка"));
      toast(msg, !result.success);
      showInlineStatus("dc-test-result", msg, result.success);
    } catch (e) {
      const errMsg = (CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message;
      toast(errMsg, true);
      showInlineStatus("dc-test-result", errMsg, false);
    }
  });
}

async function testDownloadClient(button, id) {
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/download-clients/${id}/test`, { method: "POST" });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Connection test successful" : "Тест подключения: успешно") : (CURRENT_LANG === "en" ? "Connection test failed" : "Тест подключения: ошибка"));
      toast(msg, !result.success);
    } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
  });
}

async function removeDownloadClient(id) {
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  await api(`/api/v1/download-clients/${id}`, { method: "DELETE" });
  loadDownloadClients();
}

// =============================================================================
// SETTINGS: QUALITY PROFILES (chip-based multi-select)
// =============================================================================

let EDITING_QP_ID = null;
let SELECTED_QUALITIES = new Set();

function renderQualityChips() {
  const el = document.getElementById("qp-quality-chips");
  if (!el) return;
  el.innerHTML = QUALITY_OPTIONS.map(q => `
    <span class="chip-toggle ${SELECTED_QUALITIES.has(q) ? "selected" : ""}" onclick="toggleQualityChip('${q}')">${q}</span>
  `).join("");

  const cutoffSel = document.getElementById("qp-cutoff-quality");
  if (cutoffSel) {
    const curVal = cutoffSel.value;
    cutoffSel.innerHTML = `<option value="">${CURRENT_LANG === "en" ? "Any" : "Любое (Any)"}</option>` +
      QUALITY_OPTIONS.map(q => `<option value="${q}">${q}</option>`).join("");
    if (curVal) cutoffSel.value = curVal;
  }
}

function toggleQualityChip(q) {
  if (SELECTED_QUALITIES.has(q)) SELECTED_QUALITIES.delete(q); else SELECTED_QUALITIES.add(q);
  renderQualityChips();
}

async function loadQualityProfiles() {
  renderQualityChips();
  const tbody = document.querySelector("#qp-table tbody");
  try {
    const items = await api("/api/v1/quality-profiles");
    CACHED_QUALITY_PROFILES = items;
    tbody.innerHTML = items.map(q => `
      <tr>
        <td><strong>${escapeHtml(q.name)}</strong></td>
        <td class="mono">${(q.allowed_qualities || []).join(", ") || t("common.any_quality")}</td>
        <td>
          ${q.cutoff_quality ? `<span class="badge badge-quality">${escapeHtml(q.cutoff_quality)}</span>` : `<span class="hint">—</span>`}
          ${q.cutoff_score > 0 ? `<span class="badge badge-cf-score" style="margin-left:4px;">Score: ${q.cutoff_score}</span>` : ""}
        </td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-only" title="${t("common.edit")}" onclick='editQualityProfile(${JSON.stringify(q).replace(/'/g, "&apos;")})'><i data-lucide="edit-2" class="ico-sm"></i></button>
            <button class="btn-icon-only danger" title="${t("common.delete")}" onclick="removeQualityProfile(${q.id})"><i data-lucide="trash-2" class="ico-sm"></i></button>
          </div>
        </td>
      </tr>`).join("") || `<tr><td colspan="4" style="color:var(--text-muted)">—</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {}

  loadCustomFormats();
}

function editQualityProfile(q) {
  EDITING_QP_ID = q.id;
  document.getElementById("qp-form-title").textContent = `${t("common.edit")}: ${q.name}`;
  document.getElementById("qp-name").value = q.name;
  SELECTED_QUALITIES = new Set(q.allowed_qualities || []);
  renderQualityChips();
  
  const cutoffSel = document.getElementById("qp-cutoff-quality");
  if (cutoffSel) cutoffSel.value = q.cutoff_quality || "";
  const cutoffScore = document.getElementById("qp-cutoff-score");
  if (cutoffScore) cutoffScore.value = q.cutoff_score || 0;
  const upgradeChk = document.getElementById("qp-upgrade-allowed");
  if (upgradeChk) upgradeChk.checked = q.upgrade_allowed !== false;

  document.getElementById("qp-submit-btn").textContent = t("common.save");
  document.getElementById("qp-cancel-btn").style.display = "inline-block";
}

function resetQualityProfileForm() {
  EDITING_QP_ID = null;
  document.getElementById("qp-form-title").textContent = t("quality.add_title");
  document.getElementById("qp-name").value = "";
  SELECTED_QUALITIES = new Set();
  renderQualityChips();

  const cutoffSel = document.getElementById("qp-cutoff-quality");
  if (cutoffSel) cutoffSel.value = "";
  const cutoffScore = document.getElementById("qp-cutoff-score");
  if (cutoffScore) cutoffScore.value = 0;
  const upgradeChk = document.getElementById("qp-upgrade-allowed");
  if (upgradeChk) upgradeChk.checked = true;

  document.getElementById("qp-submit-btn").textContent = t("common.add");
  document.getElementById("qp-cancel-btn").style.display = "none";
}

async function submitQualityProfile() {
  const name = document.getElementById("qp-name").value.trim();
  if (!name) { toast("Name required", true); return; }

  const cutoffQuality = document.getElementById("qp-cutoff-quality")?.value || null;
  const cutoffScore = parseInt(document.getElementById("qp-cutoff-score")?.value || "0", 10) || 0;
  const upgradeAllowed = document.getElementById("qp-upgrade-allowed")?.checked ?? true;

  const payload = {
    name,
    allowed_qualities: Array.from(SELECTED_QUALITIES),
    cutoff_quality: cutoffQuality,
    cutoff_score: cutoffScore,
    upgrade_allowed: upgradeAllowed,
  };

  try {
    if (EDITING_QP_ID) {
      await api(`/api/v1/quality-profiles/${EDITING_QP_ID}`, { method: "PUT", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    } else {
      await api("/api/v1/quality-profiles", { method: "POST", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    }
    resetQualityProfileForm();
    loadQualityProfiles();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function removeQualityProfile(id) {
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  await api(`/api/v1/quality-profiles/${id}`, { method: "DELETE" });
  loadQualityProfiles();
}

// =============================================================================
// НАСТРОЙКИ: ФОРМАТЫ КАЧЕСТВА
// =============================================================================

async function loadCustomFormats() {
  const tbody = document.getElementById("cf-table-body");
  if (!tbody) return;
  try {
    const items = await api("/api/v1/custom-formats");
    CACHED_CUSTOM_FORMATS = (items || []).sort((a, b) => (b.score || 0) - (a.score || 0));
    tbody.innerHTML = CACHED_CUSTOM_FORMATS.map(cf => {
      const isBuiltin = Boolean(cf.is_builtin || (cf.name in CF_PRESETS));
      const builtinBadge = isBuiltin
        ? `<span class="badge" style="background:rgba(99,102,241,0.15); color:var(--accent); font-size:10px; margin-left:6px; vertical-align:middle;">${t("cf.builtin_badge")}</span>`
        : "";
      const deleteBtn = isBuiltin
        ? `<button class="btn-icon-only disabled" style="opacity:0.35; cursor:not-allowed;" title="${t("cf.cannot_delete_builtin")}" disabled><i data-lucide="lock" class="ico-sm"></i></button>`
        : `<button class="btn-icon-only danger" title="${t("common.delete")}" onclick="deleteCustomFormat(${cf.id})"><i data-lucide="trash-2" class="ico-sm"></i></button>`;

      return `
      <tr>
        <td><strong>${escapeHtml(cf.name)}</strong>${builtinBadge}</td>
        <td>
          <span class="badge-cf-score ${cf.score > 0 ? "positive" : (cf.score < 0 ? "negative" : "")}">${cf.score > 0 ? `+${cf.score}` : cf.score}</span>
        </td>
        <td>${cf.include_custom_format_when_renaming ? `<span class="badge badge-accent">${t("common.yes")}</span>` : `<span class="hint">${t("common.no")}</span>`}</td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-only" title="${t("common.edit")}" onclick='editCustomFormat(${JSON.stringify(cf).replace(/'/g, "&apos;")})'><i data-lucide="edit-2" class="ico-sm"></i></button>
            ${deleteBtn}
          </div>
        </td>
      </tr>`;
    }).join("") || `<tr><td colspan="4" style="color:var(--text-muted); text-align:center; padding:20px;">${CURRENT_LANG === "en" ? "No quality formats" : "Нет форматов качества"}</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {}
}

const CF_PRESETS = {
  "Remux-2160p": { score: 110, regex: "\\b(remux[._\\-\\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\\-\\s]?remux|uhd[-_. ]?remux|bdremux[._\\-\\s]?(?:2160p|4k|uhd))\\b", rename: false },
  "Bluray-2160p": { score: 100, regex: "\\b(bluray[._\\-\\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\\-\\s]?bluray|blu-ray[._\\-\\s]?(?:2160p|4k|uhd)|uhd[-_. ]?bluray|bdrip[._\\-\\s]?(?:2160p|4k|uhd)|brrip[._\\-\\s]?(?:2160p|4k|uhd))\b", rename: false },
  "WEBDL-2160p": { score: 95, regex: "\\b(web[-_. ]?dl[._\\-\\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\\-\\s]?web[-_. ]?dl|webhd[._\\-\\s]?(?:2160p|4k|uhd))\\b", rename: false },
  "WEBRip-2160p": { score: 90, regex: "\\b(webrip[._\\-\\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\\-\\s]?webrip|web-rip[._\\-\\s]?(?:2160p|4k|uhd))\\b", rename: false },
  "HDTV-2160p": { score: 85, regex: "\\b(hdtv[._\\-\\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\\-\\s]?hdtv)\\b", rename: false },
  "Remux-1080p": { score: 80, regex: "\\b(remux[._\\-\\s]?(?:1080p)|1080p[._\\-\\s]?remux|bdremux[._\\-\\s]?1080p)\\b", rename: false },
  "Bluray-1080p": { score: 70, regex: "\\b(bluray[._\\-\\s]?(?:1080p)|1080p[._\\-\\s]?bluray|blu-ray[._\\-\\s]?1080p|bdrip[._\\-\\s]?1080p|brrip[._\\-\\s]?1080p)\\b", rename: false },
  "WEBDL-1080p": { score: 60, regex: "\\b(web[-_. ]?dl[._\\-\\s]?(?:1080p)|1080p[._\\-\\s]?web[-_. ]?dl|webhd[._\\-\\s]?1080p)\\b", rename: false },
  "WEBRip-1080p": { score: 55, regex: "\\b(webrip[._\\-\\s]?(?:1080p)|1080p[._\\-\\s]?webrip|web-rip[._\\-\\s]?1080p)\\b", rename: false },
  "HDTV-1080p": { score: 50, regex: "\\b(hdtv[._\\-\\s]?(?:1080p|1080i)|1080[pi][._\\-\\s]?hdtv)\\b", rename: false },
  "Bluray-720p": { score: 45, regex: "\\b(bluray[._\\-\\s]?(?:720p)|720p[._\\-\\s]?bluray|blu-ray[._\\-\\s]?720p|bdrip[._\\-\\s]?720p|brrip[._\\-\\s]?720p)\\b", rename: false },
  "WEBDL-720p": { score: 40, regex: "\\b(web[-_. ]?dl[._\\-\\s]?(?:720p)|720p[._\\-\\s]?web[-_. ]?dl|webhd[._\\-\\s]?720p)\\b", rename: false },
  "WEBRip-720p": { score: 35, regex: "\\b(webrip[._\\-\\s]?(?:720p)|720p[._\\-\\s]?webrip|web-rip[._\\-\\s]?720p)\\b", rename: false },
  "HDTV-720p": { score: 30, regex: "\\b(hdtv[._\\-\\s]?(?:720p)|720p[._\\-\\s]?hdtv)\\b", rename: false },
  "Bluray-480p": { score: 28, regex: "\\b(bluray[._\\-\\s]?(?:480p|576p)|(?:480p|576p)[._\\-\\s]?bluray|blu-ray[._\\-\\s]?(?:480p|576p)|bdrip|brrip|bd[-_. ]?rip|br[-_. ]?rip)\\b", rename: false },
  "WEBDL-480p": { score: 26, regex: "\\b(web[-_. ]?dl[._\\-\\s]?(?:480p|576p)|(?:480p|576p)[._\\-\\s]?web[-_. ]?dl)\\b", rename: false },
  "WEBRip-480p": { score: 24, regex: "\\b(webrip[._\\-\\s]?(?:480p|576p)|(?:480p|576p)[._\\-\\s]?webrip)\\b", rename: false },
  "HDTV-480p": { score: 22, regex: "\\b(hdtv[._\\-\\s]?(?:480p|576p)|(?:480p|576p)[._\\-\\s]?hdtv)\\b", rename: false },
  "DVDRip-480p": { score: 20, regex: "\\b(dvdrip|dvd-rip)\\b", rename: false },
  "DVD-480p": { score: 15, regex: "\\b(dvd|dvd9|dvd5|dvd-r|ntsc|pal|xvidvd)\\b", rename: false },
  "TVRip-480p": { score: 12, regex: "\\b(tvrip|satrip|dtvrip)\\b", rename: false },
  "SDTV-480p": { score: 10, regex: "\\b(sdtv|pdtv|dsr|360p)\\b", rename: false },
  "Workprint-480p": { score: 4, regex: "\\b(workprint|wp)\\b", rename: false },
  "Telecine-480p": { score: 3, regex: "\\b(telecine|tc|hdtc)\\b", rename: false },
  "Telesync-480p": { score: 2, regex: "\\b(telesync|hdts|hd-ts|tsrip|telesync-rip)\\b", rename: false },
  "CAM-480p": { score: 1, regex: "\\b(camrip|cam|hdcam)\\b", rename: false }
};

function onCustomFormatPresetSelect(presetKey) {
  if (!presetKey) return;
  const p = CF_PRESETS[presetKey] || {};
  const existing = (CACHED_CUSTOM_FORMATS || []).find(item => item.name.toLowerCase() === presetKey.toLowerCase());
  
  document.getElementById("cf-name").value = presetKey;
  if (existing) {
    document.getElementById("cf-id").value = existing.id;
    document.getElementById("cf-score").value = existing.score;
    document.getElementById("cf-include-renaming").checked = Boolean(existing.include_custom_format_when_renaming);
    let pattern = "";
    if (existing.specifications && existing.specifications.length) {
      pattern = existing.specifications[0]?.fields?.value || "";
    }
    document.getElementById("cf-regex").value = pattern || p.regex || "";
    const banner = document.getElementById("cf-builtin-banner");
    if (banner) banner.style.display = (existing.is_builtin || presetKey in CF_PRESETS) ? "block" : "none";
    const resetBtn = document.getElementById("cf-reset-btn");
    if (resetBtn) resetBtn.style.display = (existing.is_builtin || presetKey in CF_PRESETS) ? "inline-flex" : "none";
  } else {
    document.getElementById("cf-id").value = "";
    document.getElementById("cf-score").value = p.score ?? 100;
    document.getElementById("cf-regex").value = p.regex || "";
    document.getElementById("cf-include-renaming").checked = Boolean(p.rename);
    const banner = document.getElementById("cf-builtin-banner");
    if (banner) banner.style.display = (presetKey in CF_PRESETS) ? "block" : "none";
    const resetBtn = document.getElementById("cf-reset-btn");
    if (resetBtn) resetBtn.style.display = (presetKey in CF_PRESETS) ? "inline-flex" : "none";
  }
}

function onCustomFormatNameInput(val) {
  const name = (val || "").trim();
  if (!name) return;
  const existing = (CACHED_CUSTOM_FORMATS || []).find(item => item.name.toLowerCase() === name.toLowerCase());
  const banner = document.getElementById("cf-builtin-banner");
  const resetBtn = document.getElementById("cf-reset-btn");
  if (existing) {
    document.getElementById("cf-id").value = existing.id;
    if (banner) banner.style.display = (existing.is_builtin || name in CF_PRESETS) ? "block" : "none";
    if (resetBtn) resetBtn.style.display = (existing.is_builtin || name in CF_PRESETS) ? "inline-flex" : "none";
  } else {
    if (banner) banner.style.display = (name in CF_PRESETS) ? "block" : "none";
    if (resetBtn) resetBtn.style.display = (name in CF_PRESETS) ? "inline-flex" : "none";
  }
}

function openAddCustomFormatModal() {
  document.getElementById("cf-id").value = "";
  document.getElementById("cf-modal-title").innerHTML = `<i data-lucide="sparkles" class="ico-sm"></i> <span>${CURRENT_LANG === "en" ? "Add Quality Format" : "Добавить формат качества"}</span>`;
  const banner = document.getElementById("cf-builtin-banner");
  if (banner) banner.style.display = "none";
  const resetBtn = document.getElementById("cf-reset-btn");
  if (resetBtn) resetBtn.style.display = "none";

  const presetEl = document.getElementById("cf-preset");
  if (presetEl) presetEl.value = "";
  document.getElementById("cf-name").value = "";
  document.getElementById("cf-score").value = "100";
  document.getElementById("cf-include-renaming").checked = false;
  document.getElementById("cf-regex").value = "";
  openModal("custom-format-modal");
  if (window.lucide) lucide.createIcons();
}

function editCustomFormat(cf) {
  const isBuiltin = Boolean(cf.is_builtin || (cf.name in CF_PRESETS));
  document.getElementById("cf-id").value = cf.id;
  document.getElementById("cf-modal-title").innerHTML = `<i data-lucide="sparkles" class="ico-sm"></i> <span>${t("common.edit")}: ${escapeHtml(cf.name)}</span>`;
  
  const banner = document.getElementById("cf-builtin-banner");
  if (banner) banner.style.display = isBuiltin ? "block" : "none";
  const resetBtn = document.getElementById("cf-reset-btn");
  if (resetBtn) resetBtn.style.display = isBuiltin ? "inline-flex" : "none";

  const presetEl = document.getElementById("cf-preset");
  if (presetEl) presetEl.value = cf.name in CF_PRESETS ? cf.name : "";
  document.getElementById("cf-name").value = cf.name;
  document.getElementById("cf-score").value = cf.score;
  document.getElementById("cf-include-renaming").checked = cf.include_custom_format_when_renaming;
  
  let pattern = "";
  if (cf.specifications && cf.specifications.length) {
    pattern = cf.specifications[0]?.fields?.value || "";
  }
  document.getElementById("cf-regex").value = pattern;

  openModal("custom-format-modal");
  if (window.lucide) lucide.createIcons();
}

async function resetCurrentCustomFormat() {
  const id = document.getElementById("cf-id").value;
  if (!id) return;
  const confirmed = await confirmModal(t("cf.reset_confirm"));
  if (!confirmed) return;
  try {
    await api(`/api/v1/custom-formats/${id}/reset`, { method: "POST" });
    toast(t("cf.reset_success"));
    closeModal("custom-format-modal");
    await loadCustomFormats();
  } catch (e) {
    toast("Ошибка: " + e.message, true);
  }
}

async function submitCustomFormat() {
  let id = document.getElementById("cf-id").value;
  const name = document.getElementById("cf-name").value.trim();
  const score = parseInt(document.getElementById("cf-score").value || "0", 10);
  const includeRenaming = document.getElementById("cf-include-renaming").checked;
  let regexVal = document.getElementById("cf-regex").value.trim();

  if (!name) { toast(CURRENT_LANG === "en" ? "Enter format name" : "Укажите название формата", true); return; }

  // If regex is empty, try preset regex or auto-generate safe regex from name
  if (!regexVal) {
    if (CF_PRESETS[name]) {
      regexVal = CF_PRESETS[name].regex;
    } else {
      const safeEscaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      regexVal = `\\b${safeEscaped}\\b`;
    }
  }

  const specs = [];
  if (regexVal) {
    specs.push({
      name: `${name} Pattern`,
      implementation: "ReleaseTitleSpecification",
      negate: false,
      required: true,
      fields: { value: regexVal },
    });
  }

  // If ID was empty, check if format already exists in cache
  if (!id && CACHED_CUSTOM_FORMATS && CACHED_CUSTOM_FORMATS.length) {
    const existing = CACHED_CUSTOM_FORMATS.find(item => item.name.toLowerCase() === name.toLowerCase());
    if (existing) {
      id = existing.id;
    }
  }

  const payload = {
    name,
    score,
    include_custom_format_when_renaming: includeRenaming,
    specifications: specs,
  };

  try {
    if (id) {
      await api(`/api/v1/custom-formats/${id}`, { method: "PUT", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    } else {
      await api("/api/v1/custom-formats", { method: "POST", body: JSON.stringify(payload) });
      toast(CURRENT_LANG === "en" ? "Quality format added" : "Формат качества добавлен");
    }
    closeModal("custom-format-modal");
    await loadCustomFormats();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function deleteCustomFormat(id) {
  const cf = CACHED_CUSTOM_FORMATS.find(item => item.id === id);
  if (cf && (cf.is_builtin || cf.name in CF_PRESETS)) {
    toast(t("cf.cannot_delete_builtin"), true);
    return;
  }
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  try {
    await api(`/api/v1/custom-formats/${id}`, { method: "DELETE" });
    toast(CURRENT_LANG === "en" ? "Format deleted" : "Формат удален");
    loadCustomFormats();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

// =============================================================================
// SETTINGS: METADATA SOURCES
// =============================================================================

let EDITING_MD_ID = null;

function toggleCustomMetadataFields() {
  const mdTypeEl = document.getElementById("md-type");
  const type = mdTypeEl ? mdTypeEl.value : "skyhook";
  const skyhookInst = document.getElementById("md-skyhook-instructions");
  if (skyhookInst) skyhookInst.style.display = type === "skyhook" ? "block" : "none";
  const radarrInst = document.getElementById("md-radarr-instructions");
  if (radarrInst) radarrInst.style.display = type === "radarr" ? "block" : "none";
  const tmdbInst = document.getElementById("md-tmdb-instructions");
  if (tmdbInst) tmdbInst.style.display = type === "tmdb" ? "block" : "none";
  const tvdbInst = document.getElementById("md-thetvdb-instructions");
  if (tvdbInst) tvdbInst.style.display = type === "thetvdb" ? "block" : "none";
  const tvmazeInst = document.getElementById("md-tvmaze-instructions");
  if (tvmazeInst) tvmazeInst.style.display = type === "tvmaze" ? "block" : "none";

  const mdKey = document.getElementById("md-key");
  const mdPin = document.getElementById("md-pin");
  if (type === "skyhook" || type === "radarr") {
    if (mdKey) {
      mdKey.style.display = "none";
      mdKey.value = "";
    }
    if (mdPin) mdPin.style.display = "none";
  } else if (type === "thetvdb") {
    if (mdKey) {
      mdKey.style.display = "block";
      mdKey.placeholder = "TheTVDB API Key v4";
    }
    if (mdPin) mdPin.style.display = "block";
  } else if (type === "tvmaze") {
    if (mdKey) {
      mdKey.style.display = "block";
      mdKey.placeholder = "API key (optional)";
    }
    if (mdPin) mdPin.style.display = "none";
  } else if (type === "tmdb") {
    if (mdKey) {
      mdKey.style.display = "block";
      mdKey.placeholder = "Read Access Token (eyJ...)";
    }
    if (mdPin) mdPin.style.display = "none";
  } else {
    if (mdKey) {
      mdKey.style.display = "block";
      mdKey.placeholder = "API key";
    }
    if (mdPin) mdPin.style.display = "none";
  }
  
  const aliasFilterWrap = document.getElementById("md-alias-filter-wrap");
  if (aliasFilterWrap) {
    aliasFilterWrap.style.display = (type === "skyhook" || type === "radarr") ? "none" : "block";
  }
}

async function loadMetadataSources() {
  toggleCustomMetadataFields();
  const tbody = document.querySelector("#md-table tbody");
  if (!tbody) return;
  try {
    const items = await api("/api/v1/metadata-sources");
    CACHED_METADATA_SOURCES = items || [];
    tbody.innerHTML = (items && items.length > 0) ? items.map(m => {
      const typeStr = (m.type && m.type.value) ? m.type.value : (m.type || "tmdb");
      const typeLabels = {
        skyhook: "Sonarr SkyHook",
        radarr: "Radarr SkyHook",
        tmdb: "TMDB",
        thetvdb: "TheTVDB",
        tvmaze: "TVMaze",
      };
      const typeDisplay = typeLabels[typeStr.toLowerCase()] || typeStr;
      return `
      <tr>
        <td><strong>${escapeHtml(m.name)}</strong></td>
        <td><span class="indexer-status-badge available">${escapeHtml(typeDisplay)}</span></td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-only" title="${t("common.edit")}" onclick='editMetadataSource(${JSON.stringify(m).replace(/'/g, "&apos;")})'><i data-lucide="edit-2" class="ico-sm"></i></button>
            <button class="btn-icon-only danger" title="${t("common.delete")}" onclick="removeMetadataSource(${m.id})"><i data-lucide="trash-2" class="ico-sm"></i></button>
          </div>
        </td>
      </tr>`;
    }).join("") : `<tr><td colspan="3" style="color:var(--text-muted)">—</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    console.error("loadMetadataSources error:", e);
    tbody.innerHTML = `<tr><td colspan="3" style="color:var(--danger)">${escapeHtml(formatToastMessage(e.message))}</td></tr>`;
  }
  loadMetadataRefreshSettings();
}

async function loadMetadataRefreshSettings() {
  const autoEl = document.getElementById("md-auto-refresh-enabled");
  const intervalEl = document.getElementById("md-refresh-interval");
  if (!autoEl || !intervalEl) return;
  try {
    const s = await api("/api/v1/settings");
    autoEl.checked = s.metadata_auto_refresh_enabled !== false;
    intervalEl.value = String(s.metadata_refresh_interval_hours || 12);
  } catch (e) {
    console.error("loadMetadataRefreshSettings error:", e);
  }
}

async function saveMetadataRefreshSettings() {
  const autoEl = document.getElementById("md-auto-refresh-enabled");
  const intervalEl = document.getElementById("md-refresh-interval");
  if (!autoEl || !intervalEl) return;
  try {
    await api("/api/v1/settings", "PUT", {
      metadata_auto_refresh_enabled: autoEl.checked,
      metadata_refresh_interval_hours: Number(intervalEl.value) || 12,
    });
    showToast(t("md.settings_saved") || "Настройки обновления метаданных сохранены");
  } catch (e) {
    showToast(e.message || "Ошибка сохранения настроек", "error");
  }
}

async function triggerManualMetadataRefresh(btn) {
  if (btn) btn.classList.add("is-loading");
  const statusEl = document.getElementById("md-refresh-status");
  if (statusEl) {
    statusEl.style.display = "block";
    statusEl.textContent = t("md.refresh_started") || "Запущено обновление метаданных библиотеки...";
    statusEl.className = "inline-status-box";
  }
  try {
    const res = await api("/api/v1/operations/refresh-all-metadata", "POST");
    showToast(res.message || "Запущено фоновое обновление метаданных");
    if (statusEl) {
      statusEl.textContent = res.message || (CURRENT_LANG === "en" ? "Update is running in background (see Background Tasks)" : "Обновление выполняется в фоновом режиме (см. Фоновые операции)");
    }
  } catch (e) {
    showToast(e.message || "Ошибка запуска обновления метаданных", "error");
    if (statusEl) {
      statusEl.textContent = e.message || (CURRENT_LANG === "en" ? "Error" : "Ошибка");
      statusEl.className = "inline-status-box error";
    }
  } finally {
    if (btn) btn.classList.remove("is-loading");
  }
}

function editMetadataSource(m) {
  EDITING_MD_ID = m.id;
  document.getElementById("md-form-title").textContent = `${t("common.edit")}: ${m.name}`;
  document.getElementById("md-name").value = m.name || "";
  const typeVal = (m.type && m.type.value) ? m.type.value : (m.type || "tmdb");
  document.getElementById("md-type").value = typeVal;
  document.getElementById("md-key").value = m.api_key || "";
  const pinEl = document.getElementById("md-pin");
  if (pinEl) {
    pinEl.value = (m.field_mapping && m.field_mapping.pin) || "";
  }
  const countries = (m.field_mapping && m.field_mapping.alias_countries) || [];
  document.querySelectorAll('#md-alias-countries input[type="checkbox"]').forEach(cb => {
    cb.checked = countries.includes(cb.value);
  });
  toggleCustomMetadataFields();
  clearInlineStatus("md-test-result");
  document.getElementById("md-submit-btn").textContent = t("common.save");
  document.getElementById("md-cancel-btn").style.display = "inline-block";
}

function resetMetadataSourceForm() {
  EDITING_MD_ID = null;
  document.getElementById("md-form-title").textContent = t("md.add_title");
  ["md-name", "md-key", "md-pin"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  document.querySelectorAll('#md-alias-countries input[type="checkbox"]').forEach(cb => cb.checked = false);
  document.getElementById("md-submit-btn").textContent = t("common.add");
  document.getElementById("md-cancel-btn").style.display = "none";
  clearInlineStatus("md-test-result");
  toggleCustomMetadataFields();
}

async function testMetadataSource(btn) {
  const name = document.getElementById("md-name").value.trim() || "TheTVDB / TMDB / Radarr";
  const type = document.getElementById("md-type").value;
  const isSkyhookOrRadarr = (type === "skyhook" || type === "radarr");
  const api_key = isSkyhookOrRadarr ? null : document.getElementById("md-key").value.trim();
  const pin = (document.getElementById("md-pin")?.value || "").trim();
  let field_mapping = {};
  if (pin) field_mapping.pin = pin;

  let baseUrl = null;
  if (type === "radarr") baseUrl = "https://api.radarr.video/v1";
  else if (type === "tmdb") baseUrl = "https://api.themoviedb.org/3";
  else if (type === "tvmaze") baseUrl = "https://api.tvmaze.com";
  else if (type === "thetvdb") baseUrl = "https://api4.thetvdb.com/v4";

  const payload = { name, type, base_url: baseUrl, api_key: api_key || null, field_mapping };
  await withLoading(btn, async () => {
    try {
      const res = await api("/api/v1/metadata-sources/test", { method: "POST", body: JSON.stringify(payload) });
      const msg = res.message || (res.success ? (CURRENT_LANG === "en" ? "Connection successful" : "Подключение успешно установлено") : (CURRENT_LANG === "en" ? "Connection failed" : "Ошибка подключения"));
      toast(msg, !res.success);
      showInlineStatus("md-test-result", msg, res.success);
    } catch (e) {
      const errMsg = (CURRENT_LANG === "en" ? "Test failed: " : "Ошибка проверки: ") + formatToastMessage(e.message);
      toast(errMsg, true);
      showInlineStatus("md-test-result", errMsg, false);
    }
  });
}

async function submitMetadataSource() {
  const name = document.getElementById("md-name").value.trim();
  const type = document.getElementById("md-type").value;
  const isSkyhookOrRadarr = (type === "skyhook" || type === "radarr");
  const api_key = isSkyhookOrRadarr ? null : document.getElementById("md-key").value.trim();
  const pin = (document.getElementById("md-pin")?.value || "").trim();
  
  const selectedCountries = isSkyhookOrRadarr
    ? []
    : Array.from(document.querySelectorAll('#md-alias-countries input[type="checkbox"]:checked')).map(cb => cb.value);
  let field_mapping = {};
  if (selectedCountries.length > 0) {
    field_mapping.alias_countries = selectedCountries;
  }
  if (pin) {
    field_mapping.pin = pin;
  }
  
  if (!name) {
    toast(CURRENT_LANG === "en" ? "Name required" : "Укажите название", true);
    return;
  }
  let baseUrl = null;
  if (type === "radarr") baseUrl = "https://api.radarr.video/v1";
  else if (type === "tmdb") baseUrl = "https://api.themoviedb.org/3";
  else if (type === "tvmaze") baseUrl = "https://api.tvmaze.com";
  else if (type === "thetvdb") baseUrl = "https://api4.thetvdb.com/v4";

  const payload = { name, type, base_url: baseUrl, api_key: api_key || null, field_mapping };
  try {
    if (EDITING_MD_ID) {
      await api(`/api/v1/metadata-sources/${EDITING_MD_ID}`, { method: "PUT", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    } else {
      await api("/api/v1/metadata-sources", { method: "POST", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    }
    resetMetadataSourceForm();
    await loadMetadataSources();
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + formatToastMessage(e.message), true);
  }
}

async function removeMetadataSource(id) {
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  await api(`/api/v1/metadata-sources/${id}`, { method: "DELETE" });
  loadMetadataSources();
}

// =============================================================================
// SETTINGS: NOTIFICATIONS
// =============================================================================

let EDITING_NT_ID = null;

function notificationTypeName(type) {
  const map = {
    telegram: "Telegram",
    discord: "Discord",
    gotify: "Gotify",
    ntfy: "Ntfy",
    pushover: "Pushover",
    slack: "Slack",
    webhook: "Webhook",
    email: "Email (SMTP)",
    pushbullet: "Pushbullet",
    apprise: "Apprise",
    script: "Custom Script",
  };
  return map[type] || type || "—";
}

function onNotificationTypeChange() {
  const type = document.getElementById("nt-type").value;
  const types = ["telegram", "discord", "gotify", "ntfy", "pushover", "slack", "webhook", "email", "pushbullet", "apprise", "script"];
  types.forEach(t => {
    const el = document.getElementById(`nt-fields-${t}`);
    if (el) el.style.display = t === type ? "" : "none";
  });
}

function collectNotificationSettingsFromForm() {
  const type = document.getElementById("nt-type").value;
  const settings = { include_app_name: document.getElementById("nt-include-app-name").checked };

  if (type === "telegram") {
    settings.bot_token = document.getElementById("nt-bot-token").value.trim();
    settings.chat_id = document.getElementById("nt-chat-id").value.trim();
    const threadId = document.getElementById("nt-telegram-thread-id").value.trim();
    if (threadId) settings.message_thread_id = threadId;
    settings.silent = document.getElementById("nt-telegram-silent").checked;
  } else if (type === "discord") {
    settings.webhook_url = document.getElementById("nt-discord-webhook-url").value.trim();
    settings.username = document.getElementById("nt-discord-username").value.trim();
    settings.avatar_url = document.getElementById("nt-discord-avatar-url").value.trim();
  } else if (type === "gotify") {
    settings.server_url = document.getElementById("nt-gotify-server-url").value.trim();
    settings.app_token = document.getElementById("nt-gotify-app-token").value.trim();
    settings.priority = Number(document.getElementById("nt-gotify-priority").value) || 5;
  } else if (type === "ntfy") {
    settings.server_url = document.getElementById("nt-ntfy-server-url").value.trim();
    settings.topic = document.getElementById("nt-ntfy-topic").value.trim();
    settings.access_token = document.getElementById("nt-ntfy-token").value.trim();
    settings.priority = document.getElementById("nt-ntfy-priority").value;
  } else if (type === "pushover") {
    settings.user_key = document.getElementById("nt-pushover-user-key").value.trim();
    settings.api_token = document.getElementById("nt-pushover-api-token").value.trim();
    settings.priority = Number(document.getElementById("nt-pushover-priority").value) || 0;
    settings.sound = document.getElementById("nt-pushover-sound").value.trim();
  } else if (type === "slack") {
    settings.webhook_url = document.getElementById("nt-slack-webhook-url").value.trim();
    settings.channel = document.getElementById("nt-slack-channel").value.trim();
  } else if (type === "webhook") {
    settings.webhook_url = document.getElementById("nt-webhook-url").value.trim();
    settings.http_method = document.getElementById("nt-webhook-method").value;
  } else if (type === "email") {
    settings.server = document.getElementById("nt-email-server").value.trim();
    settings.port = Number(document.getElementById("nt-email-port").value) || 587;
    settings.subject_prefix = document.getElementById("nt-email-subject-prefix").value.trim() || "[Aliasarr]";
    settings.from_address = document.getElementById("nt-email-from").value.trim();
    settings.to_address = document.getElementById("nt-email-to").value.trim();
    settings.username = document.getElementById("nt-email-username").value.trim();
    settings.password = document.getElementById("nt-email-password").value;
    settings.use_ssl = document.getElementById("nt-email-ssl").checked;
    settings.use_tls = document.getElementById("nt-email-tls").checked;
  } else if (type === "pushbullet") {
    settings.api_key = document.getElementById("nt-pushbullet-api-key").value.trim();
    settings.device_id = document.getElementById("nt-pushbullet-device-id").value.trim();
  } else if (type === "apprise") {
    settings.server_url = document.getElementById("nt-apprise-server-url").value.trim();
    settings.tag = document.getElementById("nt-apprise-tag").value.trim();
    settings.urls = document.getElementById("nt-apprise-urls").value.trim();
  } else if (type === "script") {
    settings.path = document.getElementById("nt-script-path").value.trim();
    settings.arguments = document.getElementById("nt-script-args").value.trim();
  }

  return settings;
}

async function loadNotifications() {
  const tbody = document.querySelector("#nt-table tbody");
  try {
    const items = await api("/api/v1/notifications");
    tbody.innerHTML = items.map(n => `
      <tr>
        <td><strong>${escapeHtml(n.name)}</strong></td>
        <td>${escapeHtml(notificationTypeName(n.type))}</td>
        <td>
          <span class="status-pill ${n.enabled !== false ? 'status-downloaded' : 'status-unmonitored'}"
                style="cursor:pointer; user-select:none;"
                onclick="toggleNotificationStatus(this, ${n.id}, ${n.enabled !== false})"
                title="${CURRENT_LANG === 'en' ? 'Click to toggle' : 'Нажмите для переключения'}">
            <i data-lucide="${n.enabled !== false ? 'check-circle' : 'circle'}" class="ico-xs"></i> ${n.enabled !== false ? t('nt.status_enabled') : t('nt.status_disabled')}
          </span>
        </td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-only" title="Test" onclick="testNotification(this, ${n.id})"><i data-lucide="send" class="ico-sm"></i></button>
            <button class="btn-icon-only" title="${t("common.edit")}" onclick='editNotification(${JSON.stringify(n).replace(/'/g, "&apos;")})'><i data-lucide="edit-2" class="ico-sm"></i></button>
            <button class="btn-icon-only danger" title="${t("common.delete")}" onclick="removeNotification(${n.id})"><i data-lucide="trash-2" class="ico-sm"></i></button>
          </div>
        </td>
      </tr>`).join("") || `<tr><td colspan="4" style="color:var(--text-muted)">—</td></tr>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {}
}

async function toggleNotificationStatus(button, id, currentlyEnabled) {
  try {
    const items = await api("/api/v1/notifications");
    const item = items.find(x => x.id === id);
    if (!item) return;
    await api(`/api/v1/notifications/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        name: item.name,
        type: item.type,
        settings: item.settings,
        on_grab: item.on_grab,
        on_import: item.on_import,
        on_upgrade: item.on_upgrade,
        on_rename: item.on_rename,
        on_series_add: item.on_series_add,
        on_series_delete: item.on_series_delete,
        on_episode_file_delete: item.on_episode_file_delete,
        on_episode_file_delete_for_upgrade: item.on_episode_file_delete_for_upgrade,
        on_health_issue: item.on_health_issue,
        on_health_restored: item.on_health_restored,
        on_application_update: item.on_application_update,
        on_manual_interaction_required: item.on_manual_interaction_required,
        on_backup: item.on_backup,
        enabled: !currentlyEnabled,
      }),
    });
    toast(t("settings.toast_saved"));
    loadNotifications();
  } catch (e) {
    toast("Ошибка: " + e.message, true);
  }
}

function editNotification(n) {
  EDITING_NT_ID = n.id;
  document.getElementById("nt-form-title").textContent = `${t("common.edit")}: ${n.name}`;
  document.getElementById("nt-name").value = n.name;
  document.getElementById("nt-type").value = n.type;
  onNotificationTypeChange();
  const s = n.settings || {};

  // Telegram
  document.getElementById("nt-bot-token").value = s.bot_token || "";
  document.getElementById("nt-chat-id").value = s.chat_id || "";
  document.getElementById("nt-telegram-thread-id").value = s.message_thread_id || s.topic_id || "";
  document.getElementById("nt-telegram-silent").checked = !!s.silent;

  // Discord
  document.getElementById("nt-discord-webhook-url").value = s.webhook_url || "";
  document.getElementById("nt-discord-username").value = s.username || "";
  document.getElementById("nt-discord-avatar-url").value = s.avatar_url || "";

  // Gotify
  document.getElementById("nt-gotify-server-url").value = s.server_url || "";
  document.getElementById("nt-gotify-app-token").value = s.app_token || "";
  document.getElementById("nt-gotify-priority").value = s.priority ?? 5;

  // Ntfy
  document.getElementById("nt-ntfy-server-url").value = s.server_url || "https://ntfy.sh";
  document.getElementById("nt-ntfy-topic").value = s.topic || "";
  document.getElementById("nt-ntfy-token").value = s.access_token || "";
  document.getElementById("nt-ntfy-priority").value = s.priority || "3";

  // Pushover
  document.getElementById("nt-pushover-user-key").value = s.user_key || "";
  document.getElementById("nt-pushover-api-token").value = s.api_token || "";
  document.getElementById("nt-pushover-priority").value = s.priority ?? 0;
  document.getElementById("nt-pushover-sound").value = s.sound || "";

  // Slack
  document.getElementById("nt-slack-webhook-url").value = s.webhook_url || "";
  document.getElementById("nt-slack-channel").value = s.channel || "";

  // Webhook
  document.getElementById("nt-webhook-url").value = s.webhook_url || "";
  document.getElementById("nt-webhook-method").value = s.http_method || "POST";

  // Email
  const emailServer = document.getElementById("nt-email-server");
  if (emailServer) emailServer.value = s.server || "";
  const emailPort = document.getElementById("nt-email-port");
  if (emailPort) emailPort.value = s.port || 587;
  const emailSubject = document.getElementById("nt-email-subject-prefix");
  if (emailSubject) emailSubject.value = s.subject_prefix || "[Aliasarr]";
  const emailFrom = document.getElementById("nt-email-from");
  if (emailFrom) emailFrom.value = s.from_address || "";
  const emailTo = document.getElementById("nt-email-to");
  if (emailTo) emailTo.value = s.to_address || "";
  const emailUser = document.getElementById("nt-email-username");
  if (emailUser) emailUser.value = s.username || "";
  const emailPass = document.getElementById("nt-email-password");
  if (emailPass) emailPass.value = s.password || "";
  const emailSsl = document.getElementById("nt-email-ssl");
  if (emailSsl) emailSsl.checked = !!s.use_ssl;
  const emailTls = document.getElementById("nt-email-tls");
  if (emailTls) emailTls.checked = s.use_tls !== false;

  // Pushbullet
  const pbKey = document.getElementById("nt-pushbullet-api-key");
  if (pbKey) pbKey.value = s.api_key || "";
  const pbDev = document.getElementById("nt-pushbullet-device-id");
  if (pbDev) pbDev.value = s.device_id || s.device_iden || "";

  // Apprise
  const appriseServer = document.getElementById("nt-apprise-server-url");
  if (appriseServer) appriseServer.value = s.server_url || "";
  const appriseTag = document.getElementById("nt-apprise-tag");
  if (appriseTag) appriseTag.value = s.tag || "";
  const appriseUrls = document.getElementById("nt-apprise-urls");
  if (appriseUrls) appriseUrls.value = s.urls || "";

  // Script
  const scriptPath = document.getElementById("nt-script-path");
  if (scriptPath) scriptPath.value = s.path || "";
  const scriptArgs = document.getElementById("nt-script-args");
  if (scriptArgs) scriptArgs.value = s.arguments || "";

  // Common & Triggers
  document.getElementById("nt-enabled").checked = n.enabled !== false;
  document.getElementById("nt-include-app-name").checked = !!s.include_app_name;
  document.getElementById("nt-on-grab").checked = n.on_grab !== false;
  document.getElementById("nt-on-import").checked = n.on_import !== false;
  const elUpgrade = document.getElementById("nt-on-upgrade");
  if (elUpgrade) elUpgrade.checked = n.on_upgrade !== false;
  const elRename = document.getElementById("nt-on-rename");
  if (elRename) elRename.checked = !!n.on_rename;
  const elSeriesAdd = document.getElementById("nt-on-series-add");
  if (elSeriesAdd) elSeriesAdd.checked = !!n.on_series_add;
  const elSeriesDel = document.getElementById("nt-on-series-delete");
  if (elSeriesDel) elSeriesDel.checked = !!n.on_series_delete;
  const elEpDel = document.getElementById("nt-on-episode-file-delete");
  if (elEpDel) elEpDel.checked = !!n.on_episode_file_delete;
  const elBackup = document.getElementById("nt-on-backup");
  if (elBackup) elBackup.checked = !!n.on_backup;

  document.getElementById("nt-submit-btn").textContent = t("common.save");
}

function resetNotificationForm() {
  EDITING_NT_ID = null;
  document.getElementById("nt-form-title").textContent = t("notifications.add_title");
  document.getElementById("nt-name").value = "";
  document.getElementById("nt-type").value = "telegram";
  onNotificationTypeChange();

  document.getElementById("nt-bot-token").value = "";
  document.getElementById("nt-chat-id").value = "";
  document.getElementById("nt-telegram-thread-id").value = "";
  document.getElementById("nt-telegram-silent").checked = false;

  document.getElementById("nt-discord-webhook-url").value = "";
  document.getElementById("nt-discord-username").value = "";
  document.getElementById("nt-discord-avatar-url").value = "";

  document.getElementById("nt-gotify-server-url").value = "";
  document.getElementById("nt-gotify-app-token").value = "";
  document.getElementById("nt-gotify-priority").value = 5;

  document.getElementById("nt-ntfy-server-url").value = "https://ntfy.sh";
  document.getElementById("nt-ntfy-topic").value = "";
  document.getElementById("nt-ntfy-token").value = "";
  document.getElementById("nt-ntfy-priority").value = "3";

  document.getElementById("nt-pushover-user-key").value = "";
  document.getElementById("nt-pushover-api-token").value = "";
  document.getElementById("nt-pushover-priority").value = 0;
  document.getElementById("nt-pushover-sound").value = "";

  document.getElementById("nt-slack-webhook-url").value = "";
  document.getElementById("nt-slack-channel").value = "";

  document.getElementById("nt-webhook-url").value = "";
  document.getElementById("nt-webhook-method").value = "POST";

  // Email
  const emailServer = document.getElementById("nt-email-server");
  if (emailServer) emailServer.value = "";
  const emailPort = document.getElementById("nt-email-port");
  if (emailPort) emailPort.value = "587";
  const emailSubject = document.getElementById("nt-email-subject-prefix");
  if (emailSubject) emailSubject.value = "[Aliasarr]";
  const emailFrom = document.getElementById("nt-email-from");
  if (emailFrom) emailFrom.value = "";
  const emailTo = document.getElementById("nt-email-to");
  if (emailTo) emailTo.value = "";
  const emailUser = document.getElementById("nt-email-username");
  if (emailUser) emailUser.value = "";
  const emailPass = document.getElementById("nt-email-password");
  if (emailPass) emailPass.value = "";
  const emailSsl = document.getElementById("nt-email-ssl");
  if (emailSsl) emailSsl.checked = false;
  const emailTls = document.getElementById("nt-email-tls");
  if (emailTls) emailTls.checked = true;

  // Pushbullet
  const pbKey = document.getElementById("nt-pushbullet-api-key");
  if (pbKey) pbKey.value = "";
  const pbDev = document.getElementById("nt-pushbullet-device-id");
  if (pbDev) pbDev.value = "";

  // Apprise
  const appriseServer = document.getElementById("nt-apprise-server-url");
  if (appriseServer) appriseServer.value = "";
  const appriseTag = document.getElementById("nt-apprise-tag");
  if (appriseTag) appriseTag.value = "";
  const appriseUrls = document.getElementById("nt-apprise-urls");
  if (appriseUrls) appriseUrls.value = "";

  // Script
  const scriptPath = document.getElementById("nt-script-path");
  if (scriptPath) scriptPath.value = "";
  const scriptArgs = document.getElementById("nt-script-args");
  if (scriptArgs) scriptArgs.value = "";

  document.getElementById("nt-enabled").checked = true;
  document.getElementById("nt-include-app-name").checked = false;
  document.getElementById("nt-on-grab").checked = true;
  document.getElementById("nt-on-import").checked = true;
  const elUpgrade = document.getElementById("nt-on-upgrade");
  if (elUpgrade) elUpgrade.checked = true;
  const elRename = document.getElementById("nt-on-rename");
  if (elRename) elRename.checked = false;
  const elSeriesAdd = document.getElementById("nt-on-series-add");
  if (elSeriesAdd) elSeriesAdd.checked = false;
  const elSeriesDel = document.getElementById("nt-on-series-delete");
  if (elSeriesDel) elSeriesDel.checked = false;
  const elEpDel = document.getElementById("nt-on-episode-file-delete");
  if (elEpDel) elEpDel.checked = false;
  const elBackup = document.getElementById("nt-on-backup");
  if (elBackup) elBackup.checked = false;

  clearInlineStatus("nt-test-result");
  document.getElementById("nt-submit-btn").textContent = t("common.save");
}

async function submitNotification() {
  const name = document.getElementById("nt-name").value.trim();
  const type = document.getElementById("nt-type").value;
  if (!name) { toast(CURRENT_LANG === "en" ? "Specify notification name" : "Укажите название", true); return; }
  const settings = collectNotificationSettingsFromForm();
  const payload = {
    name, type, settings,
    enabled: document.getElementById("nt-enabled").checked,
    on_grab: document.getElementById("nt-on-grab").checked,
    on_import: document.getElementById("nt-on-import").checked,
    on_upgrade: document.getElementById("nt-on-upgrade") ? document.getElementById("nt-on-upgrade").checked : true,
    on_rename: document.getElementById("nt-on-rename") ? document.getElementById("nt-on-rename").checked : false,
    on_series_add: document.getElementById("nt-on-series-add") ? document.getElementById("nt-on-series-add").checked : false,
    on_series_delete: document.getElementById("nt-on-series-delete") ? document.getElementById("nt-on-series-delete").checked : false,
    on_episode_file_delete: document.getElementById("nt-on-episode-file-delete") ? document.getElementById("nt-on-episode-file-delete").checked : false,
    on_backup: document.getElementById("nt-on-backup") ? document.getElementById("nt-on-backup").checked : false,
  };
  try {
    if (EDITING_NT_ID) {
      await api(`/api/v1/notifications/${EDITING_NT_ID}`, { method: "PUT", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    } else {
      await api("/api/v1/notifications", { method: "POST", body: JSON.stringify(payload) });
      toast(t("settings.toast_saved"));
    }
    resetNotificationForm();
    loadNotifications();
  } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
}

async function testNotificationAdhoc(button) {
  const type = document.getElementById("nt-type").value;
  const settings = collectNotificationSettingsFromForm();
  await withLoading(button, async () => {
    try {
      const result = await api("/api/v1/notifications/test", { method: "POST", body: JSON.stringify({ type, settings }) });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Test notification sent" : "Тестовое уведомление отправлено") : (CURRENT_LANG === "en" ? "Failed to send notification" : "Ошибка отправки уведомления"));
      toast(msg, !result.success);
      showInlineStatus("nt-test-result", msg, result.success);
    } catch (e) {
      const errMsg = (CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message;
      toast(errMsg, true);
      showInlineStatus("nt-test-result", errMsg, false);
    }
  });
}

async function testNotification(button, id) {
  await withLoading(button, async () => {
    try {
      const result = await api(`/api/v1/notifications/${id}/test`, { method: "POST" });
      const msg = result.message || (result.success ? (CURRENT_LANG === "en" ? "Test notification sent" : "Тестовое уведомление отправлено") : (CURRENT_LANG === "en" ? "Failed to send notification" : "Ошибка отправки уведомления"));
      toast(msg, !result.success);
    } catch (e) { toast((CURRENT_LANG === "en" ? "Error: " : "Ошибка: ") + e.message, true); }
  });
}

async function removeNotification(id) {
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  await api(`/api/v1/notifications/${id}`, { method: "DELETE" });
  loadNotifications();
}

function loadAllSettings() {
  const hasSettings = hasPermission("manage_settings");
  const hasUsers = hasPermission("manage_users");
  const hasIndexers = hasPermission("manage_indexers");
  const hasDownloaders = hasPermission("manage_downloaders");

  const visibleButtons = Array.from(document.querySelectorAll("#tab-settings .settings-tabs .settings-tab-btn"))
    .filter(btn => btn.style.display !== "none");

  const activeBtn = document.querySelector("#tab-settings .settings-tabs .settings-tab-btn.active");
  if (!activeBtn || activeBtn.style.display === "none") {
    if (visibleButtons.length > 0) {
      visibleButtons[0].click();
      return;
    }
  }

  if (hasSettings) {
    loadGeneralSettings();
    loadSecuritySettings();
    loadQualityProfiles();
    loadMetadataSources();
    loadNotifications();
  }
  if (hasUsers) loadUsers();
  if (hasIndexers) loadIndexers();
  if (hasDownloaders) loadDownloadClients();
}

// ---------- СОБЫТИЯ ----------
const EVENTS_STATE = { page: 1, sort: "desc" };

function toggleEventsSort() {
  EVENTS_STATE.sort = EVENTS_STATE.sort === "desc" ? "asc" : "desc";
  document.getElementById("events-sort-btn").textContent = (CURRENT_LANG === "en" ? "Time " : "Время ") + (EVENTS_STATE.sort === "desc" ? "↓" : "↑");
  loadEvents(1);
}

function eventLevelLabel(level) {
  if (CURRENT_LANG === "en") {
    return { info: "Info", warning: "Warning", error: "Error", debug: "Debug" }[level] || level;
  }
  return { info: "Информация", warning: "Предупреждение", error: "Ошибка", debug: "Debug" }[level] || level;
}

function translateLogMessage(msg) {
  if (!msg || CURRENT_LANG !== "en") return msg;
  let s = String(msg);

  // Exact phrases for tasks & statuses
  const exactMap = {
    "Все задачи завершены": "All tasks completed",
    "Нет активных задач": "No active tasks",
    "Опрос трекеров и сопоставление алиасов...": "Querying indexers and matching aliases...",
    "Подходящих релизов не найдено": "No suitable releases found",
    "Поиск завершён: подходящих релизов не найдено": "Search completed: no suitable releases found",
    "Поиск завершён: новых релизов не обнаружено": "Search completed: no new releases found",
    "Проверка библиотеки...": "Checking library...",
    "Подготовка к импорту...": "Preparing import...",
    "Поиск локальных файлов на диске...": "Scanning local disk for files...",
    "Сбор данных и упаковка...": "Collecting data and packing...",
    "Применение данных...": "Applying data...",
    "Восстановление успешно завершено": "Restore completed successfully",
    "Опрос торрент-клиентов...": "Polling torrent clients...",
    "Нет завершённых загрузок для импорта": "No completed downloads for import",
    "Обновление метаданных всей библиотеки": "Update metadata for entire library",
    "Подготовка списка тайтлов...": "Preparing title list...",
    "Проверка отслеживаемых раздач": "Check tracked releases",
    "Опрос трекеров...": "Polling indexers...",
    "Нет активных раздач для проверки": "No active releases to check",
    "Автопоиск разыскиваемых релизов (Wanted)": "Auto-search wanted releases (Wanted)",
    "Поиск отсутствующих в календаре": "Search missing in calendar",
    "Проверка загрузок (Download Client)": "Check downloads (Download Client)",
  };
  if (exactMap[s.trim()]) return exactMap[s.trim()];

  // Scheduler startup and cron logs
  s = s.replace(/^Планировщик запущен:\s*поиск wanted каждые (\d+) мин,\s*загрузки каждые (\d+) сек,\s*слежение за раздачами каждые (\d+) мин,\s*активация премьер каждые (\d+) мин,\s*проверка индексаторов каждые (\d+) мин/g,
    'Scheduler started: wanted search every $1 min, downloads every $2 sec, tracked releases check every $3 min, premiere activation every $4 min, indexer check every $5 min');
  s = s.replace(/^Планировщик:\s*регулярное обновление метаданных библиотеки \(каждые (\d+) ч\.\)/g, 'Scheduler: regular library metadata refresh (every $1 h)');
  s = s.replace(/^Планировщик:\s*опрос дат выхода невышедших релизов \(каждые (\d+) ч\.\)/g, 'Scheduler: poll unreleased release dates (every $1 h)');
  s = s.replace(/^Планировщик:\s*авто-продление SSL сертификатов \(каждые (\d+) ч\.\)/g, 'Scheduler: auto-renew SSL certificates (every $1 h)');
  s = s.replace(/^Планировщик:\s*автоматическое создание бэкапов библиотеки \(каждые (\d+) дн\.\)/g, 'Scheduler: automatic library backups (every $1 days)');

  // Release Search & Match Logs
  s = s.replace(/^Поиск по алиасам \((.*?)\) в (\d+) трекерах:\s*найдено (\d+) подходящих кандидатов/g, 'Search by aliases ($1) across $2 trackers: found $3 matching candidates');
  s = s.replace(/^Релиз успешно захвачен для фильма «(.*?)»(.*?) и передан в '(.*?)' \(хэш:\s*(.*?), сиды:\s*(\d+), качество:\s*(.*?)\)/g, 'Release successfully grabbed for movie "$1"$2 and sent to \'$3\' (hash: $4, seeders: $5, quality: $6)');
  s = s.replace(/^Релиз успешно захвачен и передан в '(.*?)' \(хэш:\s*(.*?)\)\.\s*Закрывает серии:\s*(.*)/g, 'Release successfully grabbed and sent to \'$1\' (hash: $2). Covers episodes: $3');
  s = s.replace(/^Спецвыпуск «(.*?)» для «(.*?)» скачан на 100% и ожидает ручного импорта\./g, 'Special episode "$1" for "$2" is 100% downloaded and awaiting manual import.');
  s = s.replace(/^Импорт завершен:\s*обработано (\d+) файл\(ов\) для «(.*?)»/g, 'Import completed: processed $1 file(s) for "$2"');
  s = s.replace(/^Импорт завершён:\s*обработано (\d+) файл\(ов\) для «(.*?)»/g, 'Import completed: processed $1 file(s) for "$2"');
  s = s.replace(/^Ошибка отправки релиза в загрузчик '(.*?)':\s*(.*)/g, 'Error sending release to download client \'$1\': $2');

  // Background Task Titles & dynamic progress messages
  s = s.replace(/^Поиск релизов:\s*(.*)/g, 'Release search: $1');
  s = s.replace(/^Ручной импорт:\s*(.*)/g, 'Manual import: $1');
  s = s.replace(/^Импорт и перенос:\s*(.*)/g, 'Import and transfer: $1');
  s = s.replace(/^Пересканирование файлов:\s*(.*)/g, 'Rescanning files: $1');
  s = s.replace(/^Создание бэкапа \((.*?)\)/g, 'Backup creation ($1)');
  s = s.replace(/^Восстановление бэкапа:\s*(.*)/g, 'Backup restore: $1');
  s = s.replace(/^Подготовка к поиску для (\d+) тайтлов\.\.\./g, 'Preparing search for $1 titles...');
  s = s.replace(/^Поиск \((\d+)\/(\d+)\):\s*«(.*?)»\.\.\./g, 'Searching ($1/$2): "$3"...');
  s = s.replace(/^Обработка \((\d+)\/(\d+)\):\s*«(.*?)»\.\.\./g, 'Processing ($1/$2): "$3"...');
  s = s.replace(/^Поиск для (\d+) тайтлов с разыскиваемыми сериями\.\.\./g, 'Searching for $1 titles with wanted episodes...');
  s = s.replace(/^Подготовка к импорту (\d+) файлов\.\.\./g, 'Preparing import of $1 files...');
  s = s.replace(/^Завершено:\s*захвачено (\d+) релиз\(ов\)/g, 'Completed: grabbed $1 release(s)');
  s = s.replace(/^Захвачено (\d+) релиз\(ов\)/g, 'Grabbed $1 release(s)');
  s = s.replace(/^Успешно импортировано:\s*(\d+)\s*файл\(ов\)/g, 'Successfully imported: $1 file(s)');
  s = s.replace(/^Импортировано:\s*(\d+)\s*файл\(ов\)/g, 'Imported: $1 file(s)');
  s = s.replace(/^Импортировано:\s*(\d+)\s*из\s*(\d+)\s*\(ошибок:\s*(\d+)\)/g, 'Imported $1 of $2 (errors: $3)');
  s = s.replace(/^Сканирование завершено:\s*найдено (\d+) файл\(ов\)/g, 'Scan completed: found $1 file(s)');
  s = s.replace(/^Резервная копия создана:\s*(.*)/g, 'Backup created: $1');
  s = s.replace(/^Обработано завершённых релизов:\s*(\d+)/g, 'Processed completed releases: $1');
  s = s.replace(/^Обновление \[(\d+)\/(\d+)\]:\s*«(.*?)»/g, 'Updating [$1/$2]: "$3"');
  s = s.replace(/^Метаданные обновлены для (\d+) из (\d+) тайтлов/g, 'Metadata updated for $1 of $2 titles');
  s = s.replace(/^Проверено раздач:\s*(\d+),\s*обновлено:\s*(\d+)/g, 'Checked releases: $1, updated: $2');
  s = s.replace(/^Перемещение и переименование файлов для «(.*?)»\.\.\./g, 'Moving and renaming files for "$1"...');

  // Torrent files filtering & indexer checks
  s = s.replace(/^Раздача (.*?):\s*скачивание ограничено выбранными сериями \((\d+) шт\),\s*отключено файлов:\s*(\d+),\s*включено:\s*(\d+)/g, 'Torrent $1: download filtered to selected episodes ($2 items), disabled files: $3, enabled: $4');
  s = s.replace(/^Раздача (.*?):\s*выбрано серий (\d+) из (\d+) файлов \(остальные (\d+) файлов отключены\)/g, 'Torrent $1: selected episodes $2 of $3 files (remaining $4 files disabled)');
  s = s.replace(/^Раздача (.*?):\s*скачивание ограничено выбранными сериями,\s*отключено файлов:\s*(\d+),\s*включено:\s*(\d+)/g, 'Torrent $1: download filtered to selected episodes, disabled files: $2, enabled: $3');
  s = s.replace(/^Проверка индексатора (.*?):\s*доступен/g, 'Indexer check $1: available');
  s = s.replace(/^Проверка индексатора (.*?):\s*недоступен \(попыток:\s*(\d+),\s*подряд сбоев:\s*(\d+)\)/g, 'Indexer check $1: unavailable (attempts: $2, consecutive failures: $3)');
  s = s.replace(/^Индексатор «(.*?)» доступен \(проверка вручную, попыток:\s*(\d+)\)/g, 'Indexer "$1" is available (manual check, attempts: $2)');
  s = s.replace(/^Индексатор «(.*?)» недоступен после (\d+) попыток.*/g, 'Indexer "$1" is unavailable after $2 attempts');
  s = s.replace(/^Индексатор «(.*?)» снова доступен/g, 'Indexer "$1" is available again');
  s = s.replace(/^Индексатор (.*?) недоступен:\s*(.*)/g, 'Indexer $1 is unavailable: $2');

  // Backups, migrations, auth, system
  s = s.replace(/^Создана резервная копия настроек:\s*(.*)/g, 'Settings backup created: $1');
  s = s.replace(/^Настройки восстановлены из резервной копии\s*(.*)/g, 'Settings restored from backup $1');
  s = s.replace(/^DB-миграция: добавлена колонка\s*(.*)/g, 'DB migration: added column $1');
  s = s.replace(/^DB-миграция: не удалось добавить\s*(.*)/g, 'DB migration: failed to add $1');
  s = s.replace(/^Созданы источники метаданных по умолчанию:\s*(.*)/g, 'Default metadata sources created: $1');
  s = s.replace(/^Ошибка инициализации источников метаданных по умолчанию:\s*(.*)/g, 'Error initializing default metadata sources: $1');
  s = s.replace(/^Пароль администратора успешно обновлён из переменной окружения ALIASARR_ADMIN_PASSWORD/g, 'Admin password successfully updated from ALIASARR_ADMIN_PASSWORD environment variable');
  s = s.replace(/^Пароль администратора успешно сброшен из файла\s*(.*)/g, 'Admin password successfully reset from file $1');
  s = s.replace(/^Не удалось сбросить пароль из (.*?):\s*(.*)/g, 'Failed to reset password from $1: $2');
  s = s.replace(/^Ошибка инициализации SSL сертификата:\s*(.*)/g, 'Error initializing SSL certificate: $1');
  s = s.replace(/^Системный API-ключ инициализирован \(источник:\s*(.*?)\)/g, 'System API key initialized (source: $1)');
  s = s.replace(/^Системный API-ключ инициализирован \(секрет скрыт\)/g, 'System API key initialized (secret hidden)');
  s = s.replace(/^API-ключ \(из (.*?)\):\s*(.*)/g, 'API key (from $1): $2');
  s = s.replace(/^Заголовок для запросов к \/api\/v1\/\*:\s*(.*)/g, 'Header for requests to /api/v1/*: $1');
  s = s.replace(/^Проверка отслеживаемых раздач:\s*обнаружено (\d+) обновлений/g, 'Tracked releases check: found $1 updates');
  s = s.replace(/^Проверка отслеживаемых раздач:\s*проверено (\d+), обновлений нет/g, 'Tracked releases check: checked $1, no updates');
  s = s.replace(/^Проверка отслеживаемых раздач:\s*(.*)/g, 'Tracked releases check: $1');
  s = s.replace(/^Авто-поиск wanted-серий:\s*захвачено для (\d+) видео/g, 'Auto-search wanted episodes: grabbed for $1 video(s)');
  s = s.replace(/^Переведено в 'разыскивается' серий\/фильмов:\s*(\d+)/g, 'Moved to "wanted" status (episodes/movies): $1');
  s = s.replace(/^Проверка загрузок:\s*обработано завершённых торрентов —\s*(\d+)/g, 'Downloads check: processed completed torrents — $1');
  s = s.replace(/^Журнал:\s*удалено устаревших записей \(старше (\d+) дн\.\):\s*(\d+)/g, 'Journal: purged old entries (older than $1 days): $2');
  s = s.replace(/^Не удалось обновить дату выхода для видео (.*?):\s*(.*)/g, 'Failed to update release date for video $1: $2');
  s = s.replace(/^Опрос дат выхода:\s*обновлено видео —\s*(\d+)/g, 'Release dates poll: updated videos — $1');
  s = s.replace(/^Ошибка авто-продления SSL сертификата:\s*(.*)/g, 'Error auto-renewing SSL certificate: $1');
  s = s.replace(/^Не удалось возобновить раздачу (.*?):\s*(.*)/g, 'Failed to resume torrent $1: $2');
  s = s.replace(/^Нет доступного download client для видео\s*(.*)/g, 'No available download client for video $1');
  s = s.replace(/^Не удалось отправить релиз в download client:\s*(.*)/g, 'Failed to send release to download client: $1');
  s = s.replace(/^Не удалось ограничить файлы раздачи по сериям:\s*(.*)/g, 'Failed to filter torrent files by episode: $1');
  s = s.replace(/^Не удалось получить список торрентов у (.*?):\s*(.*)/g, 'Failed to get torrent list from $1: $2');
  s = s.replace(/^Не удалось отправить уведомление об импорте:\s*(.*)/g, 'Failed to send import notification: $1');
  s = s.replace(/^Неизвестный тип уведомлений:\s*(.*)/g, 'Unknown notification type: $1');
  s = s.replace(/^Не удалось отправить уведомление (.*?):\s*(.*)/g, 'Failed to send notification $1: $2');
  s = s.replace(/^Не удалось открыть сессию БД для уведомлений:\s*(.*)/g, 'Failed to open DB session for notifications: $1');
  s = s.replace(/^Ошибка при получении конфигурации уведомлений:\s*(.*)/g, 'Error retrieving notification configuration: $1');
  s = s.replace(/^Самоподписанный SSL-сертификат Aliasarr успешно создан на (\d+) дней:\s*(.*)/g, 'Aliasarr self-signed SSL certificate created for $1 days: $2');
  s = s.replace(/^Библиотека cryptography не найдена, используем системный openssl/g, 'Cryptography library not found, using system openssl');
  s = s.replace(/^Не удалось распарсить сертификат через cryptography:\s*(.*)/g, 'Failed to parse certificate via cryptography: $1');
  s = s.replace(/^Ошибка чтения SSL сертификата (.*?):\s*(.*)/g, 'Error reading SSL certificate $1: $2');
  s = s.replace(/^Выпуск нового самоподписанного SSL-сертификата Aliasarr\.\.\./g, 'Issuing new Aliasarr self-signed SSL certificate...');
  s = s.replace(/^SSL-сертификат протухает \(осталось (\d+) дней\)\.\s*Автоматический самовыпуск\.\.\./g, 'SSL certificate expiring in $1 days. Auto-renewing...');
  s = s.replace(/^Запущена задача \[([^\]]+)\] (.*?):\s*(.*)/g, 'Started task [$1] $2: $3');
  s = s.replace(/^Завершена задача \[([^\]]+)\] (.*?):\s*(.*)/g, 'Finished task [$1] $2: $3');
  s = s.replace(/^Ошибка в задаче \[([^\]]+)\] (.*?):\s*(.*)/g, 'Error in task [$1] $2: $3');
  s = s.replace(/^Глобальный ручной импорт/g, 'Global manual import');
  s = s.replace(/^Импорт (\d+) файлов\.\.\./g, 'Importing $1 files...');
  s = s.replace(/^Ошибка при импорте шоу \(external_id=(.*?)\):\s*(.*)/g, 'Error importing show (external_id=$1): $2');
  s = s.replace(/^Ошибка автопоиска для видео\s*(.*?):\s*(.*)/g, 'Auto-search error for video $1: $2');
  s = s.replace(/^Ошибка постобработки для видео\s*(.*?):\s*(.*)/g, 'Post-processing error for video $1: $2');

  // Sub-strings / keywords replacement
  s = s.replace(/Автопоиск wanted-серий/g, 'Wanted auto-search');
  s = s.replace(/поиск новых серий/g, 'searching new episodes');
  s = s.replace(/успешно выполнено/g, 'completed successfully');
  s = s.replace(/завершено/g, 'completed');
  s = s.replace(/Проверка загрузок/g, 'Check downloads');
  s = s.replace(/Проверка раздач/g, 'Check torrents');
  s = s.replace(/Опрос дат выхода/g, 'Poll air dates');
  s = s.replace(/Проверка индексаторов/g, 'Check indexers');
  s = s.replace(/Очистка журнала/g, 'Purge journal');
  s = s.replace(/Ручной поиск/g, 'Manual search');
  s = s.replace(/Импорт файла/g, 'Import file');
  s = s.replace(/Синхронизация/g, 'Sync');
  s = s.replace(/Обновление метаданных/g, 'Update metadata');

  return s;
}

async function loadEvents(page) {
  if (page) EVENTS_STATE.page = page;
  const level = document.getElementById("events-level-filter").value;
  const pageSize = Number(document.getElementById("events-page-size").value) || 50;
  const tbody = document.querySelector("#events-table tbody");
  try {
    const data = await api(`/api/v1/events?level=${level}&page=${EVENTS_STATE.page}&page_size=${pageSize}&sort=${EVENTS_STATE.sort}`);
    tbody.innerHTML = data.items.map(ev => `
      <tr>
        <td class="mono col-time" style="font-size:11.5px; white-space:nowrap;">${formatDateTZ(ev.created_at)}</td>
        <td class="col-comp" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"><strong>${escapeHtml(ev.component)}</strong></td>
        <td class="col-msg" style="word-break:break-word; overflow-wrap:anywhere; white-space:normal; line-height:1.45;"><span class="status-pill status-${ev.level === "error" ? "missing" : ev.level === "warning" ? "unaired" : "downloaded"}" style="margin-right:8px; vertical-align:middle;">${eventLevelLabel(ev.level)}</span><span style="vertical-align:middle;">${escapeHtml(translateLogMessage(ev.message))}</span></td>
      </tr>`).join("") || `<tr><td colspan="3" style="color:var(--text-muted)">—</td></tr>`;
    renderPagination("events-pagination", EVENTS_STATE.page, pageSize, data.total, loadEvents);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="3" style="color:var(--danger)">${CURRENT_LANG === "en" ? "Loading error:" : "Ошибка загрузки:"} ${escapeHtml(e.message)}</td></tr>`;
  }
}

function renderPagination(containerId, page, pageSize, total, loadFn) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) { el.innerHTML = ""; return; }
  el.innerHTML = `
    <button class="btn btn-secondary btn-small" ${page <= 1 ? "disabled" : ""} onclick="(${loadFn.name})(${page - 1})">‹ ${t("common.prev")}</button>
    <span class="hint" style="margin:0 10px;">${t("common.page")} ${page} ${t("common.of")} ${totalPages} (${t("common.total")} ${total})</span>
    <button class="btn btn-secondary btn-small" ${page >= totalPages ? "disabled" : ""} onclick="(${loadFn.name})(${page + 1})">${t("common.next")} ›</button>
  `;
}

// ---------- ЖУРНАЛ ----------
const JOURNAL_STATE = { page: 1 };

async function loadJournal(page) {
  if (page) JOURNAL_STATE.page = page;
  const level = document.getElementById("journal-level-filter").value;
  const tbody = document.querySelector("#journal-table tbody");
  try {
    const data = await api(`/api/v1/journal?level=${level}&page=${JOURNAL_STATE.page}&page_size=100&sort=desc`);
    tbody.innerHTML = data.items.map(ev => `
      <tr>
        <td class="mono col-time">${formatDateTZ(ev.created_at)}</td>
        <td class="col-level"><span class="status-pill status-${ev.level === "error" ? "missing" : ev.level === "warning" ? "unaired" : "downloaded"}">${ev.level.toUpperCase()}</span></td>
        <td class="col-comp"><strong>${escapeHtml(ev.component)}</strong></td>
        <td class="mono col-msg" style="font-size:12px; word-break:break-word;">${escapeHtml(translateLogMessage(ev.message))}</td>
      </tr>`).join("") || `<tr><td colspan="4" style="color:var(--text-muted)">—</td></tr>`;
    renderPagination("journal-pagination", JOURNAL_STATE.page, 100, data.total, loadJournal);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--danger)">${CURRENT_LANG === "en" ? "Loading error:" : "Ошибка загрузки:"} ${escapeHtml(e.message)}</td></tr>`;
  }

  try {
    const s = await api("/api/v1/settings");
    document.getElementById("journal-retention-days").value = s.log_retention_days ?? 14;
  } catch (e) {}
}

async function downloadJournal() {
  const level = document.getElementById("journal-level-filter").value;
  try {
    const resp = await fetch(`/api/v1/journal/download?level=${level}`, { headers: { "X-Api-Key": API_KEY } });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aliasarr_journal_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) { toast("Ошибка скачивания: " + e.message, true); }
}

async function clearJournal() {
  const confirmed = await confirmModal(t("common.delete") + "?");
  if (!confirmed) return;
  try {
    await api("/api/v1/journal", { method: "DELETE" });
    toast(CURRENT_LANG === "en" ? "Journal cleared" : "Журнал очищен");
    loadJournal(1);
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function saveJournalRetention() {
  try {
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ log_retention_days: Number(document.getElementById("journal-retention-days").value) || 14 }),
    });
    toast(t("settings.toast_saved"));
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

// ---------- РЕЛИЗ ЛОГИ (RELEASE LOGS) ----------
let RELEASE_LOGS_STATE = { page: 1, pageSize: 50 };
let CURRENT_RELEASE_LOGS = [];

async function loadReleaseLogs(page) {
  if (page) RELEASE_LOGS_STATE.page = page;
  const stage = document.getElementById("release-logs-stage-filter")?.value || "all";
  const level = document.getElementById("release-logs-level-filter")?.value || "all";
  const query = document.getElementById("release-logs-search")?.value || "";
  const tbody = document.querySelector("#release-logs-table tbody");
  if (!tbody) return;

  try {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--text-muted);">${t("common.loading")}</td></tr>`;
    const params = new URLSearchParams({
      stage: stage,
      level: level,
      query: query,
      page: RELEASE_LOGS_STATE.page,
      page_size: RELEASE_LOGS_STATE.pageSize,
      sort: "desc",
    });

    const data = await api(`/api/v1/release-logs?${params.toString()}`);
    CURRENT_RELEASE_LOGS = data.items || [];

    if (CURRENT_RELEASE_LOGS.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);">${CURRENT_LANG === "en" ? "No release logs recorded yet" : "Записей логики релизов пока нет"}</td></tr>`;
      renderPagination("release-logs-pagination", 1, RELEASE_LOGS_STATE.pageSize, 0, loadReleaseLogs);
      return;
    }

    const stageLabels = {
      search: { label: CURRENT_LANG === "en" ? "Search" : "Поиск", color: "#38bdf8", bg: "rgba(56,189,248,0.15)" },
      match: { label: CURRENT_LANG === "en" ? "Match" : "Сопоставление", color: "#a78bfa", bg: "rgba(167,139,250,0.15)" },
      filter: { label: CURRENT_LANG === "en" ? "Filter" : "Фильтрация", color: "#fbbf24", bg: "rgba(251,191,36,0.15)" },
      grab: { label: CURRENT_LANG === "en" ? "Grab" : "Захват", color: "#34d399", bg: "rgba(52,211,153,0.15)" },
      download: { label: CURRENT_LANG === "en" ? "Download" : "Загрузка", color: "#60a5fa", bg: "rgba(96,165,250,0.15)" },
      import: { label: CURRENT_LANG === "en" ? "Import" : "Импорт", color: "var(--teal)", bg: "rgba(45,212,191,0.15)" },
      error: { label: CURRENT_LANG === "en" ? "Error" : "Ошибка", color: "var(--danger)", bg: "rgba(248,113,113,0.15)" },
    };

    tbody.innerHTML = CURRENT_RELEASE_LOGS.map((item, idx) => {
      const st = stageLabels[item.stage] || { label: item.stage, color: "var(--text-muted)", bg: "rgba(255,255,255,0.05)" };
      const levelClass = item.level === "error" ? "badge-error" : (item.level === "warning" ? "badge-warn" : (item.level === "success" ? "badge-ok" : "badge-tag"));
      const levelLabel = item.level === "error" ? (CURRENT_LANG === "en" ? "Error" : "Ошибка") :
                         (item.level === "warning" ? (CURRENT_LANG === "en" ? "Warn" : "Внимание") :
                         (item.level === "success" ? (CURRENT_LANG === "en" ? "Success" : "Успех") : (CURRENT_LANG === "en" ? "Info" : "Инфо")));

      return `
        <tr>
          <td class="mono col-time" style="font-size:11.5px; white-space:nowrap;">${formatDateTZ(item.created_at)}</td>
          <td><span class="badge-tag" style="background:${st.bg}; color:${st.color}; font-weight:600; font-size:11px;">${st.label}</span></td>
          <td><span class="badge ${levelClass}" style="font-size:10.5px; padding:2px 6px;">${levelLabel}</span></td>
          <td>
            <div style="font-weight:600; color:var(--text); font-size:13px;">${escapeHtml(item.show_title || "—")}</div>
            ${item.indexer ? `<span class="hint mono" style="font-size:11px; color:#818cf8;">[${escapeHtml(item.indexer)}]</span>` : ""}
          </td>
          <td>
            <div style="font-size:12.5px; color:var(--text); line-height:1.4;">${escapeHtml(translateLogMessage(item.message))}</div>
            ${item.release_title ? `<div class="hint mono" style="font-size:11px; margin-top:3px; word-break:break-all; color:var(--text-muted);">${escapeHtml(item.release_title)}</div>` : ""}
          </td>
          <td>
            <button class="btn btn-icon-only btn-small" onclick="openReleaseLogDetail(${idx})" title="${t("common.details")}">
              <i data-lucide="info" class="ico-sm"></i>
            </button>
          </td>
        </tr>
      `;
    }).join("");

    renderPagination("release-logs-pagination", RELEASE_LOGS_STATE.page, RELEASE_LOGS_STATE.pageSize, data.total, loadReleaseLogs);

    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--danger); padding:20px; text-align:center;">${CURRENT_LANG === "en" ? "Loading error:" : "Ошибка загрузки логов релизов:"} ${escapeHtml(e.message)}</td></tr>`;
  }
}

function openReleaseLogDetail(index) {
  const item = CURRENT_RELEASE_LOGS[index];
  if (!item) return;

  const body = document.getElementById("release-log-detail-body");
  if (!body) return;

  const isRu = CURRENT_LANG !== "en";
  body.innerHTML = `
    <div class="form-col" style="gap:8px;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="hint">${isRu ? "Время записи:" : "Timestamp:"}</span>
        <strong class="mono">${formatDateTZ(item.created_at)}</strong>
      </div>
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="hint">${isRu ? "Этап обработки:" : "Stage:"}</span>
        <strong class="mono" style="text-transform:uppercase;">${escapeHtml(item.stage)}</strong>
      </div>
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="hint">${isRu ? "Статус / Уровень:" : "Level:"}</span>
        <strong class="mono" style="text-transform:uppercase; color:${item.level === 'error' ? 'var(--danger)' : (item.level === 'success' ? 'var(--teal)' : 'inherit')}">${escapeHtml(item.level)}</strong>
      </div>
      ${item.show_title ? `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="hint">${isRu ? "Тайтл (Медиа):" : "Show Title:"}</span>
          <strong>${escapeHtml(item.show_title)}</strong>
        </div>
      ` : ""}
      ${item.indexer ? `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="hint">${isRu ? "Индексатор / Трекер:" : "Indexer:"}</span>
          <strong class="mono" style="color:#818cf8;">${escapeHtml(item.indexer)}</strong>
        </div>
      ` : ""}
      ${item.release_title ? `
        <div style="margin-top:6px;">
          <span class="hint">${isRu ? "Оригинальное название раздачи:" : "Release Title:"}</span>
          <div class="mono" style="font-size:12px; background:var(--panel-alt); padding:8px 10px; border-radius:6px; border:1px solid var(--border); margin-top:4px; word-break:break-all;">
            ${escapeHtml(item.release_title)}
          </div>
        </div>
      ` : ""}
      <div style="margin-top:6px;">
        <span class="hint">${isRu ? "Сообщение движка:" : "Engine Message:"}</span>
        <div style="font-size:13px; background:var(--panel-alt); padding:8px 10px; border-radius:6px; border:1px solid var(--border); margin-top:4px; line-height:1.4;">
          ${escapeHtml(translateLogMessage(item.message))}
        </div>
      </div>
      ${item.details ? `
        <div style="margin-top:6px;">
          <span class="hint">${isRu ? "Детали парсера и контекст (JSON):" : "Parsed Context & JSON Details:"}</span>
          <pre class="mono" style="font-size:11.5px; background:rgba(0,0,0,0.3); padding:10px; border-radius:6px; border:1px solid var(--border); overflow-x:auto; margin-top:4px; max-height:220px;">${escapeHtml(JSON.stringify(item.details, null, 2))}</pre>
        </div>
      ` : ""}
    </div>
  `;

  openModal("modal-release-log-detail");
  if (typeof lucide !== "undefined" && lucide.createIcons) {
    lucide.createIcons();
  }
}

async function downloadReleaseLogs() {
  try {
    const resp = await fetch("/api/v1/release-logs/export", { headers: { "X-Api-Key": API_KEY } });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aliasarr_release_logs_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast(CURRENT_LANG === "en" ? "Logs downloaded" : "Логи релизов скачаны");
  } catch (e) {
    toast((CURRENT_LANG === "en" ? "Download error: " : "Ошибка скачивания: ") + e.message, true);
  }
}

async function clearReleaseLogs() {
  const confirmed = await confirmModal(t("common.delete") + "? " + (CURRENT_LANG === "en" ? "Clear all release logs?" : "Очистить весь журнал релизов?"));
  if (!confirmed) return;
  try {
    await api("/api/v1/release-logs", { method: "DELETE" });
    toast(CURRENT_LANG === "en" ? "Release logs cleared" : "Журнал релизов очищен");
    loadReleaseLogs(1);
  } catch (e) {
    toast("Ошибка: " + e.message, true);
  }
}

// ---------- РЕЗЕРВНОЕ КОПИРОВАНИЕ (BACKUP) ----------
let SELECTED_BACKUPS = new Set();

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

let PENDING_RESTORE_FILE = null;
let PENDING_RESTORE_NAME = null;

function renderBackupContentBadges(stats) {
  if (!stats || typeof stats !== "object") return '<span class="hint">—</span>';
  const badges = [];
  if (stats.shows) badges.push(`<span class="badge-tag badge-builtin">${stats.shows} ${CURRENT_LANG === "en" ? "shows" : "тайтлов"}</span>`);
  if (stats.episodes) badges.push(`<span class="badge-tag" style="background:rgba(255,255,255,0.06); color:var(--text-muted);">${stats.episodes} ${CURRENT_LANG === "en" ? "episodes" : "серий"}</span>`);
  if (stats.custom_formats) badges.push(`<span class="badge-tag badge-score-pos">${stats.custom_formats} ${CURRENT_LANG === "en" ? "formats" : "форматов"}</span>`);
  if (stats.quality_profiles) badges.push(`<span class="badge-tag badge-score-pos">${stats.quality_profiles} ${CURRENT_LANG === "en" ? "profiles" : "профилей"}</span>`);
  if (stats.indexers) badges.push(`<span class="badge-tag" style="background:rgba(99,102,241,0.12); color:#818cf8;">${stats.indexers} ${CURRENT_LANG === "en" ? "indexers" : "индексаторов"}</span>`);
  if (stats.download_clients) badges.push(`<span class="badge-tag" style="background:rgba(234,179,8,0.12); color:#facc15;">${stats.download_clients} ${CURRENT_LANG === "en" ? "clients" : "клиентов"}</span>`);
  if (stats.notifications) badges.push(`<span class="badge-tag" style="background:rgba(236,72,153,0.12); color:#f472b6;">${stats.notifications} ${CURRENT_LANG === "en" ? "notifiers" : "уведомлений"}</span>`);
  return badges.length ? `<div style="display:flex; flex-wrap:wrap; gap:4px;">${badges.join("")}</div>` : '<span class="hint">—</span>';
}

async function loadBackups() {
  SELECTED_BACKUPS.clear();
  const tbody = document.querySelector("#backups-table tbody");
  try {
    const [items, stats] = await Promise.all([
      api("/api/v1/backups"),
      api("/api/v1/backups/stats").catch(() => null),
    ]);

    // Обновление карточек статистики
    if (stats) {
      const totalCountEl = document.getElementById("backup-stat-total-count");
      const totalSizeEl = document.getElementById("backup-stat-total-size");
      const latestDateEl = document.getElementById("backup-stat-latest-date");
      const latestTypeEl = document.getElementById("backup-stat-latest-type");
      const scheduleEl = document.getElementById("backup-stat-schedule");
      const retentionEl = document.getElementById("backup-stat-retention");
      const dirEl = document.getElementById("backup-stat-dir");

      if (totalCountEl) totalCountEl.textContent = stats.total_count || "0";
      if (totalSizeEl) totalSizeEl.textContent = formatBytes(stats.total_size_bytes || 0);

      if (latestDateEl) {
        if (stats.latest_backup) {
          latestDateEl.textContent = formatDateTZ(stats.latest_backup.created_at);
          if (latestTypeEl) {
            const isFull = stats.latest_backup.backup_type === "full";
            latestTypeEl.innerHTML = `<span class="badge-tag ${isFull ? 'badge-score-pos' : 'badge-builtin'}">${isFull ? t("backup.badge_full") : t("backup.badge_config")} (${formatBytes(stats.latest_backup.size_bytes)})</span>`;
          }
        } else {
          latestDateEl.textContent = CURRENT_LANG === "en" ? "No backups" : "Копий нет";
          if (latestTypeEl) latestTypeEl.textContent = "—";
        }
      }

      if (scheduleEl) {
        const days = stats.backup_interval_days;
        let scheduleText = CURRENT_LANG === "en" ? "Disabled" : "Отключено";
        if (days === 1) scheduleText = CURRENT_LANG === "en" ? "Daily" : "Ежедневно";
        else if (days === 7) scheduleText = CURRENT_LANG === "en" ? "Weekly" : "Еженедельно";
        else if (days === 30) scheduleText = CURRENT_LANG === "en" ? "Monthly" : "Ежемесячно";
        else if (days > 0) scheduleText = CURRENT_LANG === "en" ? `Every ${days} days` : `Каждые ${days} дн.`;
        scheduleEl.textContent = scheduleText;
      }

      if (retentionEl) {
        retentionEl.textContent = stats.backup_retention_count > 0 
          ? (CURRENT_LANG === "en" ? `Keep last ${stats.backup_retention_count}` : `Хранить посл. ${stats.backup_retention_count}`)
          : (CURRENT_LANG === "en" ? "Unlimited" : "Без лимита");
      }

      if (dirEl && stats.backup_dir) {
        dirEl.textContent = stats.backup_dir;
      }
    }

    if (!items || !items.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:30px; color:var(--text-muted);">${t("backup.empty")}</td></tr>`;
      updateBackupDeleteButton();
      return;
    }

    tbody.innerHTML = items.map(b => {
      const isFull = b.backup_type === "full";
      const typeBadge = `<span class="badge-tag ${isFull ? 'badge-score-pos' : 'badge-builtin'}" style="margin-left:6px; font-size:10px;">${isFull ? t("backup.badge_full") : t("backup.badge_config")}</span>`;
      const contentsBadges = renderBackupContentBadges(b.stats);
      return `
      <tr>
        <td><input type="checkbox" class="backup-checkbox" data-name="${escapeHtml(b.name)}" onchange="toggleBackupSelected('${escapeHtml(b.name).replace(/'/g, "&apos;")}', this.checked)"></td>
        <td>
          <div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px;">
            <strong class="mono" style="font-size:12.5px; color:var(--text);">${escapeHtml(b.name)}</strong>
            ${typeBadge}
          </div>
        </td>
        <td style="font-size:13px;">${formatBytes(b.size_bytes)}</td>
        <td>${contentsBadges}</td>
        <td class="mono" style="font-size:12px; color:var(--text-muted);">${formatDateTZ(b.created_at)}</td>
        <td style="text-align:right;">
          <div class="row-actions" style="justify-content:flex-end; gap:4px;">
            <button class="btn-icon-only" title="${t("backup.btn_restore")}" onclick="openRestoreBackupModal('${escapeHtml(b.name).replace(/'/g, "&apos;")}')">
              <i data-lucide="rotate-ccw" class="ico-sm" style="color:var(--teal, #00F0FF);"></i>
            </button>
            <button class="btn-icon-only" title="Download" onclick="downloadBackup('${escapeHtml(b.name).replace(/'/g, "&apos;")}')">
              <i data-lucide="download" class="ico-sm"></i>
            </button>
            <button class="btn-icon-only danger" title="${t("common.delete")}" onclick="deleteBackup('${escapeHtml(b.name).replace(/'/g, "&apos;")}')">
              <i data-lucide="trash-2" class="ico-sm"></i>
            </button>
          </div>
        </td>
      </tr>`;
    }).join("");

    if (window.lucide) lucide.createIcons();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--danger); padding:20px;">${CURRENT_LANG === "en" ? "Loading error:" : "Ошибка загрузки:"} ${escapeHtml(formatToastMessage(e.message))}</td></tr>`;
  }
  updateBackupDeleteButton();
}

function toggleBackupSelected(name, checked) {
  if (checked) SELECTED_BACKUPS.add(name); else SELECTED_BACKUPS.delete(name);
  updateBackupDeleteButton();
}

function toggleAllBackupsSelected(checkbox) {
  document.querySelectorAll(".backup-checkbox").forEach(cb => {
    cb.checked = checkbox.checked;
    toggleBackupSelected(cb.dataset.name, checkbox.checked);
  });
}

function updateBackupDeleteButton() {
  const btn = document.getElementById("backup-delete-selected-btn");
  if (btn) btn.style.display = SELECTED_BACKUPS.size ? "inline-flex" : "none";
}

function openCreateBackupModal() {
  openModal("backup-create-modal");
}

async function submitCreateBackup() {
  const radio = document.querySelector('input[name="backup-type-select"]:checked');
  const backupType = radio ? radio.value : "full";
  const btn = document.getElementById("backup-submit-create-btn");
  if (btn) btn.disabled = true;

  try {
    closeModal("backup-create-modal");
    await api("/api/v1/backups", {
      method: "POST",
      body: JSON.stringify({ backup_type: backupType }),
    });
    toast(t("backup.toast_created"));
    await loadBackups();
  } catch (e) {
    toast("Ошибка: " + e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function openBackupScheduleModal() {
  try {
    const settings = await api("/api/v1/settings");
    const intervalSelect = document.getElementById("backup-schedule-interval");
    const typeSelect = document.getElementById("backup-schedule-type");
    const retentionSelect = document.getElementById("backup-schedule-retention");

    if (intervalSelect) intervalSelect.value = String(settings.backup_interval_days ?? 7);
    if (typeSelect) typeSelect.value = settings.backup_default_type || "full";
    if (retentionSelect) retentionSelect.value = String(settings.backup_retention_count ?? 10);

    openModal("backup-schedule-modal");
  } catch (e) {
    toast("Ошибка загрузки настроек: " + e.message, true);
  }
}

async function submitSaveBackupSchedule() {
  const intervalSelect = document.getElementById("backup-schedule-interval");
  const typeSelect = document.getElementById("backup-schedule-type");
  const retentionSelect = document.getElementById("backup-schedule-retention");

  const payload = {
    backup_interval_days: parseInt(intervalSelect.value, 10),
    backup_default_type: typeSelect.value,
    backup_retention_count: parseInt(retentionSelect.value, 10),
  };

  try {
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    closeModal("backup-schedule-modal");
    toast(t("backup.toast_schedule_saved"));
    await loadBackups();
  } catch (e) {
    toast("Ошибка сохранения: " + e.message, true);
  }
}

async function onBackupFileSelected(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  event.target.value = "";

  PENDING_RESTORE_FILE = file;
  PENDING_RESTORE_NAME = null;

  try {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch("/api/v1/backups/inspect", {
      method: "POST",
      headers: { "X-Api-Key": API_KEY },
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || "HTTP " + resp.status);
    }
    const meta = await resp.json();
    populateRestoreModal(file.name, meta);
    openModal("backup-restore-modal");
  } catch (e) {
    toast("Ошибка анализа файла архива: " + e.message, true);
  }
}

async function openRestoreBackupModal(name) {
  PENDING_RESTORE_NAME = name;
  PENDING_RESTORE_FILE = null;

  try {
    const meta = await api(`/api/v1/backups/${encodeURIComponent(name)}/inspect`);
    populateRestoreModal(name, meta);
    openModal("backup-restore-modal");
  } catch (e) {
    toast("Ошибка анализа бэкапа: " + e.message, true);
  }
}

function populateRestoreModal(title, meta) {
  const filenameEl = document.getElementById("backup-restore-filename");
  const dateEl = document.getElementById("backup-restore-date");
  const typeBadgeEl = document.getElementById("backup-restore-type-badge");
  const badgesWrap = document.getElementById("backup-restore-badges-wrap");
  const modeSelect = document.getElementById("backup-restore-mode-select");

  if (filenameEl) filenameEl.textContent = title;
  if (dateEl) dateEl.textContent = meta.created_at ? formatDateTZ(meta.created_at) : "—";

  const isFull = meta.backup_type === "full";
  if (typeBadgeEl) {
    typeBadgeEl.className = `badge-tag ${isFull ? 'badge-score-pos' : 'badge-builtin'}`;
    typeBadgeEl.textContent = isFull ? t("backup.badge_full") : t("backup.badge_config");
  }

  if (badgesWrap) {
    badgesWrap.innerHTML = renderBackupContentBadges(meta.stats || {});
  }

  if (modeSelect) {
    modeSelect.value = "auto";
  }
}

async function submitRestoreBackup() {
  const modeSelect = document.getElementById("backup-restore-mode-select");
  const mode = modeSelect ? modeSelect.value : "auto";
  const btn = document.getElementById("backup-submit-restore-btn");
  if (btn) btn.disabled = true;

  try {
    closeModal("backup-restore-modal");
    if (PENDING_RESTORE_NAME) {
      await api("/api/v1/backups/restore-existing", {
        method: "POST",
        body: JSON.stringify({ name: PENDING_RESTORE_NAME, mode: mode }),
      });
    } else if (PENDING_RESTORE_FILE) {
      const formData = new FormData();
      formData.append("file", PENDING_RESTORE_FILE);
      const resp = await fetch(`/api/v1/backups/restore?mode=${encodeURIComponent(mode)}`, {
        method: "POST",
        headers: { "X-Api-Key": API_KEY },
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "HTTP " + resp.status);
      }
    }
    toast(t("backup.toast_restored"));
    await loadBackups();
  } catch (e) {
    toast("Ошибка восстановления: " + e.message, true);
  } finally {
    if (btn) btn.disabled = false;
    PENDING_RESTORE_FILE = null;
    PENDING_RESTORE_NAME = null;
  }
}

async function downloadBackup(name) {
  try {
    const resp = await fetch(`/api/v1/backups/${encodeURIComponent(name)}/download`, { headers: { "X-Api-Key": API_KEY } });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  } catch (e) { toast("Ошибка скачивания: " + e.message, true); }
}

async function deleteBackup(name) {
  const confirmed = await confirmModal(`${t("common.delete")} «${name}»?`);
  if (!confirmed) return;
  try {
    await api("/api/v1/backups", { method: "DELETE", body: JSON.stringify({ names: [name] }) });
    toast(t("common.delete"));
    loadBackups();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

async function deleteSelectedBackups() {
  if (!SELECTED_BACKUPS.size) return;
  const confirmed = await confirmModal(`${t("common.delete")} (${SELECTED_BACKUPS.size})?`);
  if (!confirmed) return;
  try {
    await api("/api/v1/backups", { method: "DELETE", body: JSON.stringify({ names: Array.from(SELECTED_BACKUPS) }) });
    toast(t("common.delete"));
    loadBackups();
  } catch (e) { toast("Ошибка: " + e.message, true); }
}


// ---------- ВЫБОР ПАПКИ ----------
let FOLDER_PICKER_TARGET_ID = null;
let FOLDER_PICKER_CURRENT_PATH = "/";

async function openFolderPicker(targetInputId) {
  FOLDER_PICKER_TARGET_ID = targetInputId;
  const input = document.getElementById(targetInputId);
  const startPath = (input.value || "/").trim() || "/";
  openModal("folder-picker-modal");
  await folderPickerLoad(startPath);
}

async function folderPickerLoad(path) {
  const listEl = document.getElementById("folder-picker-list");
  listEl.innerHTML = `<p class="hint">${t("common.loading")}</p>`;
  try {
    const data = await api(`/api/v1/filesystem/browse?path=${encodeURIComponent(path)}`);
    FOLDER_PICKER_CURRENT_PATH = data.path;
    document.getElementById("folder-picker-current-path").textContent = data.path;
    listEl.innerHTML = data.directories.length
      ? data.directories.map(d => `
          <div class="folder-picker-item" onclick="folderPickerLoad('${d.path.replace(/'/g, "\\'")}')">
            <i data-lucide="folder" class="ico-sm" style="color:var(--accent); vertical-align:middle; margin-right:6px;"></i> <span>${escapeHtml(d.name)}</span>
          </div>`).join("")
      : `<p class="hint">—</p>`;
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    listEl.innerHTML = `<p style="color:var(--danger)">${CURRENT_LANG === "en" ? "Error:" : "Ошибка:"} ${escapeHtml(formatToastMessage(e.message))}</p>`;
  }
}

function folderPickerNavigateUp() {
  if (FOLDER_PICKER_CURRENT_PATH === "/") return;
  const parent = FOLDER_PICKER_CURRENT_PATH.split("/").slice(0, -1).join("/") || "/";
  folderPickerLoad(parent);
}

async function folderPickerCreateDir() {
  const nameInput = document.getElementById("folder-picker-new-name");
  const name = nameInput.value.trim();
  if (!name) return;
  const newPath = (FOLDER_PICKER_CURRENT_PATH.replace(/\/$/, "")) + "/" + name;
  try {
    await api("/api/v1/filesystem/mkdir", { method: "POST", body: JSON.stringify({ path: newPath }) });
    nameInput.value = "";
    await folderPickerLoad(newPath);
  } catch (e) { toast("Ошибка: " + e.message, true); }
}

function folderPickerConfirm() {
  if (FOLDER_PICKER_TARGET_ID) {
    document.getElementById(FOLDER_PICKER_TARGET_ID).value = FOLDER_PICKER_CURRENT_PATH;
  }
  closeModal("folder-picker-modal");
}

// =============================================================================
// ЦЕНТР ФОНОВЫХ ЗАДАЧ И ОПЕРАЦИЙ
// =============================================================================

let TASKS_POLL_INTERVAL = null;
let TASKS_CURRENT_INTERVAL = 3500;
let LAST_RUNNING_COUNT = 0;
let CURRENT_ACTIVE_TASKS = [];

async function loadTasksStatus(manual = false) {
  try {
    const data = await api("/api/v1/tasks");
    CURRENT_ACTIVE_TASKS = data.running || [];
    renderTasksStatusWidget(data);
    const popup = document.getElementById("tasks-popup");
    if (popup && popup.style.display !== "none") {
      renderTasksPopup(data);
    }
    updateLibraryTasksProgress(data);

    // Динамическая адаптация частоты опроса: 1.2с при активных задачах, 3.5с в режиме покоя
    const targetInterval = CURRENT_ACTIVE_TASKS.length > 0 ? 1200 : 3500;
    if (TASKS_CURRENT_INTERVAL !== targetInterval) {
      TASKS_CURRENT_INTERVAL = targetInterval;
      restartTasksPolling(targetInterval);
    }
  } catch (e) {
    // Non-blocking in background
  }
}

function renderTasksStatusWidget(data) {
  const widget = document.getElementById("tasks-status-widget");
  const spinner = document.getElementById("tasks-spinner");
  const idleIcon = document.getElementById("tasks-idle-icon");
  const textEl = document.getElementById("tasks-status-text");
  const subEl = document.getElementById("tasks-status-sub");
  const badge = document.getElementById("tasks-count-badge");

  if (!widget || !textEl) return;

  const running = data.running || [];
  const recent = data.recent || [];
  const runningCount = running.length;

  const mobBadge = document.getElementById("mobile-tasks-badge");
  if (mobBadge) {
    if (runningCount > 0) {
      mobBadge.style.display = "inline-flex";
      mobBadge.textContent = runningCount;
    } else {
      mobBadge.style.display = "none";
    }
  }

  if (runningCount > 0) {
    widget.classList.add("has-running");
    if (spinner) spinner.style.display = "inline-block";
    if (idleIcon) idleIcon.style.display = "none";
    if (badge) {
      badge.style.display = "inline-block";
      badge.textContent = runningCount;
    }

    const latest = running[0];
    const pct = (latest.progress !== null && latest.progress !== undefined) ? Math.min(100, Math.max(0, Math.round(latest.progress * 100))) : null;
    const pctBadge = pct !== null ? `<span class="tasks-status-progress-badge">${pct}%</span>` : "";

    textEl.innerHTML = `${escapeHtml(translateLogMessage(latest.title) || t("tasks.status_running"))}${pctBadge}`;
    if (subEl) {
      subEl.style.display = "block";
      subEl.textContent = translateLogMessage(latest.message) || "";
    }
  } else {
    widget.classList.remove("has-running");
    if (spinner) spinner.style.display = "none";
    if (idleIcon) idleIcon.style.display = "inline-block";
    if (badge) badge.style.display = "none";

    // Если недавно (менее 15 сек назад) завершилась задача — кратко показываем статус
    const latestRecent = recent.length > 0 ? recent[0] : null;
    const isVeryRecent = latestRecent && (new Date() - new Date(latestRecent.ended_at || latestRecent.started_at)) < 15000;

    if (isVeryRecent) {
      textEl.innerHTML = `<i data-lucide="check" class="ico-xs" style="vertical-align:middle; color:var(--accent); margin-right:4px;"></i> ${escapeHtml(translateLogMessage(latestRecent.title) || t("tasks.status_completed"))}`;
      if (subEl) {
        subEl.style.display = "block";
        subEl.textContent = translateLogMessage(latestRecent.message) || "";
      }
    } else {
      textEl.textContent = t("tasks.idle");
      if (subEl) subEl.style.display = "none";
    }
  }

  if (window.lucide) lucide.createIcons();

  // Если количество изменилось — плавно меняем интервал поллинга
  if (runningCount > 0 && LAST_RUNNING_COUNT === 0) {
    restartTasksPolling(1500);
  } else if (runningCount === 0 && LAST_RUNNING_COUNT > 0) {
    restartTasksPolling(4000);
  }
  LAST_RUNNING_COUNT = runningCount;
}

function renderTasksPopup(data) {
  const runningList = document.getElementById("tasks-running-list");
  const recentList = document.getElementById("tasks-recent-list");
  const runningBadge = document.getElementById("tasks-running-badge");

  const running = data.running || [];
  const recent = data.recent || [];

  if (runningBadge) {
    runningBadge.style.display = running.length > 0 ? "inline-block" : "none";
    runningBadge.textContent = running.length;
  }

  if (runningList) {
    if (running.length === 0) {
      runningList.innerHTML = `<div class="tasks-empty-hint">${t("tasks.no_running")}</div>`;
    } else {
      runningList.innerHTML = running.map(tItem => {
        const pct = (tItem.progress !== null && tItem.progress !== undefined) ? Math.min(100, Math.max(0, Math.round(tItem.progress * 100))) : null;
        const progressHtml = pct !== null
          ? `<div class="tasks-item-progress-track"><div class="tasks-item-progress-fill" style="width: ${pct}%"></div></div>`
          : `<div class="tasks-item-progress-track"><div class="tasks-item-progress-fill" style="width: 35%; animation: indeterminate-bar 1.6s ease-in-out infinite alternate;"></div></div>`;
        return `
          <div class="tasks-item">
            <div class="tasks-item-header">
              <div class="tasks-item-title-wrap">
                <div class="tasks-spinner" style="width:12px;height:12px;border-width:2px;"></div>
                <span class="tasks-item-title">${escapeHtml(translateLogMessage(tItem.title || tItem.name))}</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                ${pct !== null ? `<span class="tasks-item-pct">${pct}%</span>` : ""}
                <span class="tasks-item-time">${tItem.duration_seconds}s</span>
              </div>
            </div>
            ${tItem.message ? `<div class="tasks-item-msg">${escapeHtml(translateLogMessage(tItem.message))}</div>` : ""}
            ${progressHtml}
          </div>
        `;
      }).join("");
    }
  }

  if (recentList) {
    if (recent.length === 0) {
      recentList.innerHTML = `<div class="tasks-empty-hint">${t("tasks.no_recent")}</div>`;
    } else {
      recentList.innerHTML = recent.map(tItem => {
        const isError = tItem.status === "failed";
        const icon = isError
          ? `<span class="tasks-icon-failed"><i data-lucide="x" class="ico-xs"></i></span>`
          : `<span class="tasks-icon-success"><i data-lucide="check" class="ico-xs"></i></span>`;
        return `
          <div class="tasks-item">
            <div class="tasks-item-header">
              <div class="tasks-item-title-wrap">
                ${icon}
                <span class="tasks-item-title">${escapeHtml(translateLogMessage(tItem.title || tItem.name))}</span>
              </div>
              <span class="tasks-item-time">${tItem.duration_seconds}s</span>
            </div>
            ${tItem.message ? `<div class="tasks-item-msg">${escapeHtml(translateLogMessage(tItem.message))}</div>` : ""}
          </div>
        `;
      }).join("");
    }
  }
  if (window.lucide) lucide.createIcons();
}

function updateLibraryTasksProgress(data) {
  const running = data.running || [];
  const hadTasksBefore = Boolean(window._HAD_RUNNING_TASKS);
  window._HAD_RUNNING_TASKS = running.length > 0;

  // 1. Обновление карточек в библиотеке (сетка, таблица, обзор)
  if (typeof CACHED_SHOWS !== "undefined" && CACHED_SHOWS && CACHED_SHOWS.length) {
    CACHED_SHOWS.forEach(show => {
      const activeTask = running.find(t => 
        (t.show_id && t.show_id === show.id) ||
        (t.title && t.title.toLowerCase().includes((show.title || "").toLowerCase())) ||
        (t.message && t.message.toLowerCase().includes((show.title || "").toLowerCase()))
      );

      const taskLabel = activeTask ? getTaskDisplayTitle(activeTask) : "";

      // Карточка постера (Grid view)
      const card = document.getElementById(`show-card-${show.id}`);
      if (card) {
        let overlay = card.querySelector(".poster-import-overlay");
        const posterProgress = card.querySelector(".poster-progress");
        const progressText = card.querySelector(".poster-progress-text");

        if (activeTask) {
          const pct = Math.min(100, Math.max(0, Math.round((activeTask.progress || 0) * 100)));
          if (!overlay) {
            overlay = document.createElement("div");
            overlay.className = "poster-import-overlay";
            card.querySelector(".show-poster")?.appendChild(overlay);
          }
          overlay.innerHTML = `
            <div class="poster-import-spinner"></div>
            <div class="poster-import-title">${escapeHtml(taskLabel)}</div>
            <div class="poster-import-pct">${pct}%</div>
            <div class="poster-import-bar-track">
              <div class="poster-import-bar-fill" style="width: ${pct}%;"></div>
            </div>
          `;
          if (posterProgress) {
            posterProgress.className = "poster-progress status-importing";
            if (progressText) {
              progressText.textContent = `${taskLabel}: ${pct}%`;
            }
          }
        } else {
          if (overlay) {
            overlay.remove();
          }
          if (posterProgress) {
            if (show._computed_status) {
              posterProgress.className = `poster-progress ${show._computed_status}`;
            }
            if (progressText) {
              if (POSTER_OPTIONS.progressText && show.content_type !== "movie") {
                progressText.textContent = `${show.downloaded_episodes_count || 0} / ${show.episodes_count || 1}`;
              } else if (POSTER_OPTIONS.progressText && show.content_type === "movie") {
                progressText.textContent = (show.downloaded_episodes_count || 0) > 0 ? "1 / 1" : "0 / 1";
              }
            }
          }
        }
      }

      // Режим Обзор (Overview view)
      const overviewRow = document.getElementById(`show-overview-${show.id}`);
      if (overviewRow) {
        const overviewProgress = overviewRow.querySelector(".poster-progress");
        const progressText = overviewProgress ? overviewProgress.querySelector(".poster-progress-text") : null;
        if (activeTask) {
          const pct = Math.min(100, Math.max(0, Math.round((activeTask.progress || 0) * 100)));
          if (overviewProgress) {
            overviewProgress.className = "poster-progress status-importing";
            if (progressText) {
              progressText.textContent = `${taskLabel}: ${pct}%`;
            }
          }
        } else if (overviewProgress) {
          if (show._computed_status) {
            overviewProgress.className = `poster-progress ${show._computed_status}`;
          }
          if (progressText) {
            if (POSTER_OPTIONS.progressText && show.content_type !== "movie") {
              progressText.textContent = `${show.downloaded_episodes_count || 0} / ${show.episodes_count || 1}`;
            } else if (POSTER_OPTIONS.progressText && show.content_type === "movie") {
              progressText.textContent = (show.downloaded_episodes_count || 0) > 0 ? "1 / 1" : "0 / 1";
            }
          }
        }
      }

      // Табличный вид (Table view) — статус импорта в таблице скрыт
      const row = document.getElementById(`show-row-${show.id}`);
      if (row) {
        const progBadge = row.querySelector(".table-task-progress");
        if (progBadge) {
          progBadge.remove();
        }
      }
    });
  }

  // Если задачи только что завершились, обновляем библиотеку в фоне
  if (hadTasksBefore && running.length === 0) {
    if (typeof loadShows === "function") {
      loadShows(false);
    }
  }

  // 2. Обновление прогресс-бара внутри модального окна карточки фильма/сериала/аниме (Show Detail Modal)
  if (typeof CURRENT_SHOW_ID !== "undefined" && CURRENT_SHOW_ID) {
    const showModal = document.getElementById("show-modal");
    if (showModal && showModal.classList.contains("active")) {
      const showObj = (typeof CACHED_SHOWS !== "undefined" && CACHED_SHOWS) ? CACHED_SHOWS.find(s => s.id === CURRENT_SHOW_ID) : null;
      const activeTask = running.find(t => 
        (t.show_id && t.show_id === CURRENT_SHOW_ID) ||
        (showObj && (
          (t.title && t.title.toLowerCase().includes((showObj.title || "").toLowerCase())) ||
          (t.message && t.message.toLowerCase().includes((showObj.title || "").toLowerCase()))
        ))
      );
      const content = document.getElementById("show-modal-content");
      let banner = document.getElementById(`show-import-banner-${CURRENT_SHOW_ID}`);
      if (activeTask && content) {
        const pct = Math.min(100, Math.max(0, Math.round((activeTask.progress || 0) * 100)));
        const msg = escapeHtml(translateLogMessage(activeTask.message) || "");
        if (!banner) {
          banner = document.createElement("div");
          banner.id = `show-import-banner-${CURRENT_SHOW_ID}`;
          banner.className = "show-import-banner";
          content.prepend(banner);
        }
        banner.innerHTML = `
          <div class="show-import-header">
            <div class="show-import-title">
              <div class="tasks-spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:middle;"></div>
              <span>${escapeHtml(translateLogMessage(activeTask.title || activeTask.name))}</span>
            </div>
            <span class="show-import-pct">${pct}%</span>
          </div>
          <div class="show-import-track">
            <div class="show-import-fill" style="width: ${pct}%"></div>
          </div>
          ${msg ? `<div class="show-import-msg">${msg}</div>` : ""}
        `;
      } else if (banner) {
        banner.remove();
      }
    }
  }
}

function toggleTasksPopup(event) {
  if (event) event.stopPropagation();
  const popup = document.getElementById("tasks-popup");
  if (!popup) return;
  const isShown = popup.style.display !== "none";
  if (isShown) {
    popup.style.display = "none";
  } else {
    popup.style.display = "flex";
    loadTasksStatus(true);
    if (window.lucide) lucide.createIcons();
  }
}

async function clearTasksHistory(event) {
  if (event) event.stopPropagation();
  try {
    await api("/api/v1/tasks/clear-history", { method: "POST" });
    loadTasksStatus(true);
  } catch (e) {}
}

function restartTasksPolling(intervalMs) {
  if (TASKS_POLL_INTERVAL) clearInterval(TASKS_POLL_INTERVAL);
  TASKS_POLL_INTERVAL = setInterval(() => loadTasksStatus(false), intervalMs);
}

// Закрываем всплывающее окно задач при клике вне его
document.addEventListener("click", (e) => {
  const popup = document.getElementById("tasks-popup");
  const widget = document.getElementById("tasks-status-widget");
  if (popup && popup.style.display !== "none") {
    if (!popup.contains(e.target) && (!widget || !widget.contains(e.target))) {
      popup.style.display = "none";
    }
  }
});

// ---------- INIT ----------
document.querySelectorAll(".modal-overlay").forEach(overlay => {
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal(overlay.id);
  });
});

async function startApp() {
  updateMobileState();
  checkConnection();
  loadTasksStatus();
  restartTasksPolling(3500);

  try {
    const s = await api("/api/v1/settings");
    if (s && s.language) {
      applyLanguage(s.language);
    }
    if (s && s.theme) {
      applyTheme(s.theme);
    }
    if (s && s.timezone) {
      APP_TIMEZONE = s.timezone;
      localStorage.setItem("vbeacon_timezone", APP_TIMEZONE);
    }
  } catch (e) {}

  const initialHash = window.location.hash.slice(1);
  const targetTab = initialHash || localStorage.getItem("aliasarr_last_tab") || "dashboard";
  if (targetTab && document.getElementById("tab-" + targetTab)) {
    switchTab(targetTab);
  } else {
    switchTab("dashboard");
  }
  
  if (window.lucide) {
    lucide.createIcons();
  }
}

// Применяем язык/тему из localStorage сразу, не дожидаясь ответа /api/v1/settings —
// они всё равно будут перезаписаны актуальными значениями в loadGeneralSettings().
try {
  applyTheme(localStorage.getItem("vbeacon_theme") || "dark");
  applyLanguage(localStorage.getItem("vbeacon_lang") || "ru");
  updateMobileState();
} catch (e) {}

(async function init() {
  updateMobileState();
  const loginRequired = await checkAuthStatus();
  if (!loginRequired) {
    startApp();
  }
  // если требуется логин — startApp() будет вызван из submitLogin() после успешного входа
})();
