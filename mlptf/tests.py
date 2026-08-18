from django.test import TestCase
from django.utils import timezone

from common.models import User
from mlptf.models import Badge, UserBadge


class MLPTFModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="badge-user-1")
        self.badge = Badge.objects.create(
            name="Early Spotter",
            description="First 100 spotters",
            released=timezone.now(),
            sprite_url="https://example.com/badge.png",
        )

    def test_award_badge_to_user(self):
        user_badge = UserBadge.objects.create(
            user=self.user,
            badge=self.badge,
        )
        self.assertEqual(user_badge.user, self.user)
        self.assertEqual(user_badge.badge, self.badge)
        self.assertIn(self.badge, self.user.badges.all())
