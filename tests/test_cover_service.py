from __future__ import annotations

import asyncio
import base64
import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cover_service import (
    get_media_cover_dir,
    get_show_poster_dir,
    get_show_poster_path,
    get_collection_poster_dir,
    get_collection_poster_path,
    get_collection_backdrop_path,
    optimize_image,
    NotAnImageError,
    fetch_remote_image,
    save_show_poster,
    save_collection_poster,
    save_collection_backdrop,
    delete_show_cover,
    delete_collection_cover,
    get_cover_etag,
    download_and_store_show_cover,
    download_and_store_collection_cover,
    download_and_store_collection_backdrop,
    backfill_existing_covers,
    attach_version_to_cover_url,
)

from PIL import Image


def _image_bytes(color=(200, 30, 30), size=(8, 12), fmt="PNG") -> bytes:
    """Настоящее изображение: обложки, которые не разбираются как картинка, не сохраняются."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def _is_jpeg(path: str) -> bool:
    with Image.open(path) as img:
        return img.format == "JPEG"


try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi import HTTPException
    from fastapi.responses import Response
    from app.models.db import Base, Show, MovieCollection, User
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestCoverServiceFilesystem(unittest.TestCase):
    """Тестирование файловых операций, путей, ETag и конвертации без обязательных внешних библиотек."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_env = os.environ.get("MEDIA_COVER_DIR")
        os.environ["MEDIA_COVER_DIR"] = self.temp_dir

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["MEDIA_COVER_DIR"] = self.orig_env
        else:
            os.environ.pop("MEDIA_COVER_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_paths_resolution(self):
        self.assertEqual(get_media_cover_dir(), self.temp_dir)
        show_dir = get_show_poster_dir(42)
        self.assertEqual(show_dir, os.path.join(self.temp_dir, "shows", "42"))
        show_path = get_show_poster_path(42)
        self.assertEqual(show_path, os.path.join(self.temp_dir, "shows", "42", "poster.jpg"))

        coll_dir = get_collection_poster_dir(99)
        self.assertEqual(coll_dir, os.path.join(self.temp_dir, "collections", "99"))
        coll_path = get_collection_poster_path(99)
        self.assertEqual(coll_path, os.path.join(self.temp_dir, "collections", "99", "poster.jpg"))

    def test_optimize_image_rejects_non_images(self):
        # Раньше байты, не являющиеся картинкой, сохранялись как есть — так ответ
        # внутреннего сервиса становился доступен через эндпоинт постера.
        with self.assertRaises(NotAnImageError):
            optimize_image(b"<html>router admin page</html>")

    def test_optimize_image_converts_to_jpeg(self):
        out = optimize_image(_image_bytes(fmt="PNG"))
        with Image.open(io.BytesIO(out)) as img:
            self.assertEqual(img.format, "JPEG")

    def test_save_and_etag_show_poster(self):
        sample_bytes = _image_bytes()
        url = asyncio.run(save_show_poster(10, sample_bytes))
        self.assertTrue(url.startswith("/api/v1/shows/10/poster?v="))

        target_file = get_show_poster_path(10)
        self.assertTrue(os.path.isfile(target_file))
        self.assertTrue(_is_jpeg(target_file))

        etag = get_cover_etag(target_file)
        self.assertIsNotNone(etag)
        self.assertTrue(etag.startswith('"') and etag.endswith('"'))

        # Non-existent file etag
        self.assertIsNone(get_cover_etag(os.path.join(self.temp_dir, "non_existent.jpg")))

    def test_save_and_delete_collection_poster(self):
        sample_bytes = _image_bytes()
        url = asyncio.run(save_collection_poster(20, sample_bytes))
        self.assertTrue(url.startswith("/api/v1/collections/20/poster?v="))

        target_file = get_collection_poster_path(20)
        self.assertTrue(os.path.isfile(target_file))

        # Delete collection cover
        deleted = delete_collection_cover(20)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(get_collection_poster_dir(20)))

        # Deleting again returns False
        self.assertFalse(delete_collection_cover(20))

    def test_delete_show_cover(self):
        asyncio.run(save_show_poster(77, _image_bytes()))
        self.assertTrue(os.path.exists(get_show_poster_dir(77)))

        self.assertTrue(delete_show_cover(77))
        self.assertFalse(os.path.exists(get_show_poster_dir(77)))
        self.assertFalse(delete_show_cover(77))

    def test_download_and_store_show_cover_base64(self):
        raw = _image_bytes()
        b64_str = f"data:image/jpeg;base64,{base64.b64encode(raw).decode('ascii')}"

        res = asyncio.run(download_and_store_show_cover(55, b64_str))
        self.assertTrue(res.startswith("/api/v1/shows/55/poster?v="))
        self.assertTrue(os.path.isfile(get_show_poster_path(55)))
        self.assertTrue(_is_jpeg(get_show_poster_path(55)))

    def test_download_and_store_show_cover_http(self):
        with patch("app.services.cover_service.fetch_remote_image", AsyncMock(return_value=_image_bytes())):
            res = asyncio.run(download_and_store_show_cover(88, "https://cdn.example.com/poster.jpg"))
            self.assertTrue(res.startswith("/api/v1/shows/88/poster?v="))
            self.assertTrue(os.path.isfile(get_show_poster_path(88)))

    def test_download_and_store_collection_cover_http(self):
        with patch("app.services.cover_service.fetch_remote_image", AsyncMock(return_value=_image_bytes())):
            res = asyncio.run(download_and_store_collection_cover(99, "https://image.tmdb.org/t/p/original/coll.jpg"))
            self.assertTrue(res.startswith("/api/v1/collections/99/poster?v="))
            self.assertTrue(os.path.isfile(get_collection_poster_path(99)))

    def test_save_and_download_collection_backdrop(self):
        backdrop_bytes = _image_bytes()
        url = asyncio.run(save_collection_backdrop(30, backdrop_bytes))
        self.assertTrue(url.startswith("/api/v1/collections/30/backdrop?v="))
        target_file = get_collection_backdrop_path(30)
        self.assertTrue(os.path.isfile(target_file))

        # Test download
        with patch("app.services.cover_service.fetch_remote_image", AsyncMock(return_value=_image_bytes())):
            res = asyncio.run(download_and_store_collection_backdrop(31, "https://image.tmdb.org/t/p/original/bd.jpg"))
            self.assertTrue(res.startswith("/api/v1/collections/31/backdrop?v="))
            self.assertTrue(os.path.isfile(get_collection_backdrop_path(31)))

    def test_attach_version_to_cover_url(self):
        import datetime as dt
        # 1. External URL unchanged
        self.assertEqual(attach_version_to_cover_url("https://image.tmdb.org/p.jpg"), "https://image.tmdb.org/p.jpg")

        # 2. URL with existing query param unchanged
        self.assertEqual(attach_version_to_cover_url("/api/v1/shows/5/poster?v=999"), "/api/v1/shows/5/poster?v=999")

        # 3. Local URL with timestamp object
        t = dt.datetime(2026, 9, 15, 12, 0, 0)
        expected_ts = int(t.timestamp())
        self.assertEqual(attach_version_to_cover_url("/api/v1/shows/5/poster", t), f"/api/v1/shows/5/poster?v={expected_ts}")
        self.assertEqual(attach_version_to_cover_url("/api/v1/collections/3/backdrop", t), f"/api/v1/collections/3/backdrop?v={expected_ts}")


