---
name: custom-design
description: >-
  Используй этот скилл, когда нужно проектировать, верстать или модифицировать интерфейс Aliasarr.
  Скилл содержит стандарты эргономичной дизайн-системы Aliasarr Modern, правила 5 спокойных тем
  (OLED Void, Nordic Slate, Deep Midnight, Emerald Spruce, Daylight Paper), компонентную базу,
  математическую сетку, тактильную физику микро-взаимодействий, требования GPU-безопасности
  и строгие запреты на визуальный мусор.
---

# Руководство по дизайн-системе Aliasarr (Aliasarr Modern & Eye-Friendly System)

Данный документ является нормативным стандартом проектирования, верстки и визуальной архитектуры для веб-приложения, мобильного интерфейса и документации **Aliasarr**.

Вся визуальная среда Aliasarr строится на принципах инженерного минимализма, спокойной эргономики, бескомпромиссной защиты зрения пользователя от утомления и отказа от шаблонных нейросетевых клише.

---

## 1. Философия ремесленного дизайна и защита от нейросетевых клише

Большинство интерфейсов, создаваемых или перерабатываемых с помощью базовых нейросетевых промптов, страдают характерными симптомами «нейросетевого мусора»:
- Чрезмерное использование едких неоновых градиентов (ядовитый циан, кислотный фиолетовый, агрессивная маджента), вызывающих резь в глазах уже через 10 минут работы в темном помещении.
- Нагромождение бессмысленных многослойных размытий `backdrop-filter`, перегружающих видеокарту в фоновом режиме даже при статичном экране.
- Декоративные иконки-клише (ракеты, искры, молнии, звезды) вместо четких семантических обозначений.
- Обилие эмодзи в заголовках, таблицах и кнопках, превращающее рабочий инструмент в любительский прототип.
- Гигантские мыльные скругления (border-radius 30px+), съедающие полезную площадь экрана и искажающие визуальный баланс контента.

Дизайн-система **Aliasarr Modern** создана по стандартам первоклассных профессиональных инструментов для инженеров (уровня Linear, Raycast, Supabase, Vercel):
1. **Инженерная строгость**: Каждый пиксель и каждый отступ функционально обоснован. Плотность информации оптимизирована для быстрого восприятия больших массивов данных медиатеки.
2. **Нулевая усталость глаз (Zero Eye Fatigue)**: Отказ от ядовитого спектра в пользу выверенных матовых оттенков графита, титана, спокойного нордического сланца и сдержанного хвойного обсидиана.
3. **Тактильный микро-отклик**: Элементы управления реагируют на действия пользователя физически осязаемо: упругий прожим кнопок, микро-фасеты света на гранях карточек, спокойные всплывающие окна без дребезжания.
4. **Контекстная адаптивность**: Интерфейс одинаково органичен на 4K-мониторах рабочей станции, ноутбуках с Retina-дисплеями и экранах смартфонов в режиме Docker WebUI.

---

## 2. Строгие запреты и правила чистоты интерфейса

При любой модификации разметки, стилей или скриптов Aliasarr действуют абсолютные правила-табу:

### А. Полный запрет на эмодзи (Emoji Ban)
Категорически запрещено использовать эмодзи в интерфейсе приложения, в текстах локализации (TRANSLATIONS), в подсказках, модальных окнах, названиях вкладок, уведомлениях, комментариях к коду и в файлах документации.
- Недопустимо: Текст с эмодзи вроде ракет, огоньков, галочек, папок или звездочек.
- Допустимо: Использование семантических векторных иконок Lucide (`check-circle`, `trash-2`, `alert-triangle`, `activity`, `folder`) рядом с текстовой меткой.

### Б. Запрет на запрещенные иконки (Prohibited Icons Ban)
Категорически запрещено использовать иконки, ассоциирующиеся с дешевым визуальным шумом:
- **Ракета (`rocket`)**: Запрещена везде. Для быстрого поиска или запуска используются иконки `play`, `search`, `refresh-cw`.
- **Звезды и искры (`star`, `sparkles`)**: Запрещены везде. Для рейтингов и наград используется иконка `award`. Для закладок и закрепления раздач используется иконка `pin`. Для умного сопоставления используется `sliders-horizontal` или `tag`.
- **Молния (`zap`)**: Запрещена везде. Для автопоиска, фоновых операций и триггеров используются иконки `activity`, `workflow`, `target`, `check-circle`.

