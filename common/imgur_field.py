from django.conf import settings
from django.core.cache import cache
from django.db.models.fields.files import ImageField, ImageFieldFile
from imgurpython import ImgurClient as _ImgurClient
from imgurpython import client as imgurpython_client

imgurpython_client.API_URL = settings.IMGUR_PROXY_API_URL


class ImgurClient(_ImgurClient):
    def prepare_headers(self, force_anon=False):
        headers = super().prepare_headers(force_anon=force_anon)
        headers["Proxy-Authorization"] = settings.IMGUR_PROXY_AUTH_KEY

        return headers


client = ImgurClient(
    client_id=settings.IMGUR_CONSUMER_ID,
    client_secret=settings.IMGUR_CONSUMER_SECRET,
    access_token=settings.IMGUR_ACCESS_TOKEN,
    refresh_token=settings.IMGUR_ACCESS_TOKEN_REFRESH,
)


class ImgurImageFieldFile(ImageFieldFile):
    def _get_image_dimensions(self):
        if self.instance.width and self.instance.height:
            return self.instance.width, self.instance.height

        id = self.name.split(".")[0]

        # Do width & height cache
        cache_key = f"django-imgur-dimensions:{id}"
        dimensions = cache.get(cache_key)
        dimensions = None

        if not dimensions:
            res = client.get_image(f"{id}.json")
            dimensions = (res.width, res.height)
            cache.set(cache_key, dimensions)

            from common.tasks import add_width_height_to_media_task

            add_width_height_to_media_task.apply_async(
                kwargs={
                    "filename": self.name,
                    "width": res.width,
                    "height": res.height,
                }
            )

        return dimensions


class ImgurField(ImageField):
    attr_class = ImgurImageFieldFile

    def update_dimension_fields(self, instance, force=False, *args, **kwargs):
        pass
