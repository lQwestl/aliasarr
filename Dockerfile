# --- Aliasarr Application Image -----------------------------------------------
# Базовый образ ghcr.io/lqwestl/aliasarr-base содержит:
# - Python 3.11-slim
# - Оптимизированный SQLite 3.53.4 (собранный из исходников)
# - ffmpeg, mkvtoolnix, ca-certificates, curl
# - Предустановленные зависимости из requirements.txt
ARG BASE_IMAGE=ghcr.io/lqwestl/aliasarr-base:3.11
FROM ${BASE_IMAGE}

WORKDIR /app

# Быстрая проверка/доустановка зависимостей, если requirements.txt изменился в ветке
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
