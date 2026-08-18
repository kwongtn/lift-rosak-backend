from datetime import date, timedelta
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
    Media,
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
from operation.models import Line, Vehicle, VehicleLine, VehicleType
from rosak.tests import execute_graphql_async
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event

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


class CommonGraphQLTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="common-graphql-user-uid",
            nickname="InitialNick",
        )
        self.other_user = User.objects.create(
            firebase_id="common-graphql-other-user-uid",
            nickname="OtherNick",
        )
        self.line = Line.objects.create(
            code="KJL",
            display_name="Kelana Jaya Line",
            display_color="#d32f2f",
        )
        self.v_type = VehicleType.objects.create(
            internal_name="KJL_INNOVIA_TEST",
            display_name="Innovia 300",
        )
        self.v1 = Vehicle.objects.create(
            identification_no="Set 101",
            vehicle_type=self.v_type,
            status="IN_SERVICE",
        )
        self.v2 = Vehicle.objects.create(
            identification_no="Set 102",
            vehicle_type=self.v_type,
            status="IN_SERVICE",
        )
        self.v3 = Vehicle.objects.create(
            identification_no="Set 103",
            vehicle_type=self.v_type,
            status="IN_SERVICE",
        )
        self.v4 = Vehicle.objects.create(
            identification_no="Set 104",
            vehicle_type=self.v_type,
            status="IN_SERVICE",
        )
        VehicleLine.objects.create(vehicle=self.v1, line=self.line)
        VehicleLine.objects.create(vehicle=self.v2, line=self.line)
        VehicleLine.objects.create(vehicle=self.v3, line=self.line)
        VehicleLine.objects.create(vehicle=self.v4, line=self.line)

    async def test_get_user_data_query_profile_aggregates(self):
        today = date.today()
        yesterday_dt = now() - timedelta(days=1)
        await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.v1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=today,
        )
        await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.v1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=today,
        )
        e3 = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.v1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=today - timedelta(days=1),
        )
        await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.v2,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=today,
        )
        e5 = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.v2,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=today - timedelta(days=1),
        )
        await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.v3,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=today,
        )

        await Event.objects.filter(id__in=[e3.id, e5.id]).aupdate(created=yesterday_dt)

        query = """
            query {
                user {
                    nickname
                    spottingTrends(dateGroup: MONTH) {
                        dateKey
                        year
                        month
                        count
                    }
                    withMostEntries(type: DAY) {
                        dateKey
                        year
                        month
                        day
                        count
                    }
                    favouriteVehicles(count: 3) {
                        count
                        vehicle {
                            id
                            identificationNo
                        }
                    }
                }
            }
        """
        result = await execute_graphql_async(query, user=self.user)
        self.assertIsNone(result.errors)
        user_data = result.data["user"]
        self.assertEqual(user_data["nickname"], "InitialNick")

        favs = user_data["favouriteVehicles"]
        self.assertEqual(len(favs), 3)
        self.assertEqual(favs[0]["vehicle"]["identificationNo"], "Set 101")
        self.assertEqual(favs[0]["count"], 3)
        self.assertEqual(favs[1]["vehicle"]["identificationNo"], "Set 102")
        self.assertEqual(favs[1]["count"], 2)
        self.assertEqual(favs[2]["vehicle"]["identificationNo"], "Set 103")
        self.assertEqual(favs[2]["count"], 1)

        with_most = user_data["withMostEntries"]
        self.assertIsNotNone(with_most)
        self.assertEqual(with_most["year"], today.year)
        self.assertEqual(with_most["month"], today.month)
        self.assertEqual(with_most["day"], today.day)
        self.assertEqual(with_most["count"], 4)

        trends = user_data["spottingTrends"]
        self.assertIsInstance(trends, list)
        current_month_key = f"{today.year:04}-{today.month:02}"
        matching_month = next(
            (t for t in trends if t["dateKey"] == current_month_key), None
        )
        self.assertIsNotNone(matching_month)
        self.assertEqual(matching_month["count"], 6)

        empty_user_query = """
            query {
                user {
                    withMostEntries(type: DAY) {
                        dateKey
                        count
                    }
                }
            }
        """
        empty_result = await execute_graphql_async(
            empty_user_query, user=self.other_user
        )
        self.assertIsNotNone(empty_result.errors)
        self.assertTrue(
            any(
                "list index out of range" in str(err) or "IndexError" in str(err)
                for err in empty_result.errors
            )
        )

    async def test_update_user_nickname_mutation(self):
        mutation = """
            mutation {
                updateUser(input: { nickname: "NewNick" }) {
                    nickname
                    shortId
                }
            }
        """
        result = await execute_graphql_async(mutation, user=self.user)
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["updateUser"]["nickname"], "NewNick")

        await self.user.arefresh_from_db()
        self.assertEqual(self.user.nickname, "NewNick")

    async def test_request_verification_code_mutation(self):
        mutation = """
            mutation {
                requestVerificationCode {
                    code
                    created
                    user {
                        nickname
                    }
                }
            }
        """
        result = await execute_graphql_async(mutation, user=self.user)
        self.assertIsNone(result.errors)
        code_data = result.data["requestVerificationCode"]
        code = code_data["code"]
        self.assertTrue(100000 <= code <= 999999)
        self.assertEqual(code_data["user"]["nickname"], "InitialNick")

        db_code = await UserVerificationCode.objects.filter(
            user_id=self.user.id, code=code
        ).afirst()
        self.assertIsNotNone(db_code)
        self.assertEqual(db_code.code, code)

    async def test_medias_relay_cursor_pagination(self):
        medias = []
        for i in range(10):
            medias.append(
                await Media.objects.acreate(
                    uploader=self.user,
                    width=1920,
                    height=1080,
                    file_id=f"file_{i}",
                    file_name=f"photo_{i}.jpg",
                )
            )

        query_page1 = """
            query {
                medias(first: 5) {
                    totalCount
                    pageInfo {
                        hasNextPage
                        hasPreviousPage
                        startCursor
                        endCursor
                    }
                    edges {
                        cursor
                        node {
                            id
                            width
                            height
                        }
                    }
                }
            }
        """
        result_page1 = await execute_graphql_async(query_page1)
        self.assertIsNone(result_page1.errors)
        data_page1 = result_page1.data["medias"]
        self.assertEqual(data_page1["totalCount"], 10)
        self.assertEqual(len(data_page1["edges"]), 5)
        self.assertTrue(data_page1["pageInfo"]["hasNextPage"])
        end_cursor = data_page1["pageInfo"]["endCursor"]
        self.assertIsNotNone(end_cursor)

        query_page2 = f"""
            query {{
                medias(first: 5, after: "{end_cursor}") {{
                    totalCount
                    pageInfo {{
                        hasNextPage
                        hasPreviousPage
                        startCursor
                        endCursor
                    }}
                    edges {{
                        cursor
                        node {{
                            id
                        }}
                    }}
                }}
            }}
        """
        result_page2 = await execute_graphql_async(query_page2)
        self.assertIsNone(result_page2.errors)
        data_page2 = result_page2.data["medias"]
        self.assertEqual(data_page2["totalCount"], 10)
        self.assertEqual(len(data_page2["edges"]), 5)
        self.assertFalse(data_page2["pageInfo"]["hasNextPage"])

    async def test_medias_group_by_period_year(self):
        with patch(SIGNAL_APPLY_ASYNC):
            m1 = await Media.objects.acreate(
                uploader=self.user,
                file="some/path1.jpg",
                width=100,
                height=100,
            )
            m2 = await Media.objects.acreate(
                uploader=self.user,
                file="some/path2.jpg",
                width=200,
                height=200,
            )

        query = """
            query {
                mediasGroupByPeriod(type: YEAR) {
                    type
                    dateKey
                    year
                    month
                    day
                    count
                    medias {
                        id
                        width
                        height
                    }
                }
            }
        """
        result = await execute_graphql_async(query)
        self.assertIsNone(result.errors)
        group_data = result.data["mediasGroupByPeriod"]
        self.assertGreaterEqual(len(group_data), 1)

        current_year = date.today().year
        year_entry = next(
            (item for item in group_data if item["year"] == current_year), None
        )
        self.assertIsNotNone(year_entry)
        self.assertEqual(year_entry["dateKey"], f"{current_year:04}")
        self.assertEqual(year_entry["count"], 2)
        media_ids = [str(m["id"]) for m in year_entry["medias"]]
        self.assertIn(str(m1.id), media_ids)
        self.assertIn(str(m2.id), media_ids)
