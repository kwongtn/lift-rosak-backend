import boto3
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.http import HttpRequest
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.enums import TemporaryMediaStatus, TemporaryMediaType
from common.models import TemporaryMedia
from common.utils import FirebaseUser
from spotting.models import Event


def get_s3_resource():
    kwargs = {}
    if settings.AWS_S3_REGION_NAME:
        kwargs["region_name"] = settings.AWS_S3_REGION_NAME
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_S3_ENDPOINT_URL and not settings.AWS_S3_ENDPOINT_URL.startswith(
        "https://.compat.objectstorage"
    ):
        kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL

    return boto3.resource("s3", **kwargs)


class GenericUpload(APIView):
    @transaction.atomic
    @async_to_sync
    async def post(self, request: Request | HttpRequest, format=None):
        """
        Possible values:
            - upload_type
            - image
            - related_id
        """
        data = request.data.dict()
        extension = str(request.data.dict()["image"]).split(".")[-1]
        upload_type = data["upload_type"]
        file = data["image"].file

        if upload_type not in [i[0] for i in TemporaryMediaType.choices]:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        user = await FirebaseUser(request).get_current_user()
        if user is None:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        # Create metadata & some checks
        metadata = {}
        if upload_type == TemporaryMediaType.SPOTTING_EVENT:
            spotting_event_id = data["related_id"]
            metadata["spotting_event_id"] = spotting_event_id
            event: Event = await Event.objects.aget(id=spotting_event_id)

            if user.id != event.reporter_id:
                return Response(status=status.HTTP_403_FORBIDDEN)

        elif upload_type == TemporaryMediaType.INCIDENT_CALENDAR_INCIDENT:
            metadata["calendar_incident_id"] = data["related_id"]

        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # Upload to temporary media bucket
        await TemporaryMedia.objects.acreate(
            uploader_id=user.id,
            file=File(file=file, name=extension),
            upload_type=upload_type,
            metadata=metadata,
            status=TemporaryMediaStatus.PENDING,
        )

        # Return valid response
        return Response(None, status=status.HTTP_201_CREATED)
