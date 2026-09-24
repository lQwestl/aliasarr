"""Сквозные проверки аутентификации через настоящее ASGI-приложение.

До этого набора маршруты вызывались как функции, поэтому middleware, CORS и
разбор заголовков ни разу не проверялись в сборе. Здесь запросы проходят весь
стек: ApiKeyMiddleware, зависимости FastAPI и обработчики.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth as auth_module
import app.main as main_module
from app.api import auth_routes
from app.database import get_db
from app.models.db import Base, NotificationConfig, User
from app.services.settings_service import get_or_create_settings, hash_password
from app.services.user_service import ALL_PERMISSIONS

OWNER_PASSWORD = "owner-password-1"


class _AppCase(unittest.TestCase):
    login_enabled = True
    local_bypass = True

    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        db = self.Session()
        settings = get_or_create_settings(db)
        settings.login_enabled = self.login_enabled
        settings.auth_disabled_for_local_addresses = self.local_bypass
        settings.username = "admin"
        self.api_key = settings.api_key
        owner = User(
            username="admin", password_hash=hash_password(OWNER_PASSWORD),
            is_admin=True, is_owner=True, enabled=True, permissions={p: True for p in ALL_PERMISSIONS},
        )
        db.add(owner)
        db.commit()
        db.close()

        def _get_db():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        main_module.app.dependency_overrides[get_db] = _get_db
        self._patches = [
            patch.object(auth_module, "SessionLocal", self.Session),
            patch.object(main_module, "SessionLocal", self.Session),
            patch.dict(os.environ, {}, clear=False),
        ]
        for p in self._patches:
            p.start()
        for name in ("ALIASARR_TRUSTED_PROXIES", "ALIASARR_TRUST_CF_CONNECTING_IP", "ALIASARR_ALLOWED_HOSTS"):
            os.environ.pop(name, None)
        auth_module.invalidate_session_cache()
        auth_routes.reset_login_throttle()

    def tearDown(self):
        main_module.app.dependency_overrides.pop(get_db, None)
        for p in reversed(self._patches):
            p.stop()
        auth_module.invalidate_session_cache()

    def request(self, method, path, *, peer="192.168.1.20", host="aliasarr:8989", headers=None, **kwargs):
        all_headers = {"Host": host}
        all_headers.update(headers or {})

        async def _send():
            transport = httpx.ASGITransport(app=main_module.app, client=(peer, 50000))
            async with httpx.AsyncClient(transport=transport, base_url=f"http://{host}") as client:
                return await client.request(method, path, headers=all_headers, **kwargs)

        return asyncio.run(_send())

    def add_user(self, username, *, is_admin=False, permissions=None, password="user-password-1"):
        db = self.Session()
        user = User(
            username=username, password_hash=hash_password(password), is_admin=is_admin,
            is_owner=False, enabled=True, permissions=permissions or {},
        )
        db.add(user)
        db.commit()
        user_id = user.id
        db.close()
        return user_id

    def login(self, username, password, peer="93.184.216.9", host="aliasarr.example.com"):
        resp = self.request(
            "POST", "/api/v1/auth/login", peer=peer, host=host,
            json={"username": username, "password": password},
        )
        return resp


class TestCorsAndCrossSiteRequests(_AppCase):
    def test_cross_origin_reads_get_no_cors_grant(self):
        resp = self.request("GET", "/api/v1/settings", headers={"Origin": "https://evil.example"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("access-control-allow-origin", resp.headers)

    def test_preflight_from_other_site_is_not_allowed(self):
        resp = self.request("OPTIONS", "/api/v1/settings", headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "PUT",
        })
        self.assertNotIn("access-control-allow-origin", resp.headers)

    def test_cross_site_write_through_local_bypass_is_rejected(self):
        resp = self.request(
            "POST", "/api/v1/settings/regenerate-api-key",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "cross_site_request")

    def test_same_site_neighbour_app_is_rejected(self):
        resp = self.request(
            "POST", "/api/v1/settings/regenerate-api-key",
            headers={"Origin": "http://aliasarr:8080", "Sec-Fetch-Site": "same-site"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_same_origin_write_is_allowed(self):
        resp = self.request(
            "POST", "/api/v1/settings/regenerate-api-key",
            headers={"Origin": "http://aliasarr:8989", "Sec-Fetch-Site": "same-origin"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_origin_fallback_without_fetch_metadata(self):
        resp = self.request(
            "POST", "/api/v1/settings/regenerate-api-key",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_api_key_header_is_not_subject_to_csrf_checks(self):
        resp = self.request(
            "POST", "/api/v1/settings/regenerate-api-key", peer="93.184.216.50", host="aliasarr.example.com",
            headers={"X-Api-Key": self.api_key, "Origin": "https://dashboard.example", "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_cross_site_login_is_rejected(self):
        resp = self.request(
            "POST", "/api/v1/auth/login",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
            json={"username": "admin", "password": OWNER_PASSWORD},
        )
        self.assertEqual(resp.status_code, 403)


class TestLocalBypassHostCheck(_AppCase):
    def test_public_host_name_does_not_get_local_bypass(self):
        # DNS rebinding: чужой домен указывает на адрес Aliasarr в LAN.
        resp = self.request("GET", "/api/v1/settings", host="rebind.attacker.example")
        self.assertEqual(resp.status_code, 401)

    def test_ip_and_internal_names_keep_local_bypass(self):
        for host in ("192.168.1.5:8989", "aliasarr:8989", "nas.local", "media.home.arpa"):
            with self.subTest(host=host):
                resp = self.request("GET", "/api/v1/settings", host=host)
                self.assertEqual(resp.status_code, 200)

    def test_allowed_hosts_env_extends_the_list(self):
        os.environ["ALIASARR_ALLOWED_HOSTS"] = "media.example.org"
        resp = self.request("GET", "/api/v1/settings", host="media.example.org")
        self.assertEqual(resp.status_code, 200)


class TestForwardedClientIp(_AppCase):
    def test_spoofed_leftmost_forwarded_address_is_ignored(self):
        os.environ["ALIASARR_TRUSTED_PROXIES"] = "172.18.0.5/32"
        resp = self.request(
            "GET", "/api/v1/settings", peer="172.18.0.5", host="aliasarr",
            headers={"X-Forwarded-For": "192.168.1.10, 93.184.216.7"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_real_lan_client_behind_proxy_keeps_bypass(self):
        os.environ["ALIASARR_TRUSTED_PROXIES"] = "172.18.0.5/32"
        resp = self.request(
            "GET", "/api/v1/settings", peer="172.18.0.5", host="aliasarr",
            headers={"X-Forwarded-For": "192.168.1.10"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_cf_connecting_ip_needs_explicit_opt_in(self):
        os.environ["ALIASARR_TRUSTED_PROXIES"] = "172.18.0.5/32"
        headers = {"CF-Connecting-IP": "10.0.0.1", "X-Forwarded-For": "93.184.216.7"}
        resp = self.request("GET", "/api/v1/settings", peer="172.18.0.5", host="aliasarr", headers=headers)
        self.assertEqual(resp.status_code, 401)
        os.environ["ALIASARR_TRUST_CF_CONNECTING_IP"] = "true"
        resp = self.request("GET", "/api/v1/settings", peer="172.18.0.5", host="aliasarr", headers=headers)
        self.assertEqual(resp.status_code, 200)


class TestLoginHardening(_AppCase):
    def test_status_does_not_reveal_owner_name_before_login(self):
        resp = self.request("GET", "/api/v1/auth/status", peer="93.184.216.9", host="aliasarr.example.com")
        body = resp.json()
        self.assertFalse(body["authenticated"])
        self.assertIsNone(body["username"])

    def test_repeated_failures_are_throttled(self):
        for _ in range(auth_routes._LOGIN_MAX_FAILURES_PER_USERNAME):
            self.assertEqual(self.login("admin", "wrong").status_code, 401)
        resp = self.login("admin", OWNER_PASSWORD)
        self.assertEqual(resp.status_code, 429)
        self.assertIn("retry-after", resp.headers)

    def test_successful_login_sets_secure_cookie_behind_https_proxy(self):
        os.environ["ALIASARR_TRUSTED_PROXIES"] = "172.18.0.5/32"
        resp = self.request(
            "POST", "/api/v1/auth/login", peer="172.18.0.5", host="aliasarr.example.com",
            headers={"X-Forwarded-For": "93.184.216.9", "X-Forwarded-Proto": "https"},
            json={"username": "admin", "password": OWNER_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        cookie = resp.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)

    def test_enforced_2fa_blocks_external_login_without_totp(self):
        db = self.Session()
        settings = get_or_create_settings(db)
        settings.totp_2fa_enabled = True
        settings.totp_2fa_policy = "enforce_all"
        db.commit()
        db.close()
        self.assertEqual(self.login("admin", OWNER_PASSWORD).status_code, 403)
        # Из локальной сети вход по-прежнему возможен, чтобы 2FA можно было настроить.
        self.assertEqual(self.login("admin", OWNER_PASSWORD, peer="192.168.1.20", host="aliasarr").status_code, 200)

    def _session_cookie(self, username, password):
        resp = self.login(username, password)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.cookies.get(auth_module.SESSION_COOKIE_NAME)

    def test_disabling_2fa_requires_password(self):
        token = self._session_cookie("admin", OWNER_PASSWORD)
        headers = {"Cookie": f"{auth_module.SESSION_COOKIE_NAME}={token}", "Sec-Fetch-Site": "same-origin"}
        common = {"peer": "93.184.216.9", "host": "aliasarr.example.com", "headers": headers}
        self.assertEqual(self.request("POST", "/api/v1/auth/2fa/disable", json={}, **common).status_code, 400)
        self.assertEqual(
            self.request("POST", "/api/v1/auth/2fa/disable", json={"password": OWNER_PASSWORD}, **common).status_code,
            200,
        )

    def test_password_change_revokes_other_sessions(self):
        first = self._session_cookie("admin", OWNER_PASSWORD)
        second = self._session_cookie("admin", OWNER_PASSWORD)
        common = {"peer": "93.184.216.9", "host": "aliasarr.example.com"}
        resp = self.request(
            "POST", "/api/v1/auth/change-password",
            headers={"Cookie": f"{auth_module.SESSION_COOKIE_NAME}={first}", "Sec-Fetch-Site": "same-origin"},
            json={"current_password": OWNER_PASSWORD, "new_password": "brand-new-password"},
            **common,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        still_first = self.request("GET", "/api/v1/auth/me", headers={"Cookie": f"{auth_module.SESSION_COOKIE_NAME}={first}"}, **common)
        revoked = self.request("GET", "/api/v1/auth/me", headers={"Cookie": f"{auth_module.SESSION_COOKIE_NAME}={second}"}, **common)
        self.assertEqual(still_first.status_code, 200)
        self.assertEqual(revoked.status_code, 401)

    def test_short_passwords_are_rejected(self):
        token = self._session_cookie("admin", OWNER_PASSWORD)
        resp = self.request(
            "POST", "/api/v1/auth/change-password", peer="93.184.216.9", host="aliasarr.example.com",
            headers={"Cookie": f"{auth_module.SESSION_COOKIE_NAME}={token}", "Sec-Fetch-Site": "same-origin"},
            json={"current_password": OWNER_PASSWORD, "new_password": "1234"},
        )
        self.assertEqual(resp.status_code, 400)


class TestUserManagementEscalation(_AppCase):
    def setUp(self):
        super().setUp()
        self.manager_id = self.add_user("manager", permissions={"manage_users": True, "view_library": True})
        self.admin_id = self.add_user("second-admin", is_admin=True, permissions={p: True for p in ALL_PERMISSIONS})
        resp = self.login("manager", "user-password-1")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.cookie = {"Cookie": f"{auth_module.SESSION_COOKIE_NAME}={resp.cookies.get(auth_module.SESSION_COOKIE_NAME)}",
                       "Sec-Fetch-Site": "same-origin"}

    def call(self, method, path, **kwargs):
        return self.request(method, path, peer="93.184.216.9", host="aliasarr.example.com", headers=self.cookie, **kwargs)

    def test_manager_cannot_create_admin(self):
        resp = self.call("POST", "/api/v1/users", json={"username": "evil", "password": "long-password", "is_admin": True})
        self.assertEqual(resp.status_code, 403)
        resp = self.call("POST", "/api/v1/users", json={"username": "evil2", "password": "long-password", "role": "admin"})
        self.assertEqual(resp.status_code, 403)

    def test_manager_cannot_grant_permissions_they_lack(self):
        resp = self.call("POST", "/api/v1/users", json={
            "username": "helper", "password": "long-password", "permissions": {"manage_settings": True},
        })
        self.assertEqual(resp.status_code, 403)

    def test_manager_can_create_user_within_own_rights(self):
        resp = self.call("POST", "/api/v1/users", json={
            "username": "viewer", "password": "long-password", "permissions": {"view_library": True},
        })
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_manager_cannot_touch_admin_accounts(self):
        self.assertEqual(self.call("POST", f"/api/v1/users/{self.admin_id}/reset-password",
                                   json={"new_password": "taken-over-pass"}).status_code, 403)
        self.assertEqual(self.call("POST", f"/api/v1/users/{self.admin_id}/regenerate-api-key").status_code, 403)
        self.assertEqual(self.call("DELETE", f"/api/v1/users/{self.admin_id}").status_code, 403)

    def test_manager_cannot_restore_or_download_backups(self):
        self.assertEqual(self.call("POST", "/api/v1/backups/restore-existing", json={"name": "x.zip"}).status_code, 403)
        self.assertEqual(self.call("GET", "/api/v1/backups/x.zip/download").status_code, 403)


class TestSecretsAndHeaders(_AppCase):
    def test_notification_secrets_are_masked_for_viewers(self):
        db = self.Session()
        db.add(NotificationConfig(name="tg", type="telegram", settings={"bot_token": "123:SECRET", "chat_id": "42"}))
        db.commit()
        db.close()
        self.add_user("viewer", permissions={"view_library": True})
        resp = self.login("viewer", "user-password-1")
        cookie = {"Cookie": f"{auth_module.SESSION_COOKIE_NAME}={resp.cookies.get(auth_module.SESSION_COOKIE_NAME)}"}
        body = self.request("GET", "/api/v1/notifications", peer="93.184.216.9",
                            host="aliasarr.example.com", headers=cookie).json()
        self.assertEqual(body[0]["settings"]["bot_token"], "")
        self.assertEqual(body[0]["settings"]["chat_id"], "42")

        admin = self.request("GET", "/api/v1/notifications", headers={"X-Api-Key": self.api_key},
                             peer="93.184.216.9", host="aliasarr.example.com").json()
        self.assertEqual(admin[0]["settings"]["bot_token"], "123:SECRET")

    def test_security_headers_are_set(self):
        resp = self.request("GET", "/")
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", resp.headers.get("content-security-policy", ""))

    def test_session_cache_is_bounded(self):
        db = self.Session()
        with patch.object(auth_module, "_SESSION_CACHE_MAX_ENTRIES", 50):
            for i in range(200):
                auth_module._get_valid_session_user(db, f"garbage-token-{i}")
            self.assertLessEqual(len(auth_module._SESSION_USER_CACHE), 50)
        db.close()


if __name__ == "__main__":
    unittest.main()
