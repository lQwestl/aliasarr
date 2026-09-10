---
name: custom-design
description: >-
  Используй этот скилл, когда нужно применить правила дизайна, стилистики и UI-компонентов Aliasarr.
  Скилл содержит исчерпывающие инструкции по верстке, оформлению, типографике и интерактивным элементам приложения.
---

# Руководство по дизайну Aliasarr (Neo-Glass & Vanguard Luxe Design Guidelines)

В данном руководстве зафиксированы стандарты верстки, дизайн-системы, микро-интерактивности и визуального оформления всего приложения **Aliasarr**.

---

## 🎨 1. Основные правила и принципы оформления

1. **Естественный регистр заголовков**:
   - Названия тайтлов на карточках в библиотеке оформляются в естественном регистре (первая буква заглавная, остальные строчные, без принудительного `text-transform: uppercase`), в точности как внутри модального окна тайтла.
2. **Таблица «Активность» (очередь загрузок)**:
   - В столбце «Размер» общий размер раздачи оформляется в моноширинный бейдж (`.badge .badge-secondary .queue-size-badge`).
   - В столбце «Прогресс» процент выполнения и скачанный объем данных оформляются в отдельные моноширинные бейджи (`.badge`) под прогресс-баром.
3. **Модальное окно карточки тайтла (`#show-modal`)**:
   - Верхний отступ (`padding-top: 52px`) обеспечивает свободное расположение кнопки закрытия (`.modal-close`) над баннером импорта (`.show-import-banner`) и постером.
4. **Стеклянные панели и карточки (`.settings-section-card`, `.card`)**:
   - Фон: многослойное стекло `background: var(--panel)` с эффектом `backdrop-filter: blur(16px)` и мягкой неоновой обводкой `border: 1px solid var(--border)`.
   - Внутренние отступы: `padding: 24px` (на экранах < 900px: `16px 18px`), скругление углов: `border-radius: 16px`.
   - При наведении (`:hover`): плавный транзишн границы и свечения.

---

## 🧩 2. Компонентная база UI/UX

### А. Заголовки секций с иконками (`.settings-card-header`)
Каждая карточка или смысловой блок должен начинаться с акцентного заголовка:
```html
<div class="settings-card-header">
  <div class="settings-card-header-left">
    <div class="settings-card-icon-badge">
      <i data-lucide="icon-name"></i>
    </div>
    <div class="settings-card-title-wrap">
      <h3 data-i18n="section.title">Заголовок секции</h3>
      <p class="subtitle" data-i18n="section.subtitle">Поясняющий подзаголовок</p>
    </div>
  </div>
</div>
```

### Б. 2-Колоночная адаптивная сетка полей (`.form-grid-modern`)
Для форм настроек и модальных окон используется эргономичная CSS-grid сетка:
```html
<div class="form-grid-modern">
  <div class="settings-field-group">
    <label class="settings-field-label">
      <span data-i18n="field.name">Название поля</span>
      <span class="settings-field-hint">(подсказка / единицы)</span>
    </label>
    <input class="input" type="text">
  </div>
  
  <div class="settings-field-group" style="grid-column: 1 / -1;">
    <!-- Поле на всю ширину (full width) -->
  </div>
</div>
```

### В. Современные переключатели iOS-стиля (`.switch-toggle`)
Вместо обычных плоских чекбоксов всегда используется семантический тумблер:
```html
<label class="switch-toggle">
  <input id="my-feature-enabled" type="checkbox" checked>
  <span class="switch-slider"></span>
  <span class="switch-title" data-i18n="feature.title">Включить функцию</span>
  <span class="switch-desc" data-i18n="feature.desc">Подробное описание назначения переключателя</span>
</label>
```

### Г. Интерактивные чип-карточки событий и прав доступа (`.triggers-grid`, `.trigger-chip-card`)
Для выбора наборов событий, разрешений или режимов:
```html
<div class="triggers-grid">
  <label class="trigger-chip-card">
    <input type="checkbox" id="trigger-id" checked>
    <div class="trigger-icon"><i data-lucide="bell"></i></div>
    <span class="trigger-label" data-i18n="trigger.label">Событие</span>
  </label>
</div>
```

### Д. Вложенные блоки провайдеров (`.provider-fields-box`)
Для зависимых или динамически переключаемых параметров:
```html
<div class="provider-fields-box">
  <div class="form-grid-modern">
    <!-- Поля провайдера -->
  </div>
</div>
```

### Е. Терминальные команды с кнопкой копирования (`.terminal-code-box`, `.terminal-copy-btn`)
Для консольных команд Docker / CLI:
```html
<div class="terminal-code-box">
  <pre>docker exec -it aliasarr command</pre>
  <button type="button" class="terminal-copy-btn" onclick="copyCode(this)" title="Копировать"><i data-lucide="copy" class="ico-xs"></i></button>
</div>
```

### Ж. Бейджи категорий (`.category-badge-chip`)
Для разметки типов контента:
- Фильмы: `.category-badge-movies` (янтарно-золотой)
- Сериалы: `.category-badge-series` (бирюзовый неон)
- Аниме: `.category-badge-anime` (неоновый малиновый)

---

## 🌓 3. Цветовые темы и контраст

- Поддерживаются 4 темы: **Неоновая полночь** (`dark`), **Обсидиан** (`obsidian`), **Дракула** (`dracula`), **Полярный день** (`light`).
- Все цвета, фоны и рамки должны строго использовать CSS-переменные (`var(--panel)`, `var(--panel-alt)`, `var(--border)`, `var(--text)`, `var(--text-muted)`, `var(--teal)`, `var(--accent)`, `var(--success)`, `var(--danger)`).
- В светлой теме (`[data-theme="light"]`) элементы должны оставаться четко читаемыми, с контрастными тенями и светлыми карточками.

---

## ⚙️ 4. Сохранение логики и совместимости
- **Строгое сохранение DOM ID и классов**: Любой существующий ID элемента (`#setting-...`, `#user-...`, `#idx-...`, `#dc-...`, `#nt-...`, `#modal-...`), привязанный к логике JavaScript (`web/js/app.js`), должен быть сохранен без переименований.
- **Двуязычность (i18n)**: Все текстовые надписи должны сопровождаться атрибутом `data-i18n` и иметь записи в `TRANSLATIONS.ru` и `TRANSLATIONS.en`.
- **Автоматический пуш**: Любые завершенные изменения в коде должны быть закоммичены и отправлены в репозиторий GitHub (`git push origin main`).
