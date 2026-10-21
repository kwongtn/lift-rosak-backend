import io
import struct
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.aggregates import ArrayAgg
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.db.models import Count, F, Q
from django.db.models.functions import TruncHour
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now
from PIL import ExifTags, Image
from rest_framework.test import APIRequestFactory
from strawberry import UNSET
from strawberry.relay import GlobalID
from strawberry.types.maybe import Some

from common.enums import (
    ClearanceType,
    FeatureFlagType,
    TemporaryMediaStatus,
    TemporaryMediaType,
)
from common.exif import is_heif, strip_gps
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
from common.schema.scalars import MediaType, UserScalar
from common.tasks import (
    cleanup_expired_verification_codes,
    cleanup_temporary_media_task,
    convert_temporary_media_to_media_task,
)
from common.utils import get_date_key, get_default_start_time
from common.views import GenericUpload
from generic.schema.enums import DateGroupings
from incident.enums import PassengerStatus
from incident.models import (
    CalendarIncident,
    CalendarIncidentMedia,
    LineStatusReport,
    SocialMediaLink,
)
from operation.enums import VehicleStatus
from operation.models import (
    Line,
    Station,
    StationLine,
    Vehicle,
    VehicleLine,
    VehicleType,
)
from rosak.tests import execute_graphql, execute_graphql_async
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event, EventMedia

SIGNAL_APPLY_ASYNC = "common.signals.convert_temporary_media_to_media_task.apply_async"
TASK_APPLY_ASYNC = "common.tasks.convert_temporary_media_to_media_task.apply_async"
SIGNAL_NSFW_APPLY_ASYNC = "common.signals.check_temporary_media_nsfw.apply_async"

PRINT_IM = b"PrintIM\x000300"
# The start of a HEIC file: an ISO base media "ftyp" box with the "heic" major brand.
HEIC_STUB = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"


def _jpeg(exif: Image.Exif | None = None) -> bytes:
    buffer = io.BytesIO()
    image = Image.effect_noise((64, 48), 80).convert("RGB")
    image.save(buffer, format="JPEG", quality=90, **({"exif": exif} if exif else {}))
    return buffer.getvalue()


def jpeg_with_gps(*, gps: bool = True, after_gps: bool = False) -> bytes:
    """A JPEG like a phone makes: capture time, make and model, orientation, GPS.

    `after_gps` adds an IFD0 tag that sorts after the GPS pointer (Samsung writes one).
    """
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "TestMake"
    exif[ExifTags.Base.Model] = "TestModel"
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.DateTime] = "2026:10:21 08:30:00"
    exif[ExifTags.IFD.Exif] = {ExifTags.Base.DateTimeOriginal: "2026:10:21 08:30:01"}
    if gps:
        exif[ExifTags.IFD.GPSInfo] = {
            ExifTags.GPS.GPSLatitudeRef: "N",
            ExifTags.GPS.GPSLatitude: (3.0, 6.0, 17.0),
            ExifTags.GPS.GPSLongitudeRef: "E",
            ExifTags.GPS.GPSLongitude: (101.0, 39.0, 22.0),
        }
    if after_gps:
        exif[0xC4A5] = PRINT_IM
    return _jpeg(exif)


def _tiff_with_gps(order: str, gps_offset: int | None = None) -> tuple[bytes, bytes]:
    """An EXIF TIFF block built by hand: (block, the raw GPS latitude bytes).

    IFD0 holds Orientation, the GPS pointer and a PrintIM-style tag after it.
    """
    header = (b"II" if order == "<" else b"MM") + struct.pack(order + "HI", 42, 8)
    gps_ifd = 8 + 2 + 12 * 3 + 4
    latitude_at = gps_ifd + 2 + 12 * 2 + 4

    ifd0 = struct.pack(order + "H", 3)
    ifd0 += struct.pack(order + "HHIHH", 0x0112, 3, 1, 6, 0)
    ifd0 += struct.pack(order + "HHII", 0x8825, 4, 1, gps_offset or gps_ifd)
    ifd0 += struct.pack(order + "HHI", 0xC4A5, 7, 4) + b"PIM\x00"
    ifd0 += struct.pack(order + "I", 0)

    gps = struct.pack(order + "H", 2)
    gps += struct.pack(order + "HHI", 1, 2, 2) + b"N\x00\x00\x00"
    gps += struct.pack(order + "HHII", 2, 5, 3, latitude_at)
    gps += struct.pack(order + "I", 0)

    latitude = struct.pack(order + "6I", 3, 1, 6, 1, 17, 1)
    return header + ifd0 + gps + latitude, latitude


