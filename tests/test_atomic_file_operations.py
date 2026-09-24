from __future__ import annotations

import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.file_preflight import (
    OperationMode,
    atomic_transfer,
    quarantine_path,
    restore_quarantined,
)
from app.services.path_security import UnsafeMediaPathError


class TestAtomicTransfer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.src = self.base / "source.mkv"
        self.dst = self.base / "library" / "episode.mkv"
        self.dst.parent.mkdir()
        self.src.write_bytes(b"new-video-data")

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_publishes_complete_file_and_keeps_source(self):
        progress = []
        result = atomic_transfer(self.src, self.dst, callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(result, "copy")
        self.assertEqual(self.dst.read_bytes(), b"new-video-data")
        self.assertTrue(self.src.exists())
        self.assertEqual(progress[-1], (len(b"new-video-data"), len(b"new-video-data")))
        self.assertEqual(list(self.dst.parent.glob("*.aliasarr-part-*")), [])

    def test_failed_copy_preserves_existing_destination_and_source(self):
        self.dst.write_bytes(b"old-video")
        real_replace = os.replace

        def fail_publish(source, destination):
            if ".aliasarr-part-" in os.fspath(source) and Path(destination) == self.dst.resolve():
                raise OSError(errno.EIO, "publish failed")
            return real_replace(source, destination)

        with (
            patch("app.services.file_preflight.os.replace", side_effect=fail_publish),
            self.assertRaises(OSError),
        ):
            atomic_transfer(self.src, self.dst, replace=True)

        self.assertEqual(self.dst.read_bytes(), b"old-video")
        self.assertEqual(self.src.read_bytes(), b"new-video-data")
        self.assertEqual(list(self.dst.parent.glob(".*.aliasarr-part-*")), [])
        self.assertEqual(list(self.dst.parent.glob(".*.aliasarr-backup-*")), [])

    def test_same_device_move_removes_source_after_publish(self):
        result = atomic_transfer(self.src, self.dst, mode=OperationMode.MOVE)
        self.assertEqual(result, "move")
        self.assertFalse(self.src.exists())
        self.assertEqual(self.dst.read_bytes(), b"new-video-data")

    def test_bind_mount_move_falls_back_when_rename_raises_exdev(self):
        """Bind mounts may reject rename even when source and target report the same st_dev."""
        real_replace = os.replace

        def reject_cross_mount_rename(source, destination):
            if Path(source) == self.src.resolve() and ".aliasarr-part-" in os.fspath(destination):
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(source, destination)

        with patch("app.services.file_preflight.os.replace", side_effect=reject_cross_mount_rename):
            result = atomic_transfer(self.src, self.dst, mode=OperationMode.MOVE)

        self.assertEqual(result, "move")
        self.assertFalse(self.src.exists())
        self.assertEqual(self.dst.read_bytes(), b"new-video-data")
        self.assertEqual(list(self.dst.parent.glob(".*.aliasarr-part-*")), [])

    def test_bind_mount_move_failed_publish_keeps_source_and_old_destination(self):
        self.dst.write_bytes(b"old-video")
        real_replace = os.replace

        def fail_after_cross_mount_rename(source, destination):
            source_path = Path(source)
            if source_path == self.src.resolve() and ".aliasarr-part-" in os.fspath(destination):
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            if ".aliasarr-part-" in os.fspath(source) and Path(destination) == self.dst.resolve():
                raise OSError(errno.EIO, "publish failed")
            return real_replace(source, destination)

        with (
            patch("app.services.file_preflight.os.replace", side_effect=fail_after_cross_mount_rename),
            self.assertRaises(OSError),
        ):
            atomic_transfer(self.src, self.dst, mode=OperationMode.MOVE)

        self.assertEqual(self.src.read_bytes(), b"new-video-data")
        self.assertEqual(self.dst.read_bytes(), b"old-video")
        self.assertEqual(list(self.dst.parent.glob(".*.aliasarr-part-*")), [])
        self.assertEqual(list(self.dst.parent.glob(".*.aliasarr-backup-*")), [])

    def test_hardlink_shares_inode(self):
        result = atomic_transfer(self.src, self.dst, mode=OperationMode.HARDLINK)
        self.assertEqual(result, "hardlink")
        self.assertEqual(self.src.stat().st_ino, self.dst.stat().st_ino)

    def test_replace_false_never_clobbers_destination(self):
        self.dst.write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            atomic_transfer(self.src, self.dst, replace=False)
        self.assertEqual(self.dst.read_bytes(), b"old")
        self.assertTrue(self.src.exists())

    def test_existing_destination_can_be_kept_in_quarantine(self):
        self.dst.write_bytes(b"old")
        recycle = self.base / ".aliasarr-recycle"
        atomic_transfer(self.src, self.dst, quarantine_root=recycle)
        self.assertEqual(self.dst.read_bytes(), b"new-video-data")
        quarantined = list(recycle.glob("*/episode.mkv"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), b"old")


class TestQuarantine(unittest.TestCase):
    def test_quarantine_and_restore_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "library" / "Show" / "episode.mkv"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"video")
            recycle = base / "library" / ".aliasarr-recycle"

            record = quarantine_path(original, recycle, operation="episode_delete")
            self.assertFalse(original.exists())
            self.assertTrue(record.quarantined_path.exists())
            self.assertEqual(record.size_bytes, 5)

            restored = restore_quarantined(record)
            self.assertEqual(restored, original.resolve())
            self.assertEqual(original.read_bytes(), b"video")

    def test_quarantine_directory_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            show = base / "Show"
            show.mkdir()
            (show / "episode.mkv").write_bytes(b"video")
            record = quarantine_path(show, base / ".aliasarr-recycle", operation="show_delete")
            self.assertFalse(show.exists())
            restore_quarantined(record)
            self.assertEqual((show / "episode.mkv").read_bytes(), b"video")

    def test_quarantine_cannot_be_inside_deleted_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            show = Path(tmp, "Show")
            show.mkdir()
            with self.assertRaises(UnsafeMediaPathError):
                quarantine_path(show, show / ".aliasarr-recycle")

    def test_restore_refuses_to_overwrite_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "episode.mkv"
            original.write_bytes(b"old")
            record = quarantine_path(original, base / ".recycle")
            original.write_bytes(b"other")
            with self.assertRaises(FileExistsError):
                restore_quarantined(record)
            self.assertEqual(original.read_bytes(), b"other")
            self.assertTrue(record.quarantined_path.exists())


if __name__ == "__main__":
    unittest.main()
