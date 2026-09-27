#!/bin/sh
# Запускает Aliasarr от пользователя PUID:PGID, а не от root.
#
# Раньше процесс работал от root, а PUID/PGID использовались только для chown
# файлов медиатеки. Любая ошибка в обработке путей или загрузке файлов тогда
# выполнялась с правами root внутри контейнера и на смонтированных томах.
#
# ALIASARR_RUN_AS_ROOT=true оставляет прежнее поведение (например, если
# медиатека принадлежит root и перенастроить права нельзя).
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" != "0" ] || [ "${ALIASARR_RUN_AS_ROOT:-false}" = "true" ]; then
    exec "$@"
fi

case "$PUID" in ''|*[!0-9]*) echo "PUID must be numeric, got '$PUID'" >&2; exit 1 ;; esac
case "$PGID" in ''|*[!0-9]*) echo "PGID must be numeric, got '$PGID'" >&2; exit 1 ;; esac

# /config принадлежит приложению: база, бэкапы, обложки, SSL. Тома /data и
# /downloads не трогаем — ими владеет пользователь и торрент-клиент.
mkdir -p /config
if [ "$(stat -c '%u:%g' /config)" != "${PUID}:${PGID}" ] || \
   find /config -xdev \( ! -uid "$PUID" -o ! -gid "$PGID" \) -print -quit | grep -q .; then
    chown -R "${PUID}:${PGID}" /config
fi

exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all -- "$@"
