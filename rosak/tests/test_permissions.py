import asyncio
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError

from rosak.permissions import has_admin_claim


class HasAdminClaimTests(SimpleTestCase):
    def _run(self, user, side_effect=None, return_value=None):
        with mock.patch("rosak.permissions.auth.get_user") as get_user:
            get_user.side_effect = side_effect
            get_user.return_value = return_value
            result = asyncio.run(has_admin_claim(user))
        return result, get_user

    def test_none_user_returns_false_without_lookup(self):
        result, get_user = self._run(None)
        self.assertFalse(result)
        get_user.assert_not_called()

    def test_admin_claim_true(self):
        user = SimpleNamespace(firebase_id="uid-1")
        firebase_user = SimpleNamespace(custom_claims={"admin": True})
        result, _ = self._run(user, return_value=firebase_user)
        self.assertTrue(result)

    def test_empty_claims_returns_false(self):
        user = SimpleNamespace(firebase_id="uid-2")
        firebase_user = SimpleNamespace(custom_claims={})
        result, _ = self._run(user, return_value=firebase_user)
        self.assertFalse(result)

    def test_none_claims_returns_false(self):
        user = SimpleNamespace(firebase_id="uid-3")
        firebase_user = SimpleNamespace(custom_claims=None)
        result, _ = self._run(user, return_value=firebase_user)
        self.assertFalse(result)

    def test_user_not_found_returns_false(self):
        user = SimpleNamespace(firebase_id="uid-4")
        result, _ = self._run(user, side_effect=auth.UserNotFoundError("gone"))
        self.assertFalse(result)

    def test_firebase_error_propagates(self):
        user = SimpleNamespace(firebase_id="uid-5")
        with self.assertRaises(FirebaseError):
            self._run(user, side_effect=FirebaseError("INTERNAL", "boom"))
