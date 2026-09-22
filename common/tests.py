import io
from datetime import date, timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models import Count
from django.test import TestCase
from django.utils.timezone import now
from PIL import Image
from strawberry import UNSET
from strawberry.types.maybe import Some

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
    Vote,
)
from common.schema.inputs import UserInput
from common.schema.scalars import UserScalar
from common.tasks import (
    cleanup_expired_verification_codes,
    cleanup_temporary_media_task,
    convert_temporary_media_to_media_task,
)
from common.utils import get_default_start_time
from generic.schema.enums import DateGroupings
from incident.enums import PassengerStatus
from incident.models import LineStatusReport, SocialMediaLink
from operation.enums import VehicleStatus
from operation.models import (
    Line,
    Station,
    StationLine,
    Vehicle,
    VehicleLine,
    VehicleType,
)
from rosak.tests import execute_graphql_async
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event, EventMedia

SIGNAL_APPLY_ASYNC = "common.signals.convert_temporary_media_to_media_task.apply_async"
TASK_APPLY_ASYNC = "common.tasks.convert_temporary_media_to_media_task.apply_async"
SIGNAL_NSFW_APPLY_ASYNC = "common.signals.check_temporary_media_nsfw.apply_async"


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


class TestDateUtilities(TestCase):
    def test_get_default_start_time_with_daily_grouping(self):
        today = date.today()
        expected = today - timedelta(days=365)
        self.assertEqual(get_default_start_time(DateGroupings.DAY), expected)

    def test_get_default_start_time_with_weekly_grouping(self):
        today = date.today()
        expected = (today - timedelta(days=today.weekday())) - timedelta(days=56)
        self.assertEqual(get_default_start_time(DateGroupings.WEEK), expected)


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


