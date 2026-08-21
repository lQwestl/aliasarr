import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.auth import ApiKeyMiddleware, _PUBLIC_PATHS_PREFIXES
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestAuthDocsSecurity(unittest.TestCase):
    def setUp(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")

    def test_docs_and_openapi_not_in_public_paths(self):
        self.assertNotIn("/docs", _PUBLIC_PATHS_PREFIXES)
        self.assertNotIn("/redoc", _PUBLIC_PATHS_PREFIXES)
        self.assertNotIn("/openapi.json", _PUBLIC_PATHS_PREFIXES)

    def test_unauthenticated_docs_request_redirects_to_login(self):
        import asyncio

        middleware = ApiKeyMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/docs"
        mock_request.cookies = {}
        mock_request.headers = {}
        mock_request.query_params = {}

        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.login_enabled = True
        mock_settings.api_key = "secret_key"

        async def run():
            with patch("app.auth.SessionLocal", return_value=mock_db), \
                 patch("app.auth.get_or_create_settings", return_value=mock_settings), \
                 patch("app.auth._get_valid_session_user", return_value=(False, None)):
                call_next = AsyncMock()
                resp = await middleware.dispatch(mock_request, call_next)
                self.assertEqual(resp.status_code, 303)
                self.assertEqual(resp.headers.get("location"), "/")
                call_next.assert_not_called()

        asyncio.run(run())

    def test_unauthenticated_openapi_request_returns_401(self):
        import asyncio

        middleware = ApiKeyMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/openapi.json"
        mock_request.cookies = {}
        mock_request.headers = {}
        mock_request.query_params = {}

        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.login_enabled = True
        mock_settings.api_key = "secret_key"

        async def run():
            with patch("app.auth.SessionLocal", return_value=mock_db), \
                 patch("app.auth.get_or_create_settings", return_value=mock_settings), \
                 patch("app.auth._get_valid_session_user", return_value=(False, None)):
                call_next = AsyncMock()
                resp = await middleware.dispatch(mock_request, call_next)
                self.assertEqual(resp.status_code, 401)
                call_next.assert_not_called()

        asyncio.run(run())

    def test_authenticated_docs_request_passes_through(self):
        import asyncio

        middleware = ApiKeyMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/docs"
        mock_request.cookies = {"aliasarr_session": "valid_token"}
        mock_request.headers = {}
        mock_request.query_params = {}

        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.login_enabled = True

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "admin"

        async def run():
            with patch("app.auth.SessionLocal", return_value=mock_db), \
                 patch("app.auth.get_or_create_settings", return_value=mock_settings), \
                 patch("app.auth._get_valid_session_user", return_value=(True, mock_user)):
                mock_next_resp = MagicMock()
                call_next = AsyncMock(return_value=mock_next_resp)
                resp = await middleware.dispatch(mock_request, call_next)
                self.assertEqual(resp, mock_next_resp)
                call_next.assert_called_once_with(mock_request)

        asyncio.run(run())

    def test_unauthenticated_quality_guide_request_redirects_to_login(self):
        import asyncio

        middleware = ApiKeyMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/quality-guide"
        mock_request.cookies = {}
        mock_request.headers = {}
        mock_request.query_params = {}

        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.login_enabled = True
        mock_settings.api_key = "secret_key"

        async def run():
            with patch("app.auth.SessionLocal", return_value=mock_db), \
                 patch("app.auth.get_or_create_settings", return_value=mock_settings), \
                 patch("app.auth._get_valid_session_user", return_value=(False, None)):
                call_next = AsyncMock()
                resp = await middleware.dispatch(mock_request, call_next)
                self.assertEqual(resp.status_code, 303)
                self.assertEqual(resp.headers.get("location"), "/")
                call_next.assert_not_called()

        asyncio.run(run())

    def test_unauthenticated_static_html_request_blocks_direct_access(self):
        import asyncio

        middleware = ApiKeyMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/ui/static/quality-guide.html"
        mock_request.cookies = {}
        mock_request.headers = {}
        mock_request.query_params = {}

        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.login_enabled = True
        mock_settings.api_key = "secret_key"

        async def run():
            with patch("app.auth.SessionLocal", return_value=mock_db), \
                 patch("app.auth.get_or_create_settings", return_value=mock_settings), \
                 patch("app.auth._get_valid_session_user", return_value=(False, None)):
                call_next = AsyncMock()
                resp = await middleware.dispatch(mock_request, call_next)
                self.assertEqual(resp.status_code, 303)
                call_next.assert_not_called()

        asyncio.run(run())

    def test_new_user_creation_and_authentication(self):
        from app.services.settings_service import hash_password, verify_password

        raw_pwd = "mySecretPassword123"
        hashed = hash_password(raw_pwd)

        self.assertTrue(verify_password(raw_pwd, hashed))
        self.assertFalse(verify_password("wrongPassword", hashed))


if __name__ == "__main__":
    unittest.main()