def _with_exif_segment(jpeg: bytes, tiff: bytes) -> bytes:
    segment = b"\xff\xe1" + struct.pack(">H", 2 + 6 + len(tiff)) + b"Exif\x00\x00"
    return jpeg[:2] + segment + tiff + jpeg[2:]


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
        # The MONTH bucket below counts every event in the CURRENT month, so the
        # second fixture day has to stay inside it. On the 1st there is no
        # earlier day in the month, so e3/e5 share today instead — and then
        # `withMostEntries(DAY)` sees six events on one day rather than four/two.
        # Anchoring them to `now() - 1 day` made this test fail on every first
        # of the month: yesterday was last month, so only 4 of the 6 landed in
        # the current bucket (4 != 6).
        second_day = today - timedelta(days=1) if today.day > 1 else today
        second_dt = now() - timedelta(days=1) if today.day > 1 else now()
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
            spotting_date=second_day,
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
            spotting_date=second_day,
        )
        await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.v3,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=today,
        )

        await Event.objects.filter(id__in=[e3.id, e5.id]).aupdate(created=second_dt)

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
        # Six on the 1st (e3/e5 share today there), four on every other day.
        self.assertEqual(with_most["count"], 6 if second_day == today else 4)

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
        # No spottings at all: null, not an IndexError that nulls the whole user.
        self.assertIsNone(empty_result.errors)
        self.assertIsNone(empty_result.data["user"]["withMostEntries"])

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
                    file=f"photo_{i}.jpg",
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