class UserPrivacyTests(TestCase):
    """Tests for User.spotting_data_public privacy logic"""

    async def test_user_spotting_data_public_defaults_to_false(self):
        """New users should have private spotting data by default"""
        from common.models import User

        user = await User.objects.acreate(
            firebase_id="test-new-user-uid", nickname="TestUser"
        )
        self.assertFalse(user.spotting_data_public)

    async def test_public_user_query_returns_user_by_id(self):
        """publicUser(id:) query should return user when Firebase uid exists"""
        from common.models import User
        from rosak.tests import execute_graphql_async

        owner = await User.objects.acreate(
            firebase_id="owner-uid", nickname="OwnerUser"
        )
        other_user = await User.objects.acreate(
            firebase_id="other-uid", nickname="OtherUser"
        )

        query = """
            query GetPublicUser($id: ID!) {
                publicUser(id: $id) {
                    nickname
                    spottingsCount
                }
            }
        """
        result = await execute_graphql_async(
            query, variables={"id": owner.firebase_id}, user=other_user
        )
        self.assertIsNone(result.errors, f"Query failed: {result.errors}")
        self.assertEqual(result.data["publicUser"]["nickname"], "OwnerUser")

    async def test_public_user_query_returns_null_for_unknown_uid(self):
        """publicUser(id:) should return null for a non-existent Firebase uid"""
        from common.models import User
        from rosak.tests import execute_graphql_async

        viewer = await User.objects.acreate(firebase_id="viewer-uid", nickname="V")

        query = """
            query GetPublicUser($id: ID!) {
                publicUser(id: $id) {
                    nickname
                }
            }
        """
        result = await execute_graphql_async(
            query, variables={"id": "no-such-firebase-uid"}, user=viewer
        )
        self.assertIsNone(result.errors)
        self.assertIsNone(result.data["publicUser"])

    async def test_spottings_field_null_when_private(self):
        """Owner's spottings should be null for non-owners when private"""
        from common.models import User
        from rosak.tests import execute_graphql_async

        owner = await User.objects.acreate(
            firebase_id="owner-private-uid",
            nickname="PrivateOwner",
            spotting_data_public=False,
        )
        other_user = await User.objects.acreate(
            firebase_id="viewer-uid", nickname="Viewer"
        )

        query = """
            query GetPublicUser($id: ID!) {
                publicUser(id: $id) {
                    nickname
                    spottings { id }
                }
            }
        """
        result = await execute_graphql_async(
            query, variables={"id": owner.firebase_id}, user=other_user
        )
        self.assertIsNone(result.errors)
        self.assertIsNone(
            result.data["publicUser"]["spottings"],
            "Spottings should be null when private",
        )

    async def test_spottings_field_visible_when_public(self):
        """Owner's spottings should be visible when spotting_data_public=True"""
        from common.models import User
        from rosak.tests import execute_graphql_async

        owner = await User.objects.acreate(
            firebase_id="owner-public-uid",
            nickname="PublicOwner",
            spotting_data_public=True,
        )
        other_user = await User.objects.acreate(
            firebase_id="viewer2-uid", nickname="Viewer2"
        )

        query = """
            query GetPublicUser($id: ID!) {
                publicUser(id: $id) {
                    spottings { id }
                }
            }
        """
        result = await execute_graphql_async(
            query, variables={"id": owner.firebase_id}, user=other_user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(
            result.data["publicUser"]["spottings"],
            "Spottings should be visible when public",
        )

    async def test_owner_always_sees_own_spottings(self):
        """Owner should always see their own spottings regardless of flag"""
        from common.models import User
        from rosak.tests import execute_graphql_async

        owner = await User.objects.acreate(
            firebase_id="owner-self-uid",
            nickname="SelfViewer",
            spotting_data_public=False,  # Private
        )

        query = """
            query GetPublicUser($id: ID!) {
                publicUser(id: $id) {
                    spottings { id }
                }
            }
        """
        result = await execute_graphql_async(
            query, variables={"id": owner.firebase_id}, user=owner
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(
            result.data["publicUser"]["spottings"],
            "Owner always sees own spottings",
        )


class SpottingDataPublicMigrationTests(TestCase):
    """Test migration sets correct defaults for spotting_data_public"""

    def test_new_users_have_private_data_by_default(self):
        """After migration, new users should have spotting_data_public=False"""
        from common.models import User

        user = User.objects.create(
            firebase_id="post-migration-uid", nickname="PostMigrationUser"
        )
        self.assertFalse(user.spotting_data_public)


class TestUserInput(TestCase):
    def test_user_input_omitted_spotting_data_preserves_db_value(self):
        from rosak.tests.test_schema import assert_maybe_field_behavior

        assert_maybe_field_behavior(
            input_class=UserInput,
            field_name="spotting_data_public",
            test_cases=[
                ({"nickname": "test"}, UNSET),
            ],
        )

    def test_user_input_explicit_null_clears_field(self):
        from rosak.tests.test_schema import assert_maybe_field_behavior

        assert_maybe_field_behavior(
            input_class=UserInput,
            field_name="spotting_data_public",
            test_cases=[
                ({"nickname": "test", "spottingDataPublic": None}, Some(None)),
            ],
        )

    def test_user_input_explicit_true_updates_field(self):
        from rosak.tests.test_schema import assert_maybe_field_behavior

        assert_maybe_field_behavior(
            input_class=UserInput,
            field_name="spotting_data_public",
            test_cases=[
                ({"nickname": "test", "spottingDataPublic": True}, Some(True)),
            ],
        )


class TestUpdateUserMutation(TestCase):
    def setUp(self):
        self.mutation = """
            mutation UpdateUser($input: UserInput!) {
                updateUser(input: $input) {
                    nickname
                    spottingDataPublic
                }
            }
        """

    async def test_omitted_spotting_data_preserves_db_value(self):
        user = await User.objects.acreate(
            firebase_id="test-user-preserve-uid",
            nickname="OriginalNick",
            spotting_data_public=True,
        )

        variables = {
            "input": {
                "nickname": "UpdatedNick",
            }
        }
        result = await execute_graphql_async(
            self.mutation, variables=variables, user=user
        )
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["updateUser"]["nickname"], "UpdatedNick")
        self.assertEqual(result.data["updateUser"]["spottingDataPublic"], True)

        await user.arefresh_from_db()
        self.assertEqual(user.nickname, "UpdatedNick")
        self.assertTrue(user.spotting_data_public)

    async def test_explicit_true_updates_value(self):
        user = await User.objects.acreate(
            firebase_id="test-user-true-uid",
            nickname="OriginalNick",
            spotting_data_public=False,
        )

        variables = {
            "input": {
                "nickname": "UpdatedNick",
                "spottingDataPublic": True,
            }
        }
        result = await execute_graphql_async(
            self.mutation, variables=variables, user=user
        )
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["updateUser"]["nickname"], "UpdatedNick")
        self.assertEqual(result.data["updateUser"]["spottingDataPublic"], True)

        await user.arefresh_from_db()
        self.assertEqual(user.nickname, "UpdatedNick")
        self.assertTrue(user.spotting_data_public)

    async def test_explicit_false_updates_value(self):
        user = await User.objects.acreate(
            firebase_id="test-user-false-uid",
            nickname="OriginalNick",
            spotting_data_public=True,
        )

        variables = {
            "input": {
                "nickname": "UpdatedNick",
                "spottingDataPublic": False,
            }
        }
        result = await execute_graphql_async(
            self.mutation, variables=variables, user=user
        )
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["updateUser"]["nickname"], "UpdatedNick")
        self.assertEqual(result.data["updateUser"]["spottingDataPublic"], False)

        await user.arefresh_from_db()
        self.assertEqual(user.nickname, "UpdatedNick")
        self.assertFalse(user.spotting_data_public)


