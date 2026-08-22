#!/usr/bin/env python3
"""Launcher for Aliasarr with dynamic HTTP/HTTPS (SSL) support and live reload."""

from __future__ import annotations

import os
import sys
import uvicorn

from app.database import SessionLocal, init_db
from app.services.settings_service import get_or_create_settings
from app.services.ssl_service import ensure_ssl_certificate


def run():
    # Настройка umask для Docker / Linux
    try:
        env_umask = os.getenv("UMASK", "0000").strip()
        os.umask(int(env_umask, 8))
    except Exception:
        try:
            os.umask(0o000)
        except Exception:
            pass

    try:
        init_db()
    except Exception as exc:
        print(f"[Aliasarr] Database initialization warning: {exc}")

    while True:
        db = SessionLocal()
        ssl_enabled = False
        ssl_cert_path = "/config/ssl/cert.pem"
        ssl_key_path = "/config/ssl/key.pem"
        ssl_port = 8989

        try:
            settings = get_or_create_settings(db)
            ssl_enabled = bool(getattr(settings, "ssl_enabled", False))
            ssl_port = int(getattr(settings, "ssl_port", 8989) or 8989)
            ssl_cert_path = getattr(settings, "ssl_cert_path", "/config/ssl/cert.pem") or "/config/ssl/cert.pem"
            ssl_key_path = getattr(settings, "ssl_key_path", "/config/ssl/key.pem") or "/config/ssl/key.pem"
        except Exception as exc:
            print(f"[Aliasarr] Warning: could not load SSL settings: {exc}")
        finally:
            db.close()

        port = int(os.getenv("PORT", ssl_port if ssl_enabled else 8989))
        host = os.getenv("HOST", "0.0.0.0")

        ssl_keyfile = None
        ssl_certfile = None

        if ssl_enabled:
            try:
                cert_info = ensure_ssl_certificate(ssl_cert_path, ssl_key_path)
                c_path = cert_info.get("cert_path")
                k_path = cert_info.get("key_path")
                if c_path and k_path and os.path.exists(c_path) and os.path.exists(k_path):
                    ssl_certfile = c_path
                    ssl_keyfile = k_path
                    print(f"[Aliasarr] Starting HTTPS server on https://{host}:{port} (Certificate: {ssl_certfile})")
                else:
                    print(f"[Aliasarr] SSL files not found, starting in HTTP mode on http://{host}:{port}")
            except Exception as exc:
                print(f"[Aliasarr] Error initializing SSL certificate: {exc}, starting in HTTP mode")
        else:
            print(f"[Aliasarr] Starting HTTP server on http://{host}:{port}")

        config = uvicorn.Config(
            "app.main:app",
            host=host,
            port=port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            access_log=False,
        )
        server = uvicorn.Server(config)

        import app.main as app_module
        app_module._active_server = server
        app_module._restart_requested = False

        server.run()

        if not getattr(app_module, "_restart_requested", False):
            break

        print("[Aliasarr] Restarting server to apply SSL / Port configuration...")


if __name__ == "__main__":
    run()
