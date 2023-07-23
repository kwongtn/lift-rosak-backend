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

from common.enums import TemporaryMediaType
from common.models import TemporaryMedia
from common.utils import FirebaseUser
from spotting.models import Event

s3 = boto3.resource(
    "s3",
    region_name=settings.AWS_S3_REGION_NAME,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    endpoint_url=settings.AWS_S3_ENDPOINT_URL,
)


class GenericUpload(APIView):
    @transaction.atomic
    @async_to_sync
    async def post(self, request: Request | HttpRequest, format=None):
        """
        Possible values:
            - upload_type
            - image
            - spotting_event_id
            - calendar_incident_id
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
            spotting_event_id = data["spotting_event_id"]
            metadata["spotting_event_id"] = spotting_event_id
            event: Event = await Event.objects.aget(id=spotting_event_id)

            if user.id != event.reporter_id:
                return Response(status=status.HTTP_403_FORBIDDEN)

        elif upload_type == TemporaryMediaType.INCIDENT_CALENDAR_INCIDENT:
            metadata["calendar_incident_id"] = data["calendar_incident_id"]

        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # Upload to temporary media bucket
        await TemporaryMedia.objects.acreate(
            uploader_id=user.id,
            file=File(file=file, name=extension),
            upload_type=upload_type,
            metadata=metadata,
        )

        # Return valid response
        return Response(None, status=status.HTTP_201_CREATED)