class TestUserScalarTrends(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="test-user-trends-uid",
            nickname="TrendsUser",
            spotting_data_public=True,
        )
        self.line = Line.objects.create(
            display_name="Kelana Jaya Line",
            code="KJL",
            display_color="#ff0000",
        )
        self.vehicle_type = VehicleType.objects.create(
            display_name="Innovia Metro 300",
            internal_name="INNOVIA_300",
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 40",
            vehicle_type=self.vehicle_type,
            status=SpottingVehicleStatus.IN_SERVICE,
        )
        today = date.today()
        Event.objects.create(
            reporter=self.user,
            vehicle=self.vehicle,
            spotting_date=today - timedelta(days=2),
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
        )
        Event.objects.create(
            reporter=self.user,
            vehicle=self.vehicle,
            spotting_date=today - timedelta(days=10),
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
        )

    def test_spotting_trends_defaults_to_last_7_days(self):
        trends = UserScalar.spotting_trends.base_resolver(
            self.user, start=None, end=None
        )
        self.assertIsNotNone(trends)
        self.assertGreater(len(trends), 0)
        self.assertEqual(len(trends), 366)

    def test_spotting_trends_with_explicit_range(self):
        today = date.today()
        start = today - timedelta(days=5)
        end = today
        trends = UserScalar.spotting_trends.base_resolver(
            self.user, start=Some(start), end=Some(end)
        )
        self.assertIsNotNone(trends)
        self.assertEqual(len(trends), 6)

    def test_spotting_trends_with_partial_start_only(self):
        today = date.today()
        start = today - timedelta(days=15)
        trends = UserScalar.spotting_trends.base_resolver(
            self.user, start=Some(start), end=None
        )
        self.assertIsNotNone(trends)
        self.assertEqual(len(trends), 16)


class TestDjangoListConnection(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="test-django-list-connection-uid",
            nickname="ConnectionUser",
        )

    async def test_connection_total_count_field(self):
        for i in range(7):
            await Media.objects.acreate(
                uploader=self.user,
                width=1920,
                height=1080,
                file_id=f"test_conn_file_{i}",
                file_name=f"test_conn_photo_{i}.jpg",
            )

        query = """
            query {
                medias(first: 3) {
                    totalCount
                    edges {
                        node {
                            id
                        }
                    }
                }
            }
        """
        from strawberry_django.relay import DjangoListConnection

        import common.schema.schema as common_schema_module
        from common.schema.scalars import MediaType
        from common.schema.schema import CommonScalars

        self.assertTrue(
            hasattr(common_schema_module, "DjangoListConnection"),
            "common.schema.schema should import DjangoListConnection",
        )
        self.assertFalse(
            hasattr(common_schema_module, "ListConnectionWithTotalCount"),
            "common.schema.schema should not import deprecated ListConnectionWithTotalCount",
        )

        medias_type = CommonScalars.__annotations__.get("medias")
        self.assertEqual(
            medias_type,
            DjangoListConnection[MediaType],
            "CommonScalars.medias must use DjangoListConnection type annotation",
        )

        result = await execute_graphql_async(query)
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["medias"]["totalCount"], 7)
        self.assertEqual(len(result.data["medias"]["edges"]), 3)

    async def test_connection_pagination_info(self):
        import common.schema.schema as common_schema_module

        self.assertTrue(
            hasattr(common_schema_module, "DjangoListConnection"),
            "common.schema.schema should import DjangoListConnection",
        )
        self.assertFalse(
            hasattr(common_schema_module, "ListConnectionWithTotalCount"),
            "common.schema.schema should not import deprecated ListConnectionWithTotalCount",
        )

        for i in range(5):
            await Media.objects.acreate(
                uploader=self.user,
                width=1920,
                height=1080,
                file_id=f"test_page_file_{i}",
                file_name=f"test_page_photo_{i}.jpg",
            )

        query = """
            query {
                medias(first: 2) {
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
                        }
                    }
                }
            }
        """
        result = await execute_graphql_async(query)
        self.assertIsNone(result.errors)
        page_info = result.data["medias"]["pageInfo"]
        self.assertTrue(page_info["hasNextPage"])
        self.assertFalse(page_info["hasPreviousPage"])
        self.assertIsNotNone(page_info["startCursor"])
        self.assertIsNotNone(page_info["endCursor"])


