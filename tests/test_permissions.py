from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from app.services.postprocess import apply_media_permissions


class TestPermissions(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="aliasarr_perm_test_")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_apply_media_permissions_file_and_dir(self):
        sub_dir = os.path.join(self.test_dir, "Season 01")
        os.makedirs(sub_dir, exist_ok=True)
        file_path = os.path.join(sub_dir, "test.mkv")
        with open(file_path, "wb") as f:
            f.write(b"dummy video data")

        os.chmod(file_path, 0o600)
        os.chmod(sub_dir, 0o700)

        stats = apply_media_permissions(self.test_dir, is_dir=True, recursive=True)

        self.assertGreaterEqual(stats["dirs"], 1)
        self.assertGreaterEqual(stats["files"], 1)

        dir_stat = os.stat(sub_dir)
        file_stat = os.stat(file_path)

        self.assertTrue(bool(dir_stat.st_mode & 0o005), "Directory must have execute/read bit for all users")
        self.assertTrue(bool(file_stat.st_mode & 0o004), "File must have read bit for all users")


if __name__ == "__main__":
    unittest.main()