### В. Запрет на паразитное свечение и размытые цветные тени
Запрещено использовать `text-shadow` и размытые цветные тени вида `box-shadow: 0 0 20px var(--teal)`. Все тени должны строиться по физической шкале освещенности с черным полупрозрачным альфа-каналом.

---

## 3. Математическая дизайн-система: Токены и константы

### А. Шкала отступов (4px Baseline Grid)
Все внутренние и внешние отступы, сетки и высоты кратны 4 пикселям:
```css
--space-1: 4px;   /* Микро-зазоры между иконкой и текстом */
--space-2: 8px;   /* Базовый зазор между бейджами и чипами */
--space-3: 12px;  /* Отступы внутри компактных инпутов и ячеек */
--space-4: 16px;  /* Стандартный паддинг мобильных контейнеров */
--space-5: 20px;  /* Паддинг средних модальных окон */
--space-6: 24px;  /* Стандартный паддинг десктопных секций и карточек */
--space-8: 32px;  /* Вертикальные интервалы между блоками страницы */
--space-12: 48px; /* Разделители крупных функциональных модулей */
```

### Б. Шкала скруглений (Radii Scale)
Скругления углов не должны быть пузырчатыми; они повторяют контуры современного аппаратного обеспечения:
```css
--radius-xs: 4px;  /* Микро-бейджи, прогресс-бары, селекторы */
--radius-sm: 6px;  /* Кнопки, инпуты, селекты, подвкладки */
--radius: 10px;    /* Карточки секций, превью постеров, дроверы */
--radius-lg: 14px; /* Модальные окна, дашборд-виджеты, меню */
```

### В. Типографика
- **Основной шрифт интерфейса (`--font-body`, `--font-display`)**:
  `'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif`
  Высокая разборчивость цифр, четкая геометрия, идеальный кернинг.
- **Моноширинный шрифт технических данных (`--font-mono`)**:
  `'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace`
  Применяется для всех путей файловой системы, хешей торрентов, шаблонов переименования, номеров сезонов/серий, размеров файлов и кодеков.

### Г. Физика тактильного отклика и микро-фасетов
```css
--shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.2);
--shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.25);
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.35);
--shadow-lg: 0 12px 32px rgba(0, 0, 0, 0.45);
--shadow-xl: 0 24px 60px rgba(0, 0, 0, 0.6);

/* Внутренний светящийся скос верхней грани карточек (создает объем) */
--bevel-light: inset 0 1px 0 rgba(255, 255, 255, 0.07);
/* Нижний теневой скос */
--bevel-dark: inset 0 -1px 0 rgba(0, 0, 0, 0.35);

/* Физика упругой анимации для модальных окон и переключателей */
--spring-bounce: cubic-bezier(0.16, 1, 0.3, 1);
```

---

## 4. Палитра пяти спокойных тем (Eye-Friendly Color Palettes)

В Aliasarr реализованы 5 цветовых тем, каждая из которых решает конкретную задачу освещенности рабочего места без паразитной нагрузки на сетчатку.

### 1. Тема Nordic Slate (`[data-theme="slate"]`) — Тема по умолчанию
Создана по канонам скандинавского дизайна: холодный графитовый монохром с мягким стальным и морозным акцентом. Обеспечивает максимальный комфорт при повседневном использовании.
- Фон подложки (`--bg`): `#0b0f17`
- Поверхность панелей (`--panel`): `#111827`
- Второстепенная панель (`--panel-alt`): `#1a2234`
- Границы (`--border`): `rgba(148, 163, 184, 0.12)`
- Границы при наведении (`--border-hover`): `rgba(148, 163, 184, 0.28)`
- Основной текст (`--text`): `#f1f5f9`
- Второстепенный текст (`--text-muted`): `#94a3b8`
- Фокусный акцент (`--teal`): `#38bdf8` (мягкий небесный)
- Вторичный акцент (`--violet`): `#60a5fa` (стальной синий)
- Успех (`--success`): `#34d399`
- Предупреждение (`--warning`): `#fbbf24`
- Ошибка / Опасность (`--danger`): `#f87171`

