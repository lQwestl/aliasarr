import unittest
from unittest.mock import MagicMock

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base, AppSettings, User, UserRole, QualityProfile, Show, ContentType
    from app.services.settings_service import get_or_create_settings
    from app.api.settings_routes import update_settings, SettingsUpdate, get_settings
    from app.api.shows import create_show
    from app.schemas import ShowCreate
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestDefaultQualityProfiles(unittest.TestCase):
    def setUp(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            id=1,
            username="admin",
            role=UserRole.ADMIN,
            is_active=True,
            password_hash="hash",
            is_owner=True,
        )
        self.db.add(self.user)

        # Create sample quality profiles
        self.qp_movie = QualityProfile(id=1, name="Movie UltraHD", allowed_qualities=["2160p", "1080p"])
        self.qp_series = QualityProfile(id=2, name="Series 1080p", allowed_qualities=["1080p"])
        self.qp_anime = QualityProfile(id=3, name="Anime Subs 1080p", allowed_qualities=["1080p", "720p"])
        self.db.add_all([self.qp_movie, self.qp_series, self.qp_anime])
        self.db.commit()

    def tearDown(self):
        if hasattr(self, "db"):
            self.db.close()

    def test_default_quality_profile_update_and_get(self):
        get_or_create_settings(self.db)
        mock_request = MagicMock()

        payload = SettingsUpdate(
            default_quality_profile_movie_id=1,
            default_quality_profile_series_id=2,
            default_quality_profile_anime_id=3,
        )
        res = update_settings(payload=payload, request=mock_request, db=self.db, current_user=self.user)
        self.assertEqual(res.default_quality_profile_movie_id, 1)
        self.assertEqual(res.default_quality_profile_series_id, 2)
        self.assertEqual(res.default_quality_profile_anime_id, 3)

        out = get_settings(db=self.db, current_user=self.user)
        self.assertEqual(out.default_quality_profile_movie_id, 1)
        self.assertEqual(out.default_quality_profile_series_id, 2)
        self.assertEqual(out.default_quality_profile_anime_id, 3)

    def test_show_creation_auto_assigns_default_quality_profile(self):
        settings = get_or_create_settings(self.db)
        settings.default_quality_profile_movie_id = 1
        settings.default_quality_profile_series_id = 2
        settings.default_quality_profile_anime_id = 3
        self.db.add(settings)
        self.db.commit()

        # 1. Create Movie without explicit quality_profile_id -> should get qp 1
        movie_payload = ShowCreate(
            title="Inception",
            year=2010,
            content_type=ContentType.MOVIE,
            quality_profile_id=None,
        )
        movie_show = create_show(payload=movie_payload, db=self.db, current_user=self.user)
        self.assertEqual(movie_show.quality_profile_id, 1)

        # 2. Create Series without explicit quality_profile_id -> should get qp 2
        series_payload = ShowCreate(
            title="Breaking Bad",
            year=2008,
            content_type=ContentType.SERIES,
            quality_profile_id=None,
        )
        series_show = create_show(payload=series_payload, db=self.db, current_user=self.user)
        self.assertEqual(series_show.quality_profile_id, 2)

        # 3. Create Anime without explicit quality_profile_id -> should get qp 3
        anime_payload = ShowCreate(
            title="Attack on Titan",
            year=2013,
            content_type=ContentType.ANIME,
            quality_profile_id=None,
        )
        anime_show = create_show(payload=anime_payload, db=self.db, current_user=self.user)
        self.assertEqual(anime_show.quality_profile_id, 3)

        # 4. Create with explicit quality_profile_id -> should preserve explicit ID
        custom_payload = ShowCreate(
            title="Special Movie",
            year=2024,
            content_type=ContentType.MOVIE,
            quality_profile_id=2,
        )
        custom_show = create_show(payload=custom_payload, db=self.db, current_user=self.user)
        self.assertEqual(custom_show.quality_profile_id, 2)
