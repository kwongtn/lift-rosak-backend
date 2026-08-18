from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.utils.timezone import now

from common.enums import (
    ClearanceType,
    FeatureFlagType,
    TemporaryMediaStatus,
    TemporaryMediaType,
)
from common.models import (
    Clearance,
    FeatureFlag,
    TemporaryMedia,
    User,
    UserClearance,
    UserVerificationCode,
)
from common.tasks import (
    cleanup_expired_verification_codes,
    cleanup_temporary_media_task,
)
from common.utils import get_default_start_time
from generic.schema.enums import DateGroupings

SIGNAL_APPLY_ASYNC = "common.signals.convert_temporary_media_to_media_task.apply_async"
TASK_APPLY_ASYNC = "common.tasks.convert_temporary_media_to_media_task.apply_async"


class CommonModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="test-firebase-uid-12345",
            nickname="TestUser",
        )

    def test_user_display_name(self):
        self.assertEqual(self.user.display_name, "TestUser")

        user_no_nick = User.objects.create(
            firebase_id="anon-firebase-987654321",
        )
        self.assertEqual(user_no_nick.display_name, "anon-fir")

    def test_user_verification_code_generation(self):
        vc = UserVerificationCode.objects.create(user=self.user)
        self.assertTrue(100000 <= vc.code <= 999999)

    def test_clearance_and_feature_flag(self):
        # Clearance rows are seeded by common/migrations/0012_clearance_data.py,
        # FeatureFlag rows by 0016 — fetch, don't create.
        clearance = Clearance.objects.get(name=ClearanceType.TRUSTED_MEDIA_UPLOADER)
        user_clearance = UserClearance.objects.create(
            user=self.user, clearance=clearance
        )
        self.assertEqual(self.user.clearances.count(), 1)
        self.assertEqual(
            user_clearance.clearance.name, ClearanceType.TRUSTED_MEDIA_UPLOADER
        )

        flag = FeatureFlag.objects.get(name=FeatureFlagType.IMAGE_UPLOAD)
        flag.enabled = True
        flag.save()
        self.assertTrue(
            FeatureFlag.objects.get(name=FeatureFlagType.IMAGE_UPLOAD).enabled
        )

    def test_temporary_media_and_media(self):
        temp_media = TemporaryMedia.objects.create(
            uploader=self.user,
            upload_type=TemporaryMediaType.SPOTTING_EVENT,
            status=TemporaryMediaStatus.PENDING,
            metadata={"test_key": "test_val"},
        )
        self.assertEqual(temp_media.status, TemporaryMediaStatus.PENDING)
        self.assertEqual(temp_media.metadata["test_key"], "test_val")

    def test_default_start_time_date_groupings(self):
        for grouping in [
            DateGroupings.DAY,
            DateGroupings.WEEK,
            DateGroupings.MONTH,
            DateGroupings.YEAR,
        ]:
            start_time = get_default_start_time(grouping)
            self.assertIsNotNone(start_time)


class CleanupExpiredVerificationCodesTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="cleanup-verification-codes-uid",
        )

    def test_cleanup_expired_verification_codes(self):
        expired_code = UserVerificationCode.objects.create(user=self.user)
        fresh_code = UserVerificationCode.objects.create(user=self.user)

        # TimeStampedModel auto-sets `created` on save; .update() bypasses that.
        UserVerificationCode.objects.filter(id=expired_code.id).update(
            created=now()
            - timedelta(minutes=settings.VERIFICATION_CODE_EXPIRE_MINUTES + 10)
        )

        cleanup_expired_verification_codes.apply()

        remaining_ids = list(UserVerificationCode.objects.values_list("id", flat=True))
        self.assertEqual(remaining_ids, [fresh_code.id])


class CleanupTemporaryMediaTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="cleanup-temporary-media-uid",
        )

    def _set_image_upload_flag(self, enabled: bool):
        # FeatureFlag rows are migration-seeded — update, don't create.
        FeatureFlag.objects.filter(name=FeatureFlagType.IMAGE_UPLOAD).update(
            enabled=enabled
        )

    def _create_temporary_media(self, status: str, created_delta=None):
        # Creating a TemporaryMedia fires the post_save receiver, which would
        # hit the real broker — patch it out.
        with patch(SIGNAL_APPLY_ASYNC):
            temp_media = TemporaryMedia.objects.create(
                uploader=self.user,
                upload_type=TemporaryMediaType.SPOTTING_EVENT,
                status=status,
                metadata={},
            )
        if created_delta is not None:
            TemporaryMedia.objects.filter(id=temp_media.id).update(
                created=now() - created_delta
            )
            temp_media.refresh_from_db()
        return temp_media

    def test_cleanup_temporary_media_task_enabled(self):
        self._set_image_upload_flag(True)

        stale_pending = self._create_temporary_media(
            TemporaryMediaStatus.PENDING,
            created_delta=timedelta(minutes=10),
        )
        override_cleared = self._create_temporary_media(
            TemporaryMediaStatus.OVERRIDE_CLEARED,
        )
        old_to_delete = self._create_temporary_media(
            TemporaryMediaStatus.TO_DELETE,
            created_delta=timedelta(days=31),
        )
        fresh_pending = self._create_temporary_media(
            TemporaryMediaStatus.PENDING,
        )

        with patch(TASK_APPLY_ASYNC) as mock_apply_async:
            cleanup_temporary_media_task.apply()

        self.assertEqual(mock_apply_async.call_count, 2)
        dispatched_ids = {
            c.kwargs["kwargs"]["temporary_media_id"]
            for c in mock_apply_async.call_args_list
        }
        self.assertEqual(dispatched_ids, {stale_pending.id, override_cleared.id})

        # The old TO_DELETE row is garbage-collected; everything else stays.
        self.assertFalse(TemporaryMedia.objects.filter(id=old_to_delete.id).exists())
        self.assertTrue(TemporaryMedia.objects.filter(id=stale_pending.id).exists())
        self.assertTrue(TemporaryMedia.objects.filter(id=override_cleared.id).exists())
        self.assertTrue(TemporaryMedia.objects.filter(id=fresh_pending.id).exists())

    def test_cleanup_temporary_media_task_flag_disabled_is_noop(self):
        self._set_image_upload_flag(False)

        stale_pending = self._create_temporary_media(
            TemporaryMediaStatus.PENDING,
            created_delta=timedelta(minutes=10),
        )
        old_to_delete = self._create_temporary_media(
            TemporaryMediaStatus.TO_DELETE,
            created_delta=timedelta(days=31),
        )

        with patch(TASK_APPLY_ASYNC) as mock_apply_async:
            cleanup_temporary_media_task.apply()

        mock_apply_async.assert_not_called()
        self.assertTrue(TemporaryMedia.objects.filter(id=stale_pending.id).exists())
        self.assertTrue(TemporaryMedia.objects.filter(id=old_to_delete.id).exists())


class TemporaryMediaSignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="temporary-media-signal-uid",
        )

    def test_signal_dispatches_conversion_for_pending(self):
        with patch(SIGNAL_APPLY_ASYNC) as mock_apply_async:
            temp_media = TemporaryMedia.objects.create(
                uploader=self.user,
                upload_type=TemporaryMediaType.SPOTTING_EVENT,
                status=TemporaryMediaStatus.PENDING,
                metadata={},
            )

        mock_apply_async.assert_called_once_with(
            kwargs={"temporary_media_id": temp_media.id}
        )
        self.assertEqual(temp_media.status, TemporaryMediaStatus.PENDING)

    def test_signal_trusted_uploader_is_trusted_cleared(self):
        clearance = Clearance.objects.get(name=ClearanceType.TRUSTED_MEDIA_UPLOADER)
        UserClearance.objects.create(user=self.user, clearance=clearance)

        with patch(SIGNAL_APPLY_ASYNC) as mock_apply_async:
            temp_media = TemporaryMedia.objects.create(
                uploader=self.user,
                upload_type=TemporaryMediaType.SPOTTING_EVENT,
                status=TemporaryMediaStatus.PENDING,
                metadata={},
            )

        self.assertEqual(temp_media.status, TemporaryMediaStatus.TRUSTED_CLEARED)
        mock_apply_async.assert_called_once_with(
            kwargs={"temporary_media_id": temp_media.id}
        )

    def test_signal_does_not_dispatch_on_update(self):
        with patch(SIGNAL_APPLY_ASYNC) as mock_apply_async:
            temp_media = TemporaryMedia.objects.create(
                uploader=self.user,
                upload_type=TemporaryMediaType.SPOTTING_EVENT,
                status=TemporaryMediaStatus.PENDING,
                metadata={},
            )
            mock_apply_async.reset_mock()

            temp_media.metadata = {"updated": True}
            temp_media.save()

            mock_apply_async.assert_not_called()