### 2. Тема OLED Void (`[data-theme="oled"]`) — Абсолютный черный
Разработана для темных комнат и OLED-дисплеев. Нулевое энергопотребление на черных пикселях, хирургическая контрастность белого и серебристого титана без единого цветного пятна.
- Фон подложки (`--bg`): `#000000` (абсолютный черный 0 nit)
- Поверхность панелей (`--panel`): `#0c0d0e`
- Второстепенная панель (`--panel-alt`): `#141619`
- Границы (`--border`): `rgba(255, 255, 255, 0.08)`
- Границы при наведении (`--border-hover`): `rgba(255, 255, 255, 0.20)`
- Основной текст (`--text`): `#f8fafc`
- Второстепенный текст (`--text-muted`): `#94a3b8`
- Фокусный акцент (`--teal`): `#e2e8f0` (титановое серебро)
- Вторичный акцент (`--violet`): `#cbd5e1`
- Успех (`--success`): `#22c55e`
- Предупреждение (`--warning`): `#f59e0b`
- Ошибка / Опасность (`--danger`): `#ef4444`

### 3. Тема Deep Midnight (`[data-theme="indigo"]`) — Ночной индиго
Густая ночная атмосфера глубокого синего космоса с благородными лавандово-барвинковыми акцентами. Идеальна для вечернего просмотра релизов.
- Фон подложки (`--bg`): `#070913`
- Поверхность панелей (`--panel`): `#0e1222`
- Второстепенная панель (`--panel-alt`): `#161c33`
- Границы (`--border`): `rgba(99, 102, 241, 0.14)`
- Границы при наведении (`--border-hover`): `rgba(99, 102, 241, 0.32)`
- Основной текст (`--text`): `#f1f5f9`
- Второстепенный текст (`--text-muted`): `#a5b4fc`
- Фокусный акцент (`--teal`): `#818cf8` (барвинок)
- Вторичный акцент (`--violet`): `#a78bfa` (ирис)
- Успех (`--success`): `#34d399`
- Предупреждение (`--warning`): `#fbbf24`
- Ошибка / Опасность (`--danger`): `#f87171`

### 4. Тема Emerald Spruce (`[data-theme="pine"]`) — Хвойный сланец
Органическая темно-хвойная тема. Исследования офтальмологов доказывают, что оттенки зеленого спектра (хвоя, эвкалипт, шалфей) создают наименьшее напряжение для цилиарной мышцы глаза.
- Фон подложки (`--bg`): `#070e0a`
- Поверхность панелей (`--panel`): `#0d1712`
- Второстепенная панель (`--panel-alt`): `#15241d`
- Границы (`--border`): `rgba(52, 211, 153, 0.12)`
- Границы при наведении (`--border-hover`): `rgba(52, 211, 153, 0.28)`
- Основной текст (`--text`): `#ecfdf5`
- Второстепенный текст (`--text-muted`): `#86efac`
- Фокусный акцент (`--teal`): `#34d399` (мягкий шалфей)
- Вторичный акцент (`--violet`): `#2dd4bf` (бирюза)
- Успех (`--success`): `#34d399`
- Предупреждение (`--warning`): `#fbbf24`
- Ошибка / Опасность (`--danger`): `#f87171`

### 5. Тема Daylight Paper (`[data-theme="paper"]`, `[data-theme="light"]`) — Светлая бумага
Светлая тема с эффектом матовой типографской бумаги. Отсутствие синего ослепляющего блеска, глубокий угольный текст для солнечных помещений.
- Фон подложки (`--bg`): `#f8fafc`
- Поверхность панелей (`--panel`): `#ffffff`
- Второстепенная панель (`--panel-alt`): `#f1f5f9`
- Границы (`--border`): `#e2e8f0`
- Границы при наведении (`--border-hover`): `#cbd5e1`
- Основной текст (`--text`): `#0f172a`
- Второстепенный текст (`--text-muted`): `#64748b`
- Фокусный акцент (`--teal`): `#2563eb` (глубокий кобальт)
- Вторичный акцент (`--violet`): `#4f46e5`
- Успех (`--success`): `#16a34a`
- Предупреждение (`--warning`): `#d97706`
- Ошибка / Опасность (`--danger`): `#dc2626`

