from asgiref.sync import async_to_sync
from django.core.files.images import ImageFile
from django.db import transaction
from django.http import HttpRequest
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.models import Media
from common.utils import FirebaseUser
from spotting.models import EventMedia


class SpottingImageUpload(APIView):
    @transaction.atomic
    @async_to_sync
    async def post(self, request: Request | HttpRequest, format=None):
        user = await FirebaseUser(request).get_current_user()
        if user is None:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        media = await Media.objects.acreate(
            uploader_id=user.id,
            file=ImageFile(request.data.dict()["image"].file, "image"),
        )

        await EventMedia.objects.acreate(
            media_id=media.id,
            event_id=request.data.dict()["spotting_event_id"],
        )

        return Response(None, status=status.HTTP_201_CREATED)
