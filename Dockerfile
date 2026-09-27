# --- Этап сборки: SQLite из исходников -------------------------------------
# Компиляторы нужны только здесь и в итоговый образ не попадают.
FROM python:3.11-slim AS sqlite-build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Сборка и установка новейшей оптимизированной версии SQLite 3.53.4 из исходников
ARG SQLITE_YEAR=2026
ARG SQLITE_VERSION=3530400
# SHA3-256 архива со страницы https://www.sqlite.org/download.html. Если значение
# задано, архив с другим содержимым не будет собран; пустое значение пропускает
# проверку (с предупреждением в логе сборки).
ARG SQLITE_SHA3_256=""
RUN mkdir -p /tmp/sqlite && cd /tmp/sqlite && \
    curl -fsSL "https://www.sqlite.org/${SQLITE_YEAR}/sqlite-autoconf-${SQLITE_VERSION}.tar.gz" -o sqlite.tar.gz && \
    python3 -c "import hashlib, sys; \
digest = hashlib.sha3_256(open('sqlite.tar.gz', 'rb').read()).hexdigest(); \
expected = '${SQLITE_SHA3_256}'.strip().lower(); \
print('>>> sqlite.tar.gz SHA3-256:', digest); \
sys.exit(0) if not expected else None; \
sys.exit(0 if digest == expected else 'SQLite archive checksum mismatch')" && \
    if [ -z "${SQLITE_SHA3_256}" ]; then echo ">>> WARNING: SQLITE_SHA3_256 is not set, archive integrity was not verified"; fi && \
    tar -xzf sqlite.tar.gz --strip-components=1 && \
    CFLAGS="-O3 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_JSON1 -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_STAT4 -DSQLITE_ENABLE_DBSTAT_VTAB" \
    ./configure --prefix=/opt/sqlite --enable-all --disable-static && \
    make -j"$(nproc)" && \
    make install


# --- Итоговый образ ----------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

# Системные зависимости (mkvtoolnix для склейки, ffmpeg для анализа файлов, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    mkvtoolnix \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Подменяем системную libsqlite3 собранной версией, чтобы модуль sqlite3 в Python
# использовал именно её.
COPY --from=sqlite-build /opt/sqlite/lib/ /tmp/sqlite-lib/
RUN for dir in /usr/lib/*-linux-gnu /lib/*-linux-gnu /usr/local/lib; do \
        if [ -d "$dir" ]; then \
            find "$dir" -maxdepth 1 -name "libsqlite3.so*" -delete; \
            cp -a /tmp/sqlite-lib/libsqlite3.so* "$dir/"; \
        fi \
    done && \
    rm -rf /tmp/sqlite-lib && \
    ldconfig && \
    python3 -c "import sqlite3; print('>>> Verified SQLite version in Python:', sqlite3.sqlite_version); assert sqlite3.sqlite_version.startswith('3.53'), f'SQLite version mismatch: {sqlite3.sqlite_version}'"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run.py .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY app ./app
COPY web ./web
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

# Тома: конфиг/БД, данные, папка загрузок
VOLUME ["/config", "/data", "/downloads"]

ENV DATABASE_URL=sqlite:////config/aliasarr.db
ENV PYTHONUNBUFFERED=1
ARG COMMIT_HASH=""
ENV COMMIT_HASH=${COMMIT_HASH}

EXPOSE 8989

# Процесс запускается от PUID:PGID (по умолчанию 1000:1000), а не от root.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "run.py"]