---

## 5. Архитектура каркаса приложения (App Shell)

Структурный каркас Aliasarr состоит из 4 базовых зон:
1. **Боковая навигация (`aside.sidebar`)**:
   - Фиксированная ширина 240px, залипание на всю высоту экрана (`position: sticky; top: 0; height: 100vh`).
   - Логотип в шапке с четким бейджем и тонким монохромным контуром.
   - Вертикальный стек пунктов меню (`.nav`). Пункты имеют фиксированную высоту 38px, отступ 10px между иконкой и текстом.
   - Активный пункт `.nav-item.active` выделяется не кричащим фоном, а левым индикатором (`::before { width: 3px; background: var(--teal); }`) и цветом иконки.
   - Футер сайдбара: карточка профиля пользователя и виджет фоновых задач с точечным статусом.
2. **Липкая шапка рабочей области (`.panel-sticky-header`)**:
   - Обеспечивает постоянную видимость контекстных действий при прокрутке длинных списков или таблиц настроек.
   - Содержит заголовок `h1`, краткий подзаголовок `.subtitle` и блок управляющих кнопок `.header-actions`.
3. **Основное рабочее пространство (`main.content`)**:
   - Контентная сетка с максимальной шириной и отступами `padding: 24px` (на смартфонах `16px 12px`).
4. **Мобильный адаптивный док (`.mobile-bottom-bar`)**:
   - На экранах менее 768px боковой сайдбар сворачивается в компактное выдвижное меню, а ключевая навигация переносится в нижний плавающий док с крупными областями нажатия (touch targets не менее 44x44px).

---

## 6. Библиотека компонентов и спецификация верстки

### А. Карточка секции настроек (`.settings-section-card`)
Базовый структурный контейнер для всех панелей и настроек:
```html
<div class="settings-section-card" id="card-unique-id">
  <div class="settings-card-header">
    <div class="settings-card-header-left">
      <div class="settings-card-icon-badge">
        <i data-lucide="shield"></i>
      </div>
      <div class="settings-card-title-wrap">
        <h3 data-i18n="section.title">Заголовок секции</h3>
        <p class="subtitle" data-i18n="section.subtitle">Краткое пояснение назначения параметров блока.</p>
      </div>
    </div>
  </div>

  <div class="form-grid-modern">
    <!-- Поля и переключатели -->
  </div>
</div>
```
CSS-правила:
```css
.settings-section-card {
  background: var(--panel);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm), var(--bevel-light);
  border-radius: var(--radius);
  padding: 24px;
  margin-bottom: 20px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.settings-section-card:hover {
  border-color: var(--border-hover);
}
.settings-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.settings-card-icon-badge {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--panel-alt);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--teal);
  flex-shrink: 0;
}
```

### Б. 2-Колоночная адаптивная сетка полей (`.form-grid-modern`)
Обеспечивает строгое выравнивание полей ввода:
```html
<div class="form-grid-modern">
  <div class="settings-field-group">
    <label class="settings-field-label">
      <span data-i18n="field.title">Название параметра</span>
      <span class="settings-field-hint">(единицы измерения)</span>
    </label>
    <input class="input" type="text" placeholder="Значение">
  </div>
  
  <div class="settings-field-group">
    <label class="settings-field-label">
      <span data-i18n="field.choice">Выбор режима</span>
    </label>
    <select class="input">
      <option value="1">Опция 1</option>
      <option value="2">Опция 2</option>
    </select>
  </div>

  <!-- Поле на всю ширину строки -->
  <div class="settings-field-group" style="grid-column: 1 / -1;">
    <button class="btn btn-primary" onclick="saveSettings()">Сохранить</button>
  </div>
</div>
```
CSS-правила:
```css
.form-grid-modern {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 20px;
}
@media (max-width: 800px) {
  .form-grid-modern {
    grid-template-columns: 1fr;
  }
}
.settings-field-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.settings-field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.settings-field-hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}
```