class MediasGroupByPeriodTests(TestCase):
    """The GROUP BY resolver returns what the old ArrayAgg-and-loader one did (F012)."""

    QUERY = """
        query ($type: DateGroupings!) {
            mediasGroupByPeriod(type: $type) {
                type dateKey year month day count medias { id }
            }
        }
    """

    # Naive local times (USE_TZ = False), around year, month and leap-day edges.
    CREATED = [
        datetime(2023, 12, 31, 23, 59, 59),
        datetime(2024, 1, 1, 0, 0, 0),
        datetime(2024, 1, 1, 12, 0, 0),
        datetime(2024, 2, 29, 8, 15, 0),
        datetime(2024, 2, 29, 20, 45, 0),
        datetime(2024, 3, 31, 23, 59, 59),
        datetime(2025, 7, 4, 3, 30, 0),
    ]

    def setUp(self):
        self.user = User.objects.create(firebase_id="period-uid", nickname="Period")
        for created in self.CREATED:
            self._media("photo.jpg", created)
        # No photo file (None is saved as ""): filtered out, so these add no count
        # to an existing period and leave no period at all for 2022.
        self._media(None, datetime(2024, 5, 5, 10, 0, 0))
        self._media("", datetime(2024, 1, 1, 9, 0, 0))
        self._media("", datetime(2022, 6, 15, 9, 0, 0))

    def _media(self, file, created):
        with patch(SIGNAL_APPLY_ASYNC):
            media = Media.objects.create(uploader=self.user, file=file)
        # `created` is stamped from the real clock on insert, so move it afterwards.
        Media.objects.filter(pk=media.pk).update(created=created)

    @staticmethod
    async def _old_implementation(type):
        """The resolver as it was: ArrayAgg of ids per group, then a loader per id."""
        groupings = {"year": F("created__year")}
        if type in [DateGroupings.MONTH, DateGroupings.DAY]:
            groupings["month"] = F("created__month")
            if type == DateGroupings.DAY:
                groupings["day"] = F("created__day")

        rows = (
            Media.objects.filter(~Q(file=""))
            .annotate(**groupings)
            .values(*groupings.keys())
            .annotate(
                count=Count("id"), medias=ArrayAgg(F("id"), distinct=True, default=[])
            )
        )
        return [
            {
                "type": type.name,
                "dateKey": get_date_key(
                    year=row["year"], month=row.get("month"), day=row.get("day")
                ),
                "year": row["year"],
                "month": row.get("month"),
                "day": row.get("day"),
                "count": row["count"],
                "medias": [{"id": str(pk)} for pk in row["medias"]],
            }
            async for row in rows
        ]

    async def _new_implementation(self, type):
        result = await execute_graphql_async(self.QUERY, {"type": type.name})
        self.assertIsNone(result.errors)
        return result.data["mediasGroupByPeriod"]

    async def test_matches_the_old_implementation_for_every_period_type(self):
        expected_periods = {
            DateGroupings.YEAR: 3,
            DateGroupings.WEEK: 3,  # WEEK has always grouped like YEAR
            DateGroupings.MONTH: 5,
            DateGroupings.DAY: 5,
        }
        for type, n_periods in expected_periods.items():
            with self.subTest(type=type.name):
                old = await self._old_implementation(type)
                new = await self._new_implementation(type)

                self.assertEqual(new, old)
                self.assertEqual(len(new), n_periods)
                self.assertEqual(sum(p["count"] for p in new), 7)
                self.assertTrue(all(p["type"] == type.name for p in new))

    async def test_periods_are_oldest_first_and_empty_ones_are_absent(self):
        years = [p["year"] for p in await self._new_implementation(DateGroupings.YEAR)]
        self.assertEqual(years, [2023, 2024, 2025])  # 2022 only had a fileless row

        days = await self._new_implementation(DateGroupings.DAY)
        keys = [p["dateKey"] for p in days]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(
            keys[:3], ["2023-12-31", "2024-01-01", "2024-02-29"]
        )  # year edge and leap day stay on their own local date

    def test_a_count_only_selection_is_one_query_and_loads_no_media(self):
        # Sync on purpose: CaptureQueriesContext cannot be entered from async code.
        for type in (DateGroupings.YEAR, DateGroupings.DAY):
            with self.subTest(type=type.name):
                with CaptureQueriesContext(connection) as queries:
                    result = execute_graphql(
                        "query ($type: DateGroupings!) { mediasGroupByPeriod("
                        "type: $type) { year count } }",
                        {"type": type.name},
                    )

                self.assertIsNone(result.errors)
                self.assertEqual(len(queries), 1)
                self.assertIn("GROUP BY", queries[0]["sql"])
                self.assertNotIn("ARRAY_AGG", queries[0]["sql"])

    async def test_medias_of_mixed_groupings_in_one_request(self):
        result = await execute_graphql_async(
            """
            {
                byYear: mediasGroupByPeriod(type: YEAR) { year medias { id } }
                byDay: mediasGroupByPeriod(type: DAY) { year month day medias { id } }
            }
            """
        )
        self.assertIsNone(result.errors)

        old_year = await self._old_implementation(DateGroupings.YEAR)
        old_day = await self._old_implementation(DateGroupings.DAY)
        self.assertEqual(
            result.data["byYear"],
            [{"year": p["year"], "medias": p["medias"]} for p in old_year],
        )
        self.assertEqual(
            result.data["byDay"],
            [
                {
                    "year": p["year"],
                    "month": p["month"],
                    "day": p["day"],
                    "medias": p["medias"],
                }
                for p in old_day
            ],
        )


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

    async def test_explicit_null_spotting_data_public_is_rejected(self):
        # NOT NULL column: null must fail validation, not reach the DB as a 500.
        user = await User.objects.acreate(
            firebase_id="test-user-null-uid",
            nickname="OriginalNick",
            spotting_data_public=True,
        )

        variables = {"input": {"nickname": "UpdatedNick", "spottingDataPublic": None}}
        result = await execute_graphql_async(
            self.mutation, variables=variables, user=user
        )
        self.assertIsNotNone(result.errors)
        self.assertIn("cannot be explicitly set to null", str(result.errors[0]))
        self.assertIsNone(result.data)

        await user.arefresh_from_db()
        self.assertEqual(user.nickname, "OriginalNick")
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
        # The resolver only asks who is viewing; the owner needs no loader.
        self.owner_info = SimpleNamespace(context=SimpleNamespace(user=self.user))
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

    async def test_spotting_trends_defaults_to_last_7_days(self):
        trends = await UserScalar.spotting_trends.base_resolver(
            self.user, self.owner_info, start=None, end=None
        )
        self.assertIsNotNone(trends)
        self.assertGreater(len(trends), 0)
        self.assertEqual(len(trends), 366)

    async def test_spotting_trends_with_explicit_range(self):
        today = date.today()
        start = today - timedelta(days=5)
        end = today
        trends = await UserScalar.spotting_trends.base_resolver(
            self.user, self.owner_info, start=Some(start), end=Some(end)
        )
        self.assertIsNotNone(trends)
        self.assertEqual(len(trends), 6)

    async def test_spotting_trends_with_partial_start_only(self):
        today = date.today()
        start = today - timedelta(days=15)
        trends = await UserScalar.spotting_trends.base_resolver(
            self.user, self.owner_info, start=Some(start), end=None
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
                file=f"test_conn_photo_{i}.jpg",
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
                file=f"test_page_photo_{i}.jpg",
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


class MediaByIdQueryTests(TestCase):
    """`media(id:)` looks up one photo by the Relay id the `medias` nodes expose.

    It resolves through the same `MediaType` node path as the connection, so it
    must agree with `medias` about which rows exist.
    """

    QUERY = """
        query ($id: ID!) {
            media(id: $id) {
                id
                createdDate
                width
                height
                file { url }
                uploader { nickname }
            }
        }
    """

    def setUp(self):
        self.user = User.objects.create(
            firebase_id="media-by-id-uid", nickname="PhotoNick"
        )

    async def _make_media(self, name: str) -> Media:
        return await Media.objects.acreate(
            uploader=self.user,
            file=f"{name}.jpeg",
            width=3000,
            height=4000,
        )

    async def _feed_ids(self) -> list[str]:
        """Ids as `medias` exposes them, newest first."""
        result = await execute_graphql_async(
            "{ medias(first: 50, order: {created: DESC}) { edges { node { id } } } }"
        )
        self.assertIsNone(result.errors)
        return [edge["node"]["id"] for edge in result.data["medias"]["edges"]]

    async def test_found_by_the_id_the_feed_exposes(self):
        media = await self._make_media("found")
        # Relay global id (base64 "MediaType:<uuid>"), not the raw database id.
        relay_id = str(GlobalID("MediaType", str(media.id)))
        self.assertEqual((await self._feed_ids())[0], relay_id)
        self.assertNotEqual(relay_id, str(media.id))

        result = await execute_graphql_async(self.QUERY, {"id": relay_id})

        self.assertIsNone(result.errors)
        self.assertEqual(
            result.data["media"],
            {
                "id": relay_id,
                "createdDate": media.created.date().isoformat(),
                "width": 3000,
                "height": 4000,
                "file": {"url": "https://i.imgur.com/found.jpeg"},
                "uploader": {"nickname": "PhotoNick"},
            },
        )

    async def test_unknown_id_is_null_not_an_error(self):
        result = await execute_graphql_async(
            self.QUERY, {"id": str(GlobalID("MediaType", str(uuid4())))}
        )

        self.assertIsNone(result.errors)
        self.assertIsNone(result.data["media"])

    async def test_unusable_ids_are_null_not_an_error(self):
        media = await self._make_media("unusable")
        bad_ids = {
            "empty": "",
            "not a global id": "not-a-global-id",
            "raw database id": str(media.id),
            "other node type": str(GlobalID("UserScalar", str(media.id))),
            "pk is not a uuid": str(GlobalID("MediaType", "42")),
        }

        for label, bad_id in bad_ids.items():
            with self.subTest(label):
                result = await execute_graphql_async(self.QUERY, {"id": bad_id})

                self.assertIsNone(result.errors)
                self.assertIsNone(result.data["media"])

    async def test_agrees_with_the_feed_about_which_rows_exist(self):
        for name in ("a", "b", "c"):
            await self._make_media(name)
        # Legacy rows with no imgur file ('' or NULL) cannot be a non-null `file`, so
        # they are in neither the feed nor here.
        fileless = [
            await Media.objects.acreate(uploader=self.user, width=1, height=1),
            await Media.objects.acreate(uploader=self.user, file="", width=1, height=1),
        ]
        feed_ids = await self._feed_ids()
        self.assertEqual(len(feed_ids), 3)

        for feed_id in feed_ids:
            with self.subTest(feed_id):
                result = await execute_graphql_async(
                    "query ($id: ID!) { media(id: $id) { id } }", {"id": feed_id}
                )

                self.assertIsNone(result.errors)
                self.assertEqual(result.data["media"], {"id": feed_id})

        for media in fileless:
            with self.subTest(file=media.file.name):
                result = await execute_graphql_async(
                    self.QUERY, {"id": str(GlobalID("MediaType", str(media.id)))}
                )

                self.assertIsNone(result.errors)
                self.assertIsNone(result.data["media"])

    async def test_the_feed_pages_past_a_row_with_no_file(self):
        # One such row used to fail every page that contained it ("Cannot return null
        # for non-nullable field MediaType.file"), so the gallery stopped there.
        for name in ("a", "b"):
            await self._make_media(name)
        await Media.objects.acreate(uploader=self.user, file="", width=1, height=1)
        for name in ("c", "d", "e"):
            await self._make_media(name)

        query = """
            query ($after: String) {
                medias(first: 2, after: $after, order: {created: DESC}) {
                    totalCount
                    pageInfo { hasNextPage endCursor }
                    edges { node { id file { url } } }
                }
                mediasGroupByPeriod(type: YEAR) { count }
            }
        """
        seen, after = [], None
        while True:
            result = await execute_graphql_async(query, {"after": after})
            self.assertIsNone(result.errors)
            page = result.data["medias"]
            seen += [edge["node"]["id"] for edge in page["edges"]]
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]

        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)
        self.assertEqual(page["totalCount"], 5)
        # The year slider counts the same rows the feed lists.
        self.assertEqual(sum(g["count"] for g in result.data["mediasGroupByPeriod"]), 5)

    async def test_the_year_slider_and_its_photos_skip_rows_with_a_null_file(self):
        # `~Q(file="")` keeps NULL (NOT (file = '' AND file IS NOT NULL)), so the
        # slider counted rows the feed hides.
        shown = await self._make_media("shown")
        # Saving through the ORM stores '' for an empty file, so NULL needs an update.
        null_file = await Media.objects.acreate(uploader=self.user, width=1, height=1)
        await Media.objects.filter(pk=null_file.pk).aupdate(file=None)
        await Media.objects.acreate(uploader=self.user, file="", width=1, height=1)

        result = await execute_graphql_async(
            "{ mediasGroupByPeriod(type: YEAR) { count medias { id } } }"
        )

        self.assertIsNone(result.errors)
        (period,) = result.data["mediasGroupByPeriod"]
        self.assertEqual(period["count"], 1)
        self.assertEqual([m["id"] for m in period["medias"]], [str(shown.id)])

    async def test_a_media_type_visibility_rule_hides_the_row_from_both(self):
        hidden = await self._make_media("hidden")
        shown = await self._make_media("shown")
        hidden_id = str(GlobalID("MediaType", str(hidden.id)))
        shown_id = str(GlobalID("MediaType", str(shown.id)))

        def hide(cls, queryset, info, **kwargs):
            return queryset.exclude(pk=hidden.pk)

        with patch.object(MediaType, "get_queryset", classmethod(hide)):
            feed_ids = await self._feed_ids()
            hidden_result = await execute_graphql_async(self.QUERY, {"id": hidden_id})
            shown_result = await execute_graphql_async(self.QUERY, {"id": shown_id})

        self.assertEqual(feed_ids, [shown_id])
        self.assertIsNone(hidden_result.errors)
        self.assertIsNone(hidden_result.data["media"])
        self.assertEqual(shown_result.data["media"]["id"], shown_id)