class TemporaryMediaConversionTaskTests(TestCase):
    """Video skips PIL; image path still verifies + links EventMedia."""

    def setUp(self):
        self.user = User.objects.create(
            firebase_id="convert-temporary-media-uid",
            nickname="ConvertUser",
        )
        # Seed rows are not guaranteed in the shared --keepdb test DB.
        FeatureFlag.objects.get_or_create(
            name=FeatureFlagType.IMAGE_UPLOAD,
            defaults={"enabled": True},
        )
        FeatureFlag.objects.filter(name=FeatureFlagType.IMAGE_UPLOAD).update(
            enabled=True
        )

        vehicle_type = VehicleType.objects.create(
            internal_name="CONVERT_MEDIA_VT",
            display_name="Convert Media Vehicle Type",
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 900",
            vehicle_type=vehicle_type,
            status=SpottingVehicleStatus.IN_SERVICE,
        )
        self.event = Event.objects.create(
            reporter=self.user,
            vehicle=self.vehicle,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date.today(),
        )

    def _create_temporary_media(self, metadata, filename):
        # Creating a TemporaryMedia fires the post_save receiver, which would
        # hit the real broker — patch out both dispatch calls.
        with patch(SIGNAL_APPLY_ASYNC), patch(SIGNAL_NSFW_APPLY_ASYNC):
            return TemporaryMedia.objects.create(
                uploader=self.user,
                file=f"temporary_media/{filename}",
                upload_type=TemporaryMediaType.SPOTTING_EVENT,
                status=TemporaryMediaStatus.PENDING,
                metadata=metadata,
            )

    def _run_convert_task(self, temp_media, content, attachment):
        with (
            patch(
                "storages.backends.s3boto3.S3Boto3Storage.open",
                return_value=io.BytesIO(content),
            ),
            patch(
                "storages.backends.s3boto3.S3Boto3Storage.url",
                return_value="https://cdn.example.com/temporary_media",
            ),
            patch("common.tasks.requests.get") as mock_get,
            patch("common.tasks.DiscordWebhook") as mock_webhook,
            patch(
                "common.imgur_storage.ImgurStorage._save",
                return_value="stored_media",
            ) as mock_storage_save,
            patch("common.tasks.Image.open", wraps=Image.open) as mock_image_open,
        ):
            mock_get.return_value.content = content
            mock_webhook.return_value.execute.return_value.json.return_value = {
                "id": "discord-message-id",
                "attachments": [attachment],
            }
            result = convert_temporary_media_to_media_task.apply(
                kwargs={"temporary_media_id": temp_media.id}
            )
            self.assertTrue(result.successful(), result.traceback)

        return mock_image_open, mock_storage_save

    def test_video_temporary_media_converts_without_pil(self):
        temp_media = self._create_temporary_media(
            metadata={
                "mime_type": "video/mp4",
                "spotting_event_id": self.event.id,
                "caption": "hi",
                "duration": 12,
                "width": 1920,
                "height": 1080,
                "file_name": "clip.mp4",
            },
            filename="clip.mp4",
        )

        mock_image_open, _ = self._run_convert_task(
            temp_media,
            content=b"\x00\x00\x00\x18ftypmp42 not a real video",
            attachment={
                "id": "discord-attachment-1",
                "filename": "clip.mp4",
                "width": 1920,
                "height": 1080,
                "content_type": "video/mp4",
            },
        )

        mock_image_open.assert_not_called()

        media = Media.objects.get(uploader=self.user)
        self.assertEqual(media.content_type, "video/mp4")
        self.assertEqual(media.caption, "hi")
        self.assertEqual(media.duration, 12)
        self.assertEqual(media.width, 1920)
        self.assertEqual(media.height, 1080)
        self.assertEqual(media.file_name, "clip.mp4")
        self.assertTrue(
            EventMedia.objects.filter(event=self.event, media=media).exists()
        )

        temp_media.refresh_from_db()
        self.assertEqual(temp_media.status, TemporaryMediaStatus.TO_DELETE)
        self.assertEqual(temp_media.fail_count, 0)

    def test_image_temporary_media_still_verifies_and_links_event(self):
        buffer = io.BytesIO()
        Image.new("RGB", (3, 2), color="blue").save(buffer, format="JPEG")
        image_bytes = buffer.getvalue()

        temp_media = self._create_temporary_media(
            metadata={
                "mime_type": "image/jpeg",
                "spotting_event_id": self.event.id,
                "caption": "photo",
                "width": 3,
                "height": 2,
                "file_name": "photo.jpg",
            },
            filename="photo.jpg",
        )

        mock_image_open, _ = self._run_convert_task(
            temp_media,
            content=image_bytes,
            attachment={
                "id": "discord-attachment-2",
                "filename": "photo.jpg",
                "width": 3,
                "height": 2,
                "content_type": "image/jpeg",
            },
        )

        mock_image_open.assert_called_once()

        media = Media.objects.get(uploader=self.user)
        self.assertEqual(media.content_type, "image/jpeg")
        self.assertEqual(media.caption, "photo")
        self.assertIsNone(media.duration)
        self.assertTrue(
            EventMedia.objects.filter(event=self.event, media=media).exists()
        )