### В. Современный переключатель iOS-стиля (`.switch-toggle`)
Заменяет стандартные плоские чекбоксы на эргономичный тумблер с описанием:
```html
<label class="switch-toggle">
  <input id="setting-feature-id" type="checkbox" checked>
  <span class="switch-slider"></span>
  <span class="switch-title" data-i18n="feature.title">Название опции</span>
  <span class="switch-desc" data-i18n="feature.desc">Подробное пояснение последствий включения или отключения данной функции системы.</span>
</label>
```
CSS-правила:
```css
.switch-toggle {
  display: grid;
  grid-template-columns: 42px 1fr;
  grid-template-rows: auto auto;
  column-gap: 12px;
  align-items: center;
  cursor: pointer;
  user-select: none;
}
.switch-toggle input {
  display: none;
}
.switch-slider {
  grid-row: 1 / span 2;
  width: 42px;
  height: 24px;
  background: var(--panel-alt);
  border: 1px solid var(--border);
  border-radius: 9999px;
  position: relative;
  transition: all 0.2s var(--spring-bounce);
}
.switch-slider::before {
  content: "";
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  background: var(--text-muted);
  border-radius: 50%;
  transition: transform 0.2s var(--spring-bounce), background 0.2s ease;
}
.switch-toggle input:checked + .switch-slider {
  background: rgba(56, 189, 248, 0.2);
  border-color: var(--teal);
}
.switch-toggle input:checked + .switch-slider::before {
  transform: translateX(18px);
  background: var(--teal);
}
.switch-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}
.switch-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
  margin-top: 2px;
}
```

### Г. Тактильные кнопки с микро-физикой (`.btn`)
Все кнопки обладают физическим откликом при нажатии (`:active`):
```html
<button class="btn btn-primary"><i data-lucide="check"></i> Сохранить</button>
<button class="btn btn-secondary"><i data-lucide="refresh-cw"></i> Обновить</button>
<button class="btn btn-danger"><i data-lucide="trash-2"></i> Удалить</button>
```
CSS-правила:
```css
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 16px;
  height: 38px;
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  transition: transform 0.08s ease, background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
  user-select: none;
}
.btn:active {
  transform: scale(0.98) translateY(1px);
}
.btn-primary {
  background: var(--teal);
  color: #0b0f17;
  border-color: transparent;
  box-shadow: var(--shadow-xs);
}
[data-theme="paper"] .btn-primary,
[data-theme="light"] .btn-primary {
  color: #ffffff;
}
.btn-primary:hover {
  filter: brightness(1.08);
}
.btn-secondary {
  background: var(--panel-alt);
  color: var(--text);
  border-color: var(--border);
}
.btn-secondary:hover {
  background: var(--panel);
  border-color: var(--border-hover);
}
.btn-danger {
  background: rgba(248, 113, 113, 0.15);
  color: var(--danger);
  border-color: rgba(248, 113, 113, 0.3);
}
.btn-danger:hover {
  background: rgba(248, 113, 113, 0.25);
  border-color: var(--danger);
}
```

### Д. Карточки-эксплейнеры настроек (`.settings-explainer-card`)
Используются для наглядного разъяснения сложных архитектурных концепций (Hardlinks, размонтирование, сидирование):
```html
<div class="settings-explainer-card">
  <div class="explainer-box explainer-box-why">
    <div class="explainer-tag">
      <i data-lucide="target" class="ico-xxs"></i>
      <span data-i18n="settings.explainer_why_title">Зачем это нужно</span>
    </div>
    <div class="explainer-text" data-i18n="settings.hardlink_why_desc">Пояснение назначения функции.</div>
  </div>
  <div class="explainer-box explainer-box-rec">
    <div class="explainer-tag">
      <i data-lucide="check-circle" class="ico-xxs"></i>
      <span data-i18n="settings.explainer_rec_title">Рекомендуемое значение</span>
    </div>
    <div class="explainer-text" data-i18n="settings.hardlink_rec_desc">Рекомендация по настройке.</div>
  </div>
  <div class="explainer-box explainer-box-warn">
    <div class="explainer-tag">
      <i data-lucide="alert-triangle" class="ico-xxs"></i>
      <span data-i18n="settings.explainer_warn_title">Предостережение</span>
    </div>
    <div class="explainer-text" data-i18n="settings.hardlink_warn_desc">Предупреждение о рисках.</div>
  </div>
</div>
```
CSS-правила:
```css
.settings-explainer-card {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-top: 10px;
}
.explainer-box {
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--panel-alt);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.explainer-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.explainer-box-why .explainer-tag { color: var(--teal); }
.explainer-box-rec .explainer-tag { color: var(--success); }
.explainer-box-warn .explainer-tag { color: var(--warning); }
.explainer-text {
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.45;
}
```