class MediaCreatedDateQueryTests(TestCase):
    """`createdDate` reads `created`, which the optimizer must load with the page."""

    def setUp(self):
        self.user = User.objects.create(
            firebase_id="created-date-uid", nickname="DateNick"
        )

    def _page_queries(self, photos: int, fields: str) -> int:
        Media.objects.all().delete()
        for i in range(photos):
            Media.objects.create(
                uploader=self.user, file=f"date_{i}.jpeg", width=1, height=1
            )

        with CaptureQueriesContext(connection) as queries:
            result = execute_graphql(
                f"{{ medias(first: 24, order: {{created: DESC}}) {{"
                f" edges {{ node {{ {fields} }} }} }} }}"
            )

        self.assertIsNone(result.errors)
        self.assertEqual(len(result.data["medias"]["edges"]), photos)
        return len(queries)

    def test_a_page_costs_the_same_with_or_without_created_date(self):
        # It used to cost one more query per photo (25 for a page of 24).
        without = self._page_queries(3, "id width")
        self.assertEqual(self._page_queries(3, "id width createdDate"), without)
        self.assertEqual(self._page_queries(6, "id width createdDate"), without)

    def test_created_date_is_still_the_day_the_photo_was_created(self):
        media = Media.objects.create(
            uploader=self.user, file="day.jpeg", width=1, height=1
        )

        result = execute_graphql(
            "{ medias(first: 1) { edges { node { createdDate } } } }"
        )

        self.assertIsNone(result.errors)
        self.assertEqual(
            result.data["medias"]["edges"],
            [{"node": {"createdDate": media.created.date().isoformat()}}],
        )


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

    def _create_temporary_media(
        self,
        metadata,
        filename,
        upload_type=TemporaryMediaType.SPOTTING_EVENT,
    ):
        # Creating a TemporaryMedia fires the post_save receiver, which would
        # hit the real broker — patch out both dispatch calls.
        with patch(SIGNAL_APPLY_ASYNC), patch(SIGNAL_NSFW_APPLY_ASYNC):
            return TemporaryMedia.objects.create(
                uploader=self.user,
                file=f"temporary_media/{filename}",
                upload_type=upload_type,
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
            self.mock_webhook = mock_webhook
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

    def test_discord_upload_never_carries_gps(self):
        temp_media = self._create_temporary_media(
            metadata={
                "mime_type": "image/jpeg",
                "spotting_event_id": self.event.id,
                "file_name": "photo.jpg",
            },
            filename="photo.jpg",
        )

        # The staged file predates the upload-time strip and still holds GPS.
        self._run_convert_task(
            temp_media,
            content=jpeg_with_gps(),
            attachment={"id": "discord-attachment-3", "filename": "photo.jpg"},
        )

        sent = self.mock_webhook.return_value.add_file.call_args.kwargs["file"]
        exif = Image.open(io.BytesIO(sent)).getexif()
        self.assertNotIn(ExifTags.Base.GPSInfo, exif)
        self.assertEqual(exif[ExifTags.Base.Make], "TestMake")
        self.assertEqual(exif[ExifTags.Base.DateTime], "2026:10:21 08:30:00")

    def test_calendar_incident_photo_gets_the_parsed_exif_capture_time(self):
        incident = CalendarIncident.objects.create(
            title="Photo incident",
            brief="brief",
            severity="MINOR",
            start_datetime=now(),
        )
        # The raw EXIF "2026:10:21 08:30:00" is not a valid DateTimeField value, and
        # a bad one used to fail after the Media row was already created.
        for label, exif_date, expected in (
            ("valid", "2026:10:21 08:30:00", datetime(2026, 10, 21, 8, 30)),
            ("garbage", "not a date", None),
            ("missing", None, None),
        ):
            with self.subTest(label):
                CalendarIncidentMedia.objects.all().delete()
                Media.objects.filter(uploader=self.user).delete()
                exif = Image.Exif()
                if exif_date:
                    exif[ExifTags.Base.DateTime] = exif_date
                    exif[ExifTags.Base.Make] = "TestMake"  # a non-empty EXIF block
                temp_media = self._create_temporary_media(
                    metadata={
                        "mime_type": "image/jpeg",
                        "calendar_incident_id": incident.id,
                        "file_name": "photo.jpg",
                    },
                    filename="photo.jpg",
                    upload_type=TemporaryMediaType.INCIDENT_CALENDAR_INCIDENT,
                )

                self._run_convert_task(
                    temp_media,
                    content=_jpeg(exif),
                    attachment={"id": "discord-attachment-4", "filename": "photo.jpg"},
                )

                media = Media.objects.get(uploader=self.user)
                incident_media = CalendarIncidentMedia.objects.get(
                    calendar_incident=incident
                )
                self.assertEqual(incident_media.media_id, media.id)
                self.assertEqual(incident_media.timestamp, expected)
                temp_media.refresh_from_db()
                self.assertEqual(temp_media.status, TemporaryMediaStatus.TO_DELETE)
                self.assertEqual(temp_media.fail_count, 0)


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

        same_hour_multi = (
            reports.annotate(hour=TruncHour("created"))
            .values("line_id", "hour")
            .annotate(distinct_statuses=Count("status", distinct=True))
            .filter(distinct_statuses__gte=2)
        )
        self.assertGreaterEqual(same_hour_multi.count(), 1)

        total_reports = reports.count()
        with_station = reports.filter(stations__isnull=False).distinct().count()
        self.assertGreaterEqual(with_station, total_reports // 2)
        self.assertTrue(reports.filter(stations__isnull=True).exists())

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

    def test_same_hour_slots_guarantee_distinct_statuses(self):
        import random

        from common.management.commands.seed_demo_data import (
            SAME_HOUR_HOURS,
            SAME_HOUR_LINE_COUNT,
            SEED,
            Command,
        )

        command = Command()
        command.rng = random.Random(SEED)
        slots = command._same_hour_slots(
            list(Line.objects.all()),
            [status.value for status in PassengerStatus],
            now(),
            24 * 60,
            budget=10_000,
        )

        by_group: dict[tuple[int, int], set[str]] = {}
        for line, status, offset in slots:
            self.assertLessEqual(offset, SAME_HOUR_HOURS)
            by_group.setdefault((line.id, offset), set()).add(status)

        multi_status_groups = [g for g, s in by_group.items() if len(s) >= 2]
        self.assertGreaterEqual(len(multi_status_groups), SAME_HOUR_LINE_COUNT)

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


class StripGpsTests(SimpleTestCase):
    """`strip_gps` removes only the GPS IFD and leaves the rest byte-identical."""

    @staticmethod
    def _pixels(jpeg: bytes) -> bytes:
        return Image.open(io.BytesIO(jpeg)).convert("RGB").tobytes()

    @staticmethod
    def _exif_segment(jpeg: bytes) -> tuple[int, int]:
        start = jpeg.index(b"\xff\xe1")
        (length,) = struct.unpack(">H", jpeg[start + 2 : start + 4])
        return start, start + 2 + length

    def test_removes_gps_and_keeps_every_other_tag(self):
        for after_gps in (False, True):
            with self.subTest(after_gps=after_gps):
                source = jpeg_with_gps(after_gps=after_gps)
                latitude = struct.pack("<6I", 3, 1, 6, 1, 17, 1)
                self.assertIn(latitude, source)

                out = strip_gps(source)

                self.assertNotIn(latitude, out)
                exif = Image.open(io.BytesIO(out)).getexif()
                self.assertNotIn(ExifTags.Base.GPSInfo, exif)
                self.assertEqual(exif.get_ifd(ExifTags.IFD.GPSInfo), {})
                self.assertEqual(exif[ExifTags.Base.Make], "TestMake")
                self.assertEqual(exif[ExifTags.Base.Model], "TestModel")
                self.assertEqual(exif[ExifTags.Base.Orientation], 6)
                self.assertEqual(exif[ExifTags.Base.DateTime], "2026:10:21 08:30:00")
                self.assertEqual(
                    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal],
                    "2026:10:21 08:30:01",
                )
                if after_gps:
                    self.assertEqual(exif[0xC4A5], PRINT_IM)

    def test_edit_is_lossless(self):
        source = jpeg_with_gps()
        out = strip_gps(source)

        start, end = self._exif_segment(source)
        self.assertEqual(len(out), len(source))
        self.assertEqual(out[:start], source[:start])
        self.assertEqual(out[end:], source[end:])
        self.assertEqual(self._pixels(out), self._pixels(source))

    def test_handles_both_byte_orders(self):
        for order in ("<", ">"):
            with self.subTest(order=order):
                tiff, latitude = _tiff_with_gps(order)
                source = _with_exif_segment(_jpeg(), tiff)

                out = strip_gps(source)

                self.assertEqual(len(out), len(source))
                self.assertIn(latitude, source)
                self.assertNotIn(latitude, out)
                exif = Image.open(io.BytesIO(out)).getexif()
                self.assertEqual(sorted(exif), [0x0112, 0xC4A5])
                self.assertEqual(exif[0x0112], 6)
                self.assertEqual(exif[0xC4A5], b"PIM\x00")

    def test_leaves_files_with_nothing_to_strip_untouched(self):
        png = io.BytesIO()
        Image.new("RGB", (4, 4)).save(png, format="PNG")
        for label, data in {
            "exif without gps": jpeg_with_gps(gps=False),
            "jpeg without exif": _jpeg(),
            "png": png.getvalue(),
            "video": b"\x00\x00\x00\x18ftypmp42 not a real video",
            "empty": b"",
        }.items():
            with self.subTest(label):
                self.assertIs(strip_gps(data), data)

    def test_is_heif_recognises_heic_by_its_ftyp_brand(self):
        for brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heif"):
            with self.subTest(brand):
                self.assertTrue(is_heif(HEIC_STUB.replace(b"heic", brand)))

        for label, data in {
            "mp4": b"\x00\x00\x00\x18ftypmp42 not a real video",
            "jpeg": jpeg_with_gps(),
            "short": b"\x00\x00\x00\x18ftyp",
            "empty": b"",
        }.items():
            with self.subTest(label):
                self.assertFalse(is_heif(data))

    def test_drops_an_exif_segment_it_cannot_read(self):
        # With no way to show it holds no position, the whole segment goes.
        plain = _jpeg()
        for label, tiff in {
            "ifd0 runs past the block": b"II*\x00\x08\x00\x00\x00\xff\xff",
            "not a tiff block": b"garbage!",
            "gps pointer outside the block": _tiff_with_gps("<", 0x7FFFFFF0)[0],
        }.items():
            with self.subTest(label), self.assertLogs("common.exif", "WARNING"):
                self.assertEqual(strip_gps(_with_exif_segment(plain, tiff)), plain)

    @staticmethod
    def _crafted_ifd0(n_other: int, n_gps: int) -> bytes:
        """A TIFF block whose IFD0 holds `n_other` plain tags, then `n_gps` GPS pointers."""
        count = n_other + n_gps
        tail = 8 + 2 + 12 * count + 4  # an empty IFD for every pointer to land on
        entries = (
            b"".join(
                struct.pack("<HHII", 0x0100 + i % 200, 3, 1, 1) for i in range(n_other)
            )
            + struct.pack("<HHII", 0x8825, 4, 1, tail) * n_gps
        )
        header = b"II" + struct.pack("<HI", 42, 8) + struct.pack("<H", count)
        return header + entries + bytes(4 + 16)

    def test_drops_an_exif_segment_with_many_gps_pointers_without_scanning_it_forever(
        self,
    ):
        # Each removal used to rescan IFD0 (6 s of CPU for 2,500 + 2,500 entries,
        # on the event loop), so the loop is capped and the segment fails closed.
        plain = _jpeg()
        crafted = _with_exif_segment(plain, self._crafted_ifd0(2000, 2000))

        started = time.monotonic()
        with self.assertLogs("common.exif", "WARNING"):
            out = strip_gps(crafted)

        self.assertEqual(out, plain)
        self.assertLess(time.monotonic() - started, 1)

    def test_strips_a_few_repeated_gps_pointers(self):
        out = strip_gps(_with_exif_segment(_jpeg(), self._crafted_ifd0(3, 3)))

        self.assertEqual(
            sorted(Image.open(io.BytesIO(out)).getexif()), [0x100, 0x101, 0x102]
        )


class GenericUploadStripsGpsTests(TestCase):
    """POST /upload/ stores the photo without its GPS, whichever client sent it."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="upload-gps-uid", nickname="Snap")
        vehicle_type = VehicleType.objects.create(
            internal_name="UPLOAD_GPS_VT", display_name="Upload GPS Vehicle Type"
        )
        vehicle = Vehicle.objects.create(
            identification_no="Set 901",
            vehicle_type=vehicle_type,
            status=SpottingVehicleStatus.IN_SERVICE,
        )
        self.event = Event.objects.create(
            reporter=self.user,
            vehicle=vehicle,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date.today(),
        )

    def _post(self, content: bytes, name: str = "IMG_0001.jpg"):
        """POST `content` as the reporter: the response and what reached storage."""
        stored = []

        def save(storage, name, file):
            file.seek(0)
            stored.append(file.read())
            return name

        request = APIRequestFactory().post(
            "/upload/",
            {
                "upload_type": TemporaryMediaType.SPOTTING_EVENT,
                "related_id": str(self.event.id),
                "image": SimpleUploadedFile(name, content),
            },
            format="multipart",
        )
        with (
            patch("common.views.FirebaseUser") as firebase_user,
            patch(
                "storages.backends.s3boto3.S3Boto3Storage._save",
                autospec=True,
                side_effect=save,
            ),
            patch(SIGNAL_APPLY_ASYNC),
            patch(SIGNAL_NSFW_APPLY_ASYNC),
        ):
            firebase_user.return_value.get_current_user = AsyncMock(
                return_value=self.user
            )
            response = GenericUpload.as_view()(request)

        return response, stored

    def _upload(self, content: bytes, name: str = "IMG_0001.jpg") -> bytes:
        """POST `content` as the reporter and return the bytes handed to storage."""
        response, stored = self._post(content, name)

        self.assertEqual(response.status_code, 201)
        (content_stored,) = stored
        return content_stored

    def test_jpeg_is_stored_without_gps_but_with_its_capture_data(self):
        source = jpeg_with_gps()

        stored = self._upload(source)

        self.assertTrue(TemporaryMedia.objects.filter(uploader=self.user).exists())
        exif = Image.open(io.BytesIO(stored)).getexif()
        self.assertNotIn(ExifTags.Base.GPSInfo, exif)
        self.assertEqual(exif[ExifTags.Base.Make], "TestMake")
        self.assertEqual(exif[ExifTags.Base.Model], "TestModel")
        self.assertEqual(exif[ExifTags.Base.DateTime], "2026:10:21 08:30:00")
        self.assertEqual(
            Image.open(io.BytesIO(stored)).convert("RGB").tobytes(),
            Image.open(io.BytesIO(source)).convert("RGB").tobytes(),
        )

    def test_other_uploads_are_stored_as_received(self):
        for name, content in {
            "clip.mp4": b"\x00\x00\x00\x18ftypmp42 not a real video",
            "no_gps.jpg": jpeg_with_gps(gps=False),
        }.items():
            with self.subTest(name):
                self.assertEqual(self._upload(content, name=name), content)

    def test_heic_is_refused_and_nothing_is_stored(self):
        # strip_gps cannot edit HEIC, so it would keep its GPS all the way to Discord.
        response, stored = self._post(HEIC_STUB, name="IMG_0001.heic")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(stored, [])
        self.assertFalse(TemporaryMedia.objects.filter(uploader=self.user).exists())