class TemporaryMediaReviewHoldAndCleanupTests(TestCase):
    """AWAITING_REVIEW is held; cleanup converts OVERRIDE_CLEARED but is bounded."""

    def setUp(self):
        self.user = User.objects.create(
            firebase_id="review-hold-cleanup-uid",
        )
        # Seed rows are not guaranteed in the shared --keepdb test DB.
        FeatureFlag.objects.get_or_create(
            name=FeatureFlagType.IMAGE_UPLOAD,
            defaults={"enabled": True},
        )
        FeatureFlag.objects.filter(name=FeatureFlagType.IMAGE_UPLOAD).update(
            enabled=True
        )

    def _create_temporary_media(self, status, fail_count=0):
        with patch(SIGNAL_APPLY_ASYNC), patch(SIGNAL_NSFW_APPLY_ASYNC):
            temp_media = TemporaryMedia.objects.create(
                uploader=self.user,
                upload_type=TemporaryMediaType.SPOTTING_EVENT,
                status=status,
                metadata={},
            )
        if fail_count:
            TemporaryMedia.objects.filter(id=temp_media.id).update(
                fail_count=fail_count
            )
            temp_media.refresh_from_db()
        return temp_media

    def test_awaiting_review_held(self):
        with (
            patch(SIGNAL_APPLY_ASYNC) as mock_signal_apply,
            patch(TASK_APPLY_ASYNC) as mock_task_apply,
        ):
            temp_media = TemporaryMedia.objects.create(
                uploader=self.user,
                upload_type=TemporaryMediaType.SPOTTING_EVENT,
                status=TemporaryMediaStatus.AWAITING_REVIEW,
                metadata={},
            )

        mock_signal_apply.assert_not_called()
        mock_task_apply.assert_not_called()

        with patch(TASK_APPLY_ASYNC) as mock_task_apply:
            cleanup_temporary_media_task.apply()

        mock_task_apply.assert_not_called()

        temp_media.refresh_from_db()
        self.assertEqual(temp_media.status, TemporaryMediaStatus.AWAITING_REVIEW)

    def test_override_cleared_converts(self):
        temp_media = self._create_temporary_media(
            TemporaryMediaStatus.OVERRIDE_CLEARED,
        )

        with patch(TASK_APPLY_ASYNC) as mock_task_apply:
            cleanup_temporary_media_task.apply()

        mock_task_apply.assert_called_once_with(
            kwargs={"temporary_media_id": temp_media.id}
        )

    def test_cleanup_override_cleared_bounded(self):
        temp_media = self._create_temporary_media(
            TemporaryMediaStatus.OVERRIDE_CLEARED,
            fail_count=5,
        )

        with patch(TASK_APPLY_ASYNC) as mock_task_apply:
            cleanup_temporary_media_task.apply()

        mock_task_apply.assert_not_called()

        temp_media.refresh_from_db()
        self.assertEqual(temp_media.status, TemporaryMediaStatus.OVERRIDE_CLEARED)
        self.assertEqual(temp_media.fail_count, 5)


