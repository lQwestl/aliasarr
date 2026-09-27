"""Путь тайтла нельзя вывести за пределы медиатеки обычным редактированием.

Смена папки через /change-folder проверяла путь, а PUT /shows/{id} записывал
любую строку. По этому пути затем работают удаление файлов и рекурсивная
установка прав 0777/0666.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.shows import update_show
from app.api.system_routes import fix_all_media_permissions
from app.models.db import AppSettings, Base, Show, User
from app.schemas import ShowUpdate


class TestShowPathGuard(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.library = os.path.join(self.root, "library")
        self.outside = os.path.join(self.root, "config")
        os.makedirs(os.path.join(self.library, "Dexter"))
        os.makedirs(self.outside)
        self.db.add(AppSettings(id=1, api_key="k", root_folder=self.library, root_folder_series=self.library))
        self.user = User(username="admin", password_hash="h", is_admin=True, is_owner=True)
        self.show = Show(title="Dexter", content_type="series", path=os.path.join(self.library, "Dexter"))
        self.db.add_all([self.user, self.show])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _update(self, **fields):
        return asyncio.run(update_show(self.show.id, ShowUpdate(**fields), db=self.db, current_user=self.user))

    def test_path_outside_library_is_rejected(self):
        for bad in ("/", self.outside, os.path.join(self.library, "..", "config"), "relative/path"):
            with self.subTest(path=bad):
                with self.assertRaises(HTTPException) as ctx:
                    self._update(path=bad)
                self.assertEqual(ctx.exception.status_code, 400)
        self.db.refresh(self.show)
        self.assertEqual(self.show.path, os.path.join(self.library, "Dexter"))

    def test_path_inside_library_is_accepted(self):
        new_path = os.path.join(self.library, "Dexter (2006)")
        self._update(path=new_path)
        self.db.refresh(self.show)
        self.assertEqual(self.show.path, new_path)

    def test_unchanged_legacy_path_does_not_block_other_edits(self):
        legacy = os.path.join(self.outside, "Old Root", "Dexter")
        self.show.path = legacy
        self.db.commit()
        self._update(path=legacy, title="Dexter: New Blood")
        self.db.refresh(self.show)
        self.assertEqual(self.show.title, "Dexter: New Blood")

    def test_bulk_permission_fix_skips_paths_outside_library(self):
        self.show.path = self.outside
        self.db.commit()
        res = fix_all_media_permissions(db=self.db, current_user=self.user)
        self.assertEqual(res["skipped_paths"], [self.outside])


if __name__ == "__main__":
    unittest.main()