### Е. Карточки метрик дашборда (`.dash-stat-card`)
Оформление сводных показателей медиатеки:
```html
<div class="dash-stat-card card-media" onclick="switchTab('library')">
  <div>
    <div class="dash-stat-header">
      <span class="dash-stat-title">
        <div class="dash-stat-icon-badge"><i data-lucide="film"></i></div>
        <span data-i18n="dash.card_media">Медиатека</span>
      </span>
      <span class="dash-stat-arrow"><i data-lucide="arrow-up-right" class="ico-xs"></i></span>
    </div>
    <div class="dash-stat-main-val" id="stat-shows">—</div>
  </div>
  <div class="dash-stat-subitems">
    <div class="dash-subitem">
      <span class="dash-subitem-label"><i data-lucide="tv" class="ico-xxs"></i> Сериалы</span>
      <span class="dash-subitem-val" id="stat-series">0</span>
    </div>
    <div class="dash-subitem">
      <span class="dash-subitem-label"><i data-lucide="film" class="ico-xxs"></i> Фильмы</span>
      <span class="dash-subitem-val" id="stat-movies">0</span>
    </div>
  </div>
</div>
```

### Ж. Модальные окна с пружинной физикой (`.modal-overlay`, `.modal`)
Модальные окна Aliasarr открываются без задержки и рывков благодаря аппаратно-ускоренной интерполяции:
```html
<div class="modal-overlay" id="example-modal" onclick="closeModal('example-modal')">
  <div class="modal" onclick="event.stopPropagation()">
    <div class="modal-header">
      <div class="modal-header-left">
        <div class="modal-icon-badge"><i data-lucide="settings"></i></div>
        <h2 class="modal-title">Заголовок окна</h2>
      </div>
      <button class="modal-close" onclick="closeModal('example-modal')"><i data-lucide="x"></i></button>
    </div>
    <div class="modal-body">
      <!-- Контент модального окна -->
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal('example-modal')">Отмена</button>
      <button class="btn btn-primary" onclick="confirmAction()">Применить</button>
    </div>
  </div>
</div>
```
CSS-правила:
```css
.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: var(--glass-blur, none);
}
.modal-overlay.active {
  display: flex;
}
.modal {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 90%;
  max-width: 680px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-xl), var(--bevel-light);
  animation: modalSpringIn 0.24s var(--spring-bounce);
}
@keyframes modalSpringIn {
  from {
    opacity: 0;
    transform: scale(0.97) translateY(8px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}
.modal-header {
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.modal-body {
  padding: 22px;
  overflow-y: auto;
  flex: 1;
}
.modal-footer {
  padding: 16px 22px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  background: var(--panel-alt);
  border-bottom-left-radius: var(--radius-lg);
  border-bottom-right-radius: var(--radius-lg);
}
```

### З. Таблицы данных (`.table-responsive`, `.glass-table-wrap`)
Таблицы медиатеки, очередей загрузок и логов оптимизированы для плотного представления данных:
```html
<div class="table-responsive glass-table-wrap">
  <table class="table-modern">
    <thead>
      <tr>
        <th>Видео</th>
        <th>Категория</th>
        <th>Размер</th>
        <th>Статус</th>
        <th class="text-right">Действия</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td class="font-medium">Breaking Bad</td>
        <td><span class="badge badge-secondary">Сериал</span></td>
        <td class="mono">42.8 GB</td>
        <td><span class="badge badge-success">Загружено</span></td>
        <td class="text-right">
          <button class="btn btn-secondary btn-xs"><i data-lucide="search"></i></button>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```
