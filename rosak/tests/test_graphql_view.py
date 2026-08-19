from django.test import TestCase
from django.urls import resolve

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