@unittest.skipUnless(HAS_DEPS, "Requires sqlalchemy, fastapi, and pydantic")
class TestCoverServiceEndpointsAndDb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_env = os.environ.get("MEDIA_COVER_DIR")
        os.environ["MEDIA_COVER_DIR"] = self.temp_dir

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.user = User(
            id=1,
            username="admin",
            is_admin=True,
            is_owner=True,
            enabled=True,
            password_hash="hash",
        )
        self.db.add(self.user)
        self.db.commit()

        self.patch_session = patch("app.database.SessionLocal", self.Session)
        self.patch_session.start()

    def tearDown(self):
        self.patch_session.stop()
        self.db.close()
        if self.orig_env is not None:
            os.environ["MEDIA_COVER_DIR"] = self.orig_env
        else:
            os.environ.pop("MEDIA_COVER_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_backfill_existing_covers(self):
        s1 = Show(
            title="Show CDN",
            poster_url="https://image.tmdb.org/t/p/original/show1.jpg",
        )
        raw_b64 = base64.b64encode(_image_bytes()).decode("ascii")
        s2 = Show(
            title="Show Base64",
            poster_url=f"data:image/jpeg;base64,{raw_b64}",
        )
        s3 = Show(
            title="Show No Poster",
            poster_url=None,
        )
        self.db.add_all([s1, s2, s3])
        self.db.commit()

        with patch("app.services.cover_service.fetch_remote_image", AsyncMock(return_value=_image_bytes())):
            res = asyncio.run(backfill_existing_covers(self.db))
            self.assertEqual(res["total"], 3)
            self.assertEqual(res["migrated"], 2)

            self.db.refresh(s1)
            self.db.refresh(s2)
            self.assertTrue(s1.poster_url.startswith(f"/api/v1/shows/{s1.id}/poster?v="))
            self.assertEqual(s1.poster_source_url, "https://image.tmdb.org/t/p/original/show1.jpg")
            self.assertTrue(os.path.isfile(get_show_poster_path(s1.id)))

            self.assertTrue(s2.poster_url.startswith(f"/api/v1/shows/{s2.id}/poster?v="))
            self.assertTrue(os.path.isfile(get_show_poster_path(s2.id)))

    def test_get_show_poster_endpoint_and_caching(self):
        from app.api.shows import get_show_poster

        s = Show(title="Test Endpoint Show", poster_url=None)
        self.db.add(s)
        self.db.commit()

        req_mock = MagicMock()
        req_mock.headers = {}

        # 1. 404 when file and source url not present
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_show_poster(s.id, req_mock))
        self.assertEqual(ctx.exception.status_code, 404)

        # 2. Save file and get 200 FileResponse with ETag
        sample_img = _image_bytes()
        asyncio.run(save_show_poster(s.id, sample_img))

        resp = asyncio.run(get_show_poster(s.id, req_mock))
        self.assertEqual(resp.media_type, "image/jpeg")
        self.assertEqual(resp.headers.get("Cache-Control"), "no-cache, must-revalidate")
        self.assertNotIn("immutable", resp.headers.get("Cache-Control", ""))
        etag = resp.headers.get("ETag")
        self.assertIsNotNone(etag)

        # 3. 304 Not Modified when If-None-Match matches ETag
        req_mock_cached = MagicMock()
        req_mock_cached.headers = {"if-none-match": etag}
        resp304 = asyncio.run(get_show_poster(s.id, req_mock_cached))
        self.assertEqual(resp304.status_code, 304)
        self.assertEqual(resp304.headers.get("Cache-Control"), "no-cache, must-revalidate")
        self.assertNotIn("immutable", resp304.headers.get("Cache-Control", ""))

    def test_upload_show_cover_endpoint(self):
        from app.api.shows import upload_show_cover
        from starlette.datastructures import UploadFile

        s = Show(title="Upload Show", poster_url=None)
        self.db.add(s)
        self.db.commit()

        file_bytes = _image_bytes()
        upload_obj = UploadFile(filename="poster.jpg", file=io.BytesIO(file_bytes))

        resp = asyncio.run(upload_show_cover(s.id, file=upload_obj, db=self.db, current_user=self.user))
        self.assertTrue(resp["success"])
        self.assertTrue(resp["poster_url"].startswith(f"/api/v1/shows/{s.id}/poster?v="))

        self.db.refresh(s)
        self.assertTrue(s.poster_url.startswith(f"/api/v1/shows/{s.id}/poster?v="))
        self.assertTrue(os.path.isfile(get_show_poster_path(s.id)))
        self.assertTrue(_is_jpeg(get_show_poster_path(s.id)))

    def test_get_collection_poster_endpoint(self):
        from app.api.collections_routes import get_collection_poster

        coll = MovieCollection(title="Test Coll", tmdb_collection_id=12345)
        self.db.add(coll)
        self.db.commit()

        req_mock = MagicMock()
        req_mock.headers = {}

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_collection_poster(coll.id, req_mock))
        self.assertEqual(ctx.exception.status_code, 404)

        asyncio.run(save_collection_poster(coll.id, _image_bytes()))
        resp = asyncio.run(get_collection_poster(coll.id, req_mock))
        self.assertEqual(resp.media_type, "image/jpeg")
        self.assertEqual(resp.headers.get("Cache-Control"), "no-cache, must-revalidate")
        self.assertNotIn("immutable", resp.headers.get("Cache-Control", ""))
        etag = resp.headers.get("ETag")
        self.assertIsNotNone(etag)

        req_cached = MagicMock()
        req_cached.headers = {"if-none-match": etag}
        resp304 = asyncio.run(get_collection_poster(coll.id, req_cached))
        self.assertEqual(resp304.status_code, 304)
        self.assertEqual(resp304.headers.get("Cache-Control"), "no-cache, must-revalidate")
        self.assertNotIn("immutable", resp304.headers.get("Cache-Control", ""))

    def test_get_collection_backdrop_endpoint(self):
        from app.api.collections_routes import get_collection_backdrop

        coll = MovieCollection(title="Test Coll BD", tmdb_collection_id=12346)
        self.db.add(coll)
        self.db.commit()

        req_mock = MagicMock()
        req_mock.headers = {}

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_collection_backdrop(coll.id, req_mock))
        self.assertEqual(ctx.exception.status_code, 404)

        asyncio.run(save_collection_backdrop(coll.id, _image_bytes()))
        resp = asyncio.run(get_collection_backdrop(coll.id, req_mock))
        self.assertEqual(resp.media_type, "image/jpeg")
        self.assertEqual(resp.headers.get("Cache-Control"), "no-cache, must-revalidate")
        self.assertNotIn("immutable", resp.headers.get("Cache-Control", ""))
        etag = resp.headers.get("ETag")
        self.assertIsNotNone(etag)

        req_cached = MagicMock()
        req_cached.headers = {"if-none-match": etag}
        resp304 = asyncio.run(get_collection_backdrop(coll.id, req_cached))
        self.assertEqual(resp304.status_code, 304)
        self.assertEqual(resp304.headers.get("Cache-Control"), "no-cache, must-revalidate")
        self.assertNotIn("immutable", resp304.headers.get("Cache-Control", ""))

    def test_delete_show_deletes_cover_folder(self):
        from app.schemas import DeleteContentPayload
        from app.api.shows import delete_content

        s = Show(title="Show To Delete", poster_url=None)
        self.db.add(s)
        self.db.commit()

        asyncio.run(save_show_poster(s.id, _image_bytes()))
        self.assertTrue(os.path.isfile(get_show_poster_path(s.id)))

        payload = DeleteContentPayload(delete_mode="show", delete_files=False)
        res = asyncio.run(delete_content(s.id, payload, db=self.db, current_user=self.user))
        self.assertTrue(res.success)
        self.assertFalse(os.path.exists(get_show_poster_dir(s.id)))

    def test_delete_collection_deletes_cover_folder(self):
        from app.api.collections_routes import delete_collection

        coll = MovieCollection(title="Coll To Delete", tmdb_collection_id=54321)
        self.db.add(coll)
        self.db.commit()

        asyncio.run(save_collection_poster(coll.id, _image_bytes()))
        asyncio.run(save_collection_backdrop(coll.id, _image_bytes()))
        self.assertTrue(os.path.isfile(get_collection_poster_path(coll.id)))
        self.assertTrue(os.path.isfile(get_collection_backdrop_path(coll.id)))

        res = delete_collection(coll.id, db=self.db, current_user=self.user)
        self.assertIsNone(res)
        self.assertFalse(os.path.exists(get_collection_poster_dir(coll.id)))