CSS-правила:
```css
.glass-table-wrap {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.table-modern {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 13px;
}
.table-modern th {
  background: var(--panel-alt);
  color: var(--text-muted);
  font-weight: 600;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.table-modern td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}
.table-modern tbody tr:last-child td {
  border-bottom: none;
}
.table-modern tbody tr:hover td {
  background: rgba(255, 255, 255, 0.02);
}
```

---

## 7. Правила строгой изоляции Servarr Classic

Дизайн-система **Servarr Classic** (`[data-design="servarr"]`) предназначена для пользователей, привыкших к раскладке Sonarr / Radarr.

Для обеспечения ее абсолютной стабильности установлены следующие правила изоляции:
1. **Неприкосновенность файла `web/css/servarr.css`**: Запрещено вносить изменения в данный файл в рамках задач по редизайну Modern.
2. **Селекторная изоляция**: Все правила стиля Servarr строго инкапсулированы под префиксом `[data-design="servarr"]`.
3. **Фиксированная палитра**: При выборе стиля Servarr на элемент `<html>` программно устанавливается псевдо-тема `paper` (светлая рабочая область + графитовая навигация). Выбор пользовательской темы замораживается и снабжается уведомлением: «В дизайне Servarr Classic используется собственная нейтральная палитра».
4. **Структурная независимость DOM**: Шапка `#servarr-header` отображается исключительно при `[data-design="servarr"]` (`display: flex`). В дизайне Modern она принудительно скрыта (`display: none !important`).

---

## 8. GPU-безопасность и оптимизация производительности

1. **Глобальный переключатель размытия (`--glass-blur`)**:
   - `backdrop-filter: blur(...)` заставляет Chromium выполнять растрирование подложки на каждый перерисованный кадр.
   - По умолчанию `--glass-blur: none;`. Размытие включается только явно пользователем в меню «Эффекты стекла» (`data-glass="on"`).
   - Запрещено прописывать жесткие значения `backdrop-filter: blur(20px)` в компонентах без использования переменной `var(--glass-blur, none)`.
2. **Анимации только через `transform` и `opacity`**:
   - Запрещено анимировать `height`, `width`, `margin`, `padding`, `top`, `left`, так как это вызывает перерасчет Layout/Reflow.
   - Все модальные окна открываются через упругую пружинную трансформацию:
     ```css
     @keyframes modalSpringIn {
       from {
         opacity: 0;
         transform: scale(0.97) translateY(8px);
       }
       to {
         opacity: 1;
         transform: scale(1) translateY(0);
       }
     }
     ```
3. **Сохранение внешнего вида без ожидания бэкенда**:
   - Выбор темы, дизайна и полос прокрутки мгновенно записывается в `localStorage` и применяется к `<html>` синхронно до ответа сетевого запроса к `/api/v1/settings`.

---

## 9. Контрольный чеклист соответствия (Compliance Checklist)

Перед фиксацией любых изменений в коде выполните проверку по списку:
- [ ] В `web/index.html` и `web/js/app.js` нет ни одного эмодзи.
- [ ] В разметке нет иконок с ракетой (`rocket`), звездами (`star`, `sparkles`) или молниями (`zap`).
- [ ] Все рейтинги используют иконку `award`. Закрепление/избранное использует `pin`.
- [ ] Все панели подвкладок настроек являются прямыми потомками `<section id="tab-settings">`.
- [ ] Все ключи `data-i18n` присутствуют симметрично в `TRANSLATIONS.ru` и `TRANSLATIONS.en`.
- [ ] Файл `web/css/servarr.css` не содержит незапланированных диффов.
- [ ] Скрипты проходят валидацию синтаксиса `node --check web/js/app.js`.
- [ ] Автоматические тесты `test_frontend_mobile_layout.py`, `test_frontend_gpu_safety.py` и `test_i18n_coverage.py` завершаются со статусом OK.
- [ ] Общий объем данного документа составляет не менее 500 строк.