class SeedDemoDataCommandTests(TestCase):
    """Contract of the ``seed_demo_data`` management command."""

    SEED_LINES = (
        "BRT SBL",
        "KTM ETS",
        "KTMK-PKL",
        "LRT AGL",
        "LRT KJL",
        "MRL",
        "MRT KGL",
        "MRT PYL",
    )

    @classmethod
    def setUpTestData(cls):
        from common.management.commands.seed_demo_data import SEED_USER_PREFIX

        cls.prefix = SEED_USER_PREFIX
        for index, code in enumerate(cls.SEED_LINES):
            line = Line.objects.create(
                code=code,
                display_name=f"Seed Line {code}",
                display_color="#336699",
            )
            station = Station.objects.create(display_name=f"{code} Station")
            StationLine.objects.create(
                station=station,
                line=line,
                display_name=f"{code} Station",
                internal_representation=f"SD{index:03d}",
            )
        vehicle_type = VehicleType.objects.create(
            internal_name="SEED-VT",
            display_name="Seed Vehicle Type",
        )
        for n in range(3):
            Vehicle.objects.create(
                identification_no=f"SEED{n:03d}",
                vehicle_type=vehicle_type,
                status=VehicleStatus.IN_SERVICE,
            )

    def _seeded(self, model, field="user"):
        return model.objects.filter(
            **{f"{field}__firebase_id__startswith": self.prefix}
        )

    def test_seed_generates_varied_volume_and_is_idempotent(self):
        call_command("seed_demo_data")

        users = User.objects.filter(firebase_id__startswith=self.prefix)
        self.assertGreaterEqual(users.count(), 100)

        reports = self._seeded(LineStatusReport)
        self.assertGreaterEqual(reports.count(), 250)

        reported_line_ids = set(reports.values_list("line_id", flat=True))
        for line in Line.objects.all()[:6]:
            self.assertIn(line.id, reported_line_ids)

        window = reports.filter(created__gte=now() - timedelta(minutes=15))
        multi_status = (
            window.values("line_id")
            .annotate(distinct_statuses=Count("status", distinct=True))
            .filter(distinct_statuses__gte=2)
        )
        self.assertGreaterEqual(multi_status.count(), 3)

        self.assertTrue(reports.filter(notes="").exists())
        self.assertTrue(reports.exclude(notes="").exists())
        self.assertGreaterEqual(reports.values("status").distinct().count(), 2)
        self.assertGreaterEqual(
            reports.exclude(notes="").values("notes").distinct().count(), 5
        )

        links = self._seeded(SocialMediaLink)
        self.assertGreaterEqual(links.count(), 30)
        content_type = ContentType.objects.get_for_model(SocialMediaLink)
        self.assertTrue(
            Vote.objects.filter(
                content_type=content_type,
                object_id__in=list(links.values_list("id", flat=True)),
            ).exists()
        )

        before = (
            users.count(),
            reports.count(),
            links.count(),
            Event.objects.filter(reporter__firebase_id__startswith=self.prefix).count(),
        )
        call_command("seed_demo_data")
        after = (
            User.objects.filter(firebase_id__startswith=self.prefix).count(),
            self._seeded(LineStatusReport).count(),
            self._seeded(SocialMediaLink).count(),
            Event.objects.filter(reporter__firebase_id__startswith=self.prefix).count(),
        )
        self.assertEqual(before, after)

    def test_flush_removes_only_seeded_rows(self):
        outsider = User.objects.create(firebase_id="seed-outsider", nickname="Outsider")
        keep_line = Line.objects.get(code="MRT PYL")
        keep_link = SocialMediaLink.objects.create(
            url="https://example.com/keep-me",
            title="Unrelated pre-existing link",
            user=outsider,
        )
        LineStatusReport.objects.create(
            line=keep_line,
            user=outsider,
            status=PassengerStatus.NORMAL,
            notes="pre-existing report",
        )

        call_command("seed_demo_data", reports=20, users=5, links=5)
        self.assertTrue(
            User.objects.filter(firebase_id__startswith=self.prefix).exists()
        )

        call_command("seed_demo_data", flush=True)

        self.assertFalse(
            User.objects.filter(firebase_id__startswith=self.prefix).exists()
        )
        self.assertFalse(self._seeded(LineStatusReport).exists())
        self.assertFalse(self._seeded(SocialMediaLink).exists())
        self.assertTrue(SocialMediaLink.objects.filter(id=keep_link.id).exists())
        self.assertTrue(LineStatusReport.objects.filter(user=outsider).exists())
