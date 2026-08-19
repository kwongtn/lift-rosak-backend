import json
import os
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, modify_settings

from rosak.custom_view import git_version


@modify_settings(
    MIDDLEWARE={
        "remove": ["strawberry_django.middlewares.debug_toolbar.DebugToolbarMiddleware"]
    }
)
class GitVersionViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_git_version_with_env_vars_set(self):
        with mock.patch.dict(
            os.environ,
            {
                "GIT_COMMIT_HASH": "a1b2c3d4",
                "GIT_COMMIT_TIME": "Wed, 19 Aug 2026 01:11:12 +0800",
            },
        ):
            request = self.factory.get("/version/")
            response = git_version(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/json")
            data = json.loads(response.content)
            self.assertEqual(data["hash"], "a1b2c3d4")
            self.assertEqual(data["datetime"], "Wed, 19 Aug 2026 01:11:12 +0800")

    def test_git_version_with_empty_env_vars_returns_fallback(self):
        with mock.patch.dict(
            os.environ,
            {
                "GIT_COMMIT_HASH": "",
                "GIT_COMMIT_TIME": "",
            },
        ):
            request = self.factory.get("/version/")
            response = git_version(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/json")
            data = json.loads(response.content)
            self.assertEqual(data["hash"], "<<No hash data>>")
            self.assertEqual(data["datetime"], "")

    def test_git_version_with_missing_env_vars_returns_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            request = self.factory.get("/version/")
            response = git_version(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/json")
            data = json.loads(response.content)
            self.assertEqual(data["hash"], "<<No hash data>>")
            self.assertEqual(data["datetime"], "")

    def test_git_version_integration_url(self):
        with mock.patch.dict(
            os.environ,
            {
                "GIT_COMMIT_HASH": "12345678",
                "GIT_COMMIT_TIME": "Wed, 19 Aug 2026 00:00:00 +0000",
            },
        ):
            response = self.client.get("/version/")
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(data["hash"], "12345678")
            self.assertEqual(data["datetime"], "Wed, 19 Aug 2026 00:00:00 +0000")
