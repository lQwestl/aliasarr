from __future__ import annotations

import json
import tempfile
import unittest

from sqlalchemy import create_engine, text

import app.database as database


class DatabaseMigrationTests(unittest.TestCase):
    def test_existing_tracked_release_gets_nullable_favorite_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{temp_dir}/tracked.sqlite")
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE tracked_releases (id INTEGER PRIMARY KEY, show_id INTEGER NOT NULL)"))
                conn.execute(text("INSERT INTO tracked_releases (id, show_id) VALUES (1, 5)"))

            original_engine = database.engine
            database.engine = engine
            try:
                database._migrate_add_missing_columns()
                database._ensure_performance_indexes()
            finally:
                database.engine = original_engine

            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT favorite_season, favorite_title, favorite_query, last_seen_fingerprint, last_check_status "
                    "FROM tracked_releases WHERE id = 1"
                )).one()
                indexes = conn.execute(text("PRAGMA index_list(tracked_releases)")).all()
            engine.dispose()

        self.assertEqual(tuple(row), (None, None, None, None, None))
        self.assertIn("ux_tracked_favorite_show_season", {item[1] for item in indexes})

    def test_existing_download_client_gets_empty_remote_path_mapping_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{temp_dir}/migration.sqlite")
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE download_clients (id INTEGER PRIMARY KEY)"))
                conn.execute(text("INSERT INTO download_clients (id) VALUES (1)"))

            original_engine = database.engine
            database.engine = engine
            try:
                database._migrate_add_missing_columns()
            finally:
                database.engine = original_engine

            with engine.connect() as conn:
                raw = conn.execute(
                    text("SELECT remote_path_mappings FROM download_clients WHERE id = 1")
                ).scalar_one()
            engine.dispose()

        self.assertEqual(json.loads(raw), [])


if __name__ == "__main__":
    unittest.main()
