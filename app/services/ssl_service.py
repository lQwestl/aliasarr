"""Сервис генерации и автоматического продления самоподписанных SSL-сертификатов (HTTPS) для Aliasarr.
Сертификат выпускается на максимальный срок (36500 дней ~100 лет).
При истечении срока (или за 30 дней до окончания) сертификат автоматически самовыпускается заново.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import logging
import os
import socket
from typing import Any, Optional

logger = logging.getLogger("aliasarr.ssl")

DEFAULT_SSL_CERT_PATH = "/config/ssl/cert.pem"
DEFAULT_SSL_KEY_PATH = "/config/ssl/key.pem"
MAX_VALIDITY_DAYS = 36500  # ~100 лет (максимальный срок действия)
RENEW_BEFORE_DAYS = 30     # Перевыпускать за 30 дней до истечения


def _get_all_local_ips() -> list[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return list(ips)


def _resolve_ssl_paths(cert_path: Optional[str] = None, key_path: Optional[str] = None) -> tuple[str, str]:
    c_path = cert_path or DEFAULT_SSL_CERT_PATH
    k_path = key_path or DEFAULT_SSL_KEY_PATH

    # Если путь /config недоступен для записи (например локальный dev вне контейнера),
    # используем локальную папку config/ssl в рабочей директории
    try:
        os.makedirs(os.path.dirname(os.path.abspath(c_path)), exist_ok=True)
    except Exception:
        local_dir = os.path.join(os.getcwd(), "config", "ssl")
        os.makedirs(local_dir, exist_ok=True)
        c_path = os.path.join(local_dir, "cert.pem")
        k_path = os.path.join(local_dir, "key.pem")

    return c_path, k_path


def trigger_server_restart(delay_seconds: float = 0.8) -> None:
    """Планирует мягкий перезапуск ASGI сервера uvicorn для применения параметров SSL/HTTPS."""
    import threading
    import time

    def _do_restart():
        time.sleep(delay_seconds)
        try:
            import app.main as app_module
            server = getattr(app_module, "_active_server", None)
            if server is not None:
                app_module._restart_requested = True
                server.should_exit = True
                logger.info("Запрошен перезапуск uvicorn сервера для смены режима SSL...")
                return
        except Exception as exc:
            logger.warning("Ошибка при вызове мягкого перезапуска сервера: %s", exc)

        logger.info("Завершение процесса для перезапуска контейнера...")
        os._exit(0)

    t = threading.Thread(target=_do_restart, daemon=True)
    t.start()


def generate_self_signed_certificate(
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    validity_days: int = MAX_VALIDITY_DAYS,
) -> dict[str, Any]:
    """Генерирует новый приватный ключ RSA 2048 и самоподписанный X.509 сертификат на validity_days дней."""
    c_path, k_path = _resolve_ssl_paths(cert_path, key_path)

    os.makedirs(os.path.dirname(os.path.abspath(c_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(k_path)), exist_ok=True)

    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        # 1. Генерация приватного ключа RSA 2048
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )

        # 2. Формирование Subject / Issuer
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Aliasarr"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Aliasarr Self-Signed HTTPS"),
            x509.NameAttribute(NameOID.COMMON_NAME, "aliasarr.local"),
        ])

        # 3. Subject Alternative Names (SAN)
        san_list = [
            x509.DNSName("localhost"),
            x509.DNSName("aliasarr"),
            x509.DNSName("aliasarr.local"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
            x509.IPAddress(ipaddress.IPv6Address("::1")),
        ]
        for ip_str in _get_all_local_ips():
            try:
                san_list.append(x509.IPAddress(ipaddress.IPv4Address(ip_str)))
            except Exception:
                pass

        now = dt.datetime.now(dt.timezone.utc)
        valid_to = now + dt.timedelta(days=validity_days)

        # 4. Построение сертификата
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=10))
            .not_valid_after(valid_to)
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        )

        certificate = builder.sign(
            private_key=private_key,
            algorithm=hashes.SHA256(),
            backend=default_backend(),
        )

        # 5. Сохранение ключа и сертификата в PEM
        key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)

        with open(k_path, "wb") as f:
            f.write(key_bytes)
        try:
            os.chmod(k_path, 0o600)
        except Exception:
            pass

        with open(c_path, "wb") as f:
            f.write(cert_bytes)

        logger.info("Самоподписанный SSL-сертификат Aliasarr успешно создан на %d дней: %s", validity_days, c_path)
    except ImportError:
        # Fallback через утилиту openssl если cryptography не установлена
        import subprocess
        logger.warning("Библиотека cryptography не найдена, используем системный openssl")
        cmd = [
            "openssl", "req", "-x509", "-nodes",
            "-days", str(validity_days),
            "-newkey", "rsa:2048",
            "-keyout", k_path,
            "-out", c_path,
            "-subj", "/C=US/O=Aliasarr/OU=Aliasarr HTTPS/CN=aliasarr.local",
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    return get_ssl_certificate_info(cert_path=c_path, key_path=k_path)


def get_ssl_certificate_info(cert_path: Optional[str] = None, key_path: Optional[str] = None) -> dict[str, Any]:
    """Возвращает метаданные и статус SSL-сертификата."""
    c_path, k_path = _resolve_ssl_paths(cert_path, key_path)

    if not os.path.exists(c_path) or not os.path.exists(k_path):
        return {
            "exists": False,
            "cert_path": c_path,
            "key_path": k_path,
            "valid": False,
            "valid_from": None,
            "valid_to": None,
            "days_remaining": 0,
            "issuer": None,
            "subject": None,
            "fingerprint_sha256": None,
            "is_self_signed": True,
            "auto_renew": True,
        }

    try:
        with open(c_path, "rb") as f:
            cert_data = f.read()

        # SHA-256 Fingerprint
        fp_hex = hashlib.sha256(cert_data).hexdigest().upper()
        fingerprint = ":".join(fp_hex[i:i+2] for i in range(0, len(fp_hex), 2))

        try:
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend

            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            try:
                valid_from_dt = cert.not_valid_before_utc
                valid_to_dt = cert.not_valid_after_utc
            except AttributeError:
                valid_from_dt = cert.not_valid_before.replace(tzinfo=dt.timezone.utc)
                valid_to_dt = cert.not_valid_after.replace(tzinfo=dt.timezone.utc)

            now = dt.datetime.now(dt.timezone.utc)
            days_left = max(0, (valid_to_dt - now).days)
            is_valid = valid_to_dt > now

            issuer_str = cert.issuer.rfc4514_string()
            subject_str = cert.subject.rfc4514_string()

            return {
                "exists": True,
                "cert_path": c_path,
                "key_path": k_path,
                "valid": is_valid,
                "valid_from": valid_from_dt.isoformat(),
                "valid_to": valid_to_dt.isoformat(),
                "days_remaining": days_left,
                "issuer": issuer_str,
                "subject": subject_str,
                "fingerprint_sha256": fingerprint,
                "is_self_signed": True,
                "auto_renew": True,
            }
        except Exception as exc:
            logger.warning("Не удалось распарсить сертификат через cryptography: %s", exc)
            return {
                "exists": True,
                "cert_path": c_path,
                "key_path": k_path,
                "valid": True,
                "valid_from": None,
                "valid_to": None,
                "days_remaining": MAX_VALIDITY_DAYS,
                "issuer": "Aliasarr Self-Signed",
                "subject": "aliasarr.local",
                "fingerprint_sha256": fingerprint,
                "is_self_signed": True,
                "auto_renew": True,
            }
    except Exception as e:
        logger.error("Ошибка чтения SSL сертификата %s: %s", c_path, e)
        return {
            "exists": False,
            "cert_path": c_path,
            "key_path": k_path,
            "valid": False,
            "valid_from": None,
            "valid_to": None,
            "days_remaining": 0,
            "issuer": None,
            "subject": None,
            "fingerprint_sha256": None,
            "is_self_signed": True,
            "auto_renew": True,
        }


def ensure_ssl_certificate(
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    force_renew: bool = False,
) -> dict[str, Any]:
    """Проверяет наличие и валидность SSL сертификата. Если отсутствует или протухает (<30 дней) — самовыпускает заново на 36500 дней."""
    c_path, k_path = _resolve_ssl_paths(cert_path, key_path)

    if force_renew or not os.path.exists(c_path) or not os.path.exists(k_path):
        logger.info("Выпуск нового самоподписанного SSL-сертификата Aliasarr...")
        return generate_self_signed_certificate(cert_path=c_path, key_path=k_path)

    info = get_ssl_certificate_info(cert_path=c_path, key_path=k_path)
    if not info["valid"] or info["days_remaining"] <= RENEW_BEFORE_DAYS:
        logger.info("SSL-сертификат протухает (осталось %d дней). Автоматический самовыпуск...", info["days_remaining"])
        return generate_self_signed_certificate(cert_path=c_path, key_path=k_path)

    return info
