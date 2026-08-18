from unittest.mock import MagicMock

from django.test import SimpleTestCase

from rosak.routers.timescale import TimescaleRouter


class TimescaleRouterTests(SimpleTestCase):
    def setUp(self):
        self.router = TimescaleRouter()

    def _make_mock_model(self, app_label: str):
        model = MagicMock()
        model._meta.app_label = app_label
        return model

    def _make_mock_instance(self, db: str):
        instance = MagicMock()
        instance._state.db = db
        return instance

    def test_allow_migrate_jejak_on_timescale_db(self):
        """jejak app migration should be allowed on timescale DB."""
        self.assertTrue(self.router.allow_migrate("timescale", "jejak"))

    def test_allow_migrate_jejak_blocked_on_default_db(self):
        """jejak app migration should be blocked on default DB."""
        self.assertFalse(self.router.allow_migrate("default", "jejak"))

    def test_allow_migrate_jejak_blocked_on_other_db(self):
        """jejak app migration should be blocked on any non-timescale DB."""
        self.assertFalse(self.router.allow_migrate("timescale_read", "jejak"))
        self.assertFalse(self.router.allow_migrate("analytics", "jejak"))

    def test_allow_migrate_non_jejak_defers_on_default_db(self):
        """Non-jejak apps (e.g. common, operation) should return None to defer."""
        self.assertIsNone(self.router.allow_migrate("default", "common"))
        self.assertIsNone(self.router.allow_migrate("default", "operation"))
        self.assertIsNone(self.router.allow_migrate("default", "incident"))
        self.assertIsNone(self.router.allow_migrate("default", "spotting"))
        self.assertIsNone(self.router.allow_migrate("default", "auth"))

    def test_allow_migrate_non_jejak_defers_on_timescale_db(self):
        """Non-jejak apps on timescale DB should return None (defer to next router)."""
        self.assertIsNone(self.router.allow_migrate("timescale", "common"))
        self.assertIsNone(self.router.allow_migrate("timescale", "operation"))
        self.assertIsNone(self.router.allow_migrate("timescale", "generic"))

    def test_db_for_read_routes_jejak_to_timescale_read(self):
        """jejak models should read from timescale_read."""
        model = self._make_mock_model("jejak")
        self.assertEqual(self.router.db_for_read(model), "timescale_read")

    def test_db_for_write_routes_jejak_to_timescale(self):
        """jejak models should write to timescale."""
        model = self._make_mock_model("jejak")
        self.assertEqual(self.router.db_for_write(model), "timescale")

    def test_db_for_read_returns_none_for_non_jejak_apps(self):
        """Non-jejak models should return None for read routing."""
        for app in ["common", "operation", "incident", "spotting", "generic", "mlptf"]:
            model = self._make_mock_model(app)
            self.assertIsNone(self.router.db_for_read(model))

    def test_db_for_write_returns_none_for_non_jejak_apps(self):
        """Non-jejak models should return None for write routing."""
        for app in ["common", "operation", "incident", "spotting", "generic", "mlptf"]:
            model = self._make_mock_model(app)
            self.assertIsNone(self.router.db_for_write(model))

    def test_allow_relation_allows_timescale_models(self):
        """Relations between objects in timescale and timescale_read should be allowed."""
        obj1 = self._make_mock_instance("timescale")
        obj2 = self._make_mock_instance("timescale_read")
        self.assertTrue(self.router.allow_relation(obj1, obj2))

        obj3 = self._make_mock_instance("timescale")
        obj4 = self._make_mock_instance("timescale")
        self.assertTrue(self.router.allow_relation(obj3, obj4))

    def test_allow_relation_returns_none_for_other_dbs(self):
        """Relations involving other DBs should return None."""
        obj1 = self._make_mock_instance("default")
        obj2 = self._make_mock_instance("timescale")
        self.assertIsNone(self.router.allow_relation(obj1, obj2))

        obj3 = self._make_mock_instance("default")
        obj4 = self._make_mock_instance("default")
        self.assertIsNone(self.router.allow_relation(obj3, obj4))
