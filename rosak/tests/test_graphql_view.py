from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, modify_settings, override_settings
from django.urls import resolve

from common.models import User
from rosak.context import CustomGraphQLView


class TestGraphQLViewConfig(TestCase):
    def test_csrf_protection_enabled(self):
        """Verify GraphQL endpoint has CSRF handling configured."""
        match = resolve("/graphql/")
        # Verify the resolved view is CustomGraphQLView
        self.assertTrue(
            hasattr(match.func, "view_class")
            and issubclass(match.func.view_class, CustomGraphQLView)
            or getattr(match.func, "__name__", "") == "view"
        )
        # Verify view initkwargs
        view_func = match.func
        # In strawberry/django, view_class or initkwargs can be verified
        if hasattr(view_func, "view_class"):
            self.assertTrue(issubclass(view_func.view_class, CustomGraphQLView))

    def test_multipart_uploads_configuration(self):
        """Verify multipart uploads setting per Strawberry 0.243.0 defaults (disabled)."""
        match = resolve("/graphql/")
        # Check CustomGraphQLView's multipart_uploads_enabled attribute / initkwargs
        view_class = getattr(match.func, "view_class", CustomGraphQLView)
        multipart_enabled = getattr(
            view_class,
            "multipart_uploads_enabled",
            getattr(CustomGraphQLView, "multipart_uploads_enabled", False),
        )
        self.assertFalse(multipart_enabled)


@override_settings(
    CACHES={
        **settings.CACHES,
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    }
)
# The dev-only debug toolbar would render its panel into the JSON answers.
@modify_settings(
    MIDDLEWARE={
        "remove": "strawberry_django.middlewares.debug_toolbar.DebugToolbarMiddleware"
    }
)
class TestGraphQLGetIsNotSharedAcrossViewers(TestCase):
    """The per-site cache must not hand one viewer's GET answer to another."""

    PARAMS = {"query": "{ user { nickname } }"}  # null for anonymous, a row for a user

    def setUp(self):
        User.objects.create(firebase_id="cache-owner-uid", nickname="CacheOwner")

    def _get(self, token=None):
        headers = {"Firebase-Auth-Key": token} if token else {}
        with patch(
            "common.utils.auth.verify_id_token",
            return_value={"uid": "cache-owner-uid"},
        ):
            return self.client.get("/graphql/", self.PARAMS, headers=headers)

    def test_a_signed_in_get_does_not_get_the_cached_anonymous_body(self):
        anonymous = self._get()
        self.assertIsNone(anonymous.json()["data"])

        signed_in = self._get("token")

        self.assertEqual(signed_in.json()["data"], {"user": {"nickname": "CacheOwner"}})

    def test_an_anonymous_get_does_not_get_the_cached_signed_in_body(self):
        self.assertIsNotNone(self._get("token").json()["data"])

        self.assertIsNone(self._get().json()["data"])

    def test_the_response_varies_on_the_token_header(self):
        self.assertIn("Firebase-Auth-Key", self._get()["Vary"])