class TestCoverDownloadSsrf(unittest.TestCase):
    """Скачивание обложек не должно ходить во внутреннюю сеть."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.env = patch.dict(os.environ, {"MEDIA_COVER_DIR": self.temp_dir})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _fetch(self, url, handler, resolved=None):
        import httpx

        real_client = httpx.AsyncClient
        resolved = resolved or {}

        async def fake_resolve(host, port):
            return resolved.get(host, {host})

        def client_factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        with patch("app.services.cover_service._resolve_host", fake_resolve), \
             patch("httpx.AsyncClient", client_factory):
            return asyncio.run(fetch_remote_image(url))

    def test_private_and_metadata_addresses_are_refused(self):
        def handler(request):
            raise AssertionError(f"no request expected, got {request.url}")

        for url in (
            "http://127.0.0.1/admin",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://10.0.0.5:8080/api/v2/torrents/info",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self._fetch(url, handler)

    def test_host_resolving_to_lan_is_refused(self):
        def handler(request):
            raise AssertionError("no request expected")

        with self.assertRaises(ValueError):
            self._fetch("https://poster.attacker.example/x.jpg", handler,
                        resolved={"poster.attacker.example": {"192.168.1.10"}})

    def test_redirect_into_private_network_is_refused(self):
        import httpx

        def handler(request):
            if request.url.host == "cdn.example.org":
                return httpx.Response(302, headers={"location": "http://127.0.0.1:9091/transmission/rpc"})
            raise AssertionError("redirect target must not be requested")

        with self.assertRaises(ValueError):
            self._fetch("https://cdn.example.org/p.jpg", handler,
                        resolved={"cdn.example.org": {"93.184.216.34"}})

    def test_public_image_is_downloaded(self):
        import httpx

        payload = _image_bytes()

        def handler(request):
            return httpx.Response(200, content=payload, headers={"content-type": "image/png"})

        data = self._fetch("https://image.tmdb.org/t/p/original/a.png", handler,
                           resolved={"image.tmdb.org": {"93.184.216.34"}})
        self.assertEqual(data, payload)

    def test_non_image_response_is_not_stored(self):
        with patch("app.services.cover_service.fetch_remote_image",
                   AsyncMock(return_value=b"<html>internal service</html>")):
            res = asyncio.run(download_and_store_show_cover(501, "https://cdn.example.org/p.jpg"))
        self.assertIsNone(res)
        self.assertFalse(os.path.exists(get_show_poster_path(501)))
