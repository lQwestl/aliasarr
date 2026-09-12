FROM python:3.11-slim

WORKDIR /app

# Системные зависимости (компиляция, mkvtoolnix для склейки, ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    mkvtoolnix \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run.py .
COPY app ./app
COPY web ./web

# Тома: конфиг/БД, данные, папка загрузок
VOLUME ["/config", "/data", "/downloads"]

ENV DATABASE_URL=sqlite:////config/aliasarr.db
ENV PYTHONUNBUFFERED=1
ARG COMMIT_HASH=""
ENV COMMIT_HASH=${COMMIT_HASH}

EXPOSE 8989

CMD ["python", "run.py"]
