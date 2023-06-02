import base64
import logging
import os.path
from io import BytesIO, StringIO

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.files import File
from django.core.files.storage import Storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils.deconstruct import deconstructible
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientError
from PIL import Image

logger = logging.getLogger(__name__)


@deconstructible
class ImgurStorage(Storage):
    """
    A storage class providing access to resources in an Imgur album.
    """

    def __init__(self, location="/"):
        self.client = ImgurClient(
            client_id=settings.IMGUR_CONSUMER_ID,
            client_secret=settings.IMGUR_CONSUMER_SECRET,
            access_token=settings.IMGUR_ACCESS_TOKEN,
            refresh_token=settings.IMGUR_ACCESS_TOKEN_REFRESH,
        )
        logger.info("Logged in Imgur storage")

        self.account_info = self.client.get_account(settings.IMGUR_USERNAME)
        self.albums = self.client.get_account_albums(settings.IMGUR_USERNAME)
        self.location = location
        self.base_url = "https://api.imgur.com/3/account/{url}/".format(
            url=self.account_info.url
        )
        logger.debug(f"account_info: {self.account_info}")
        logger.debug(f"albums: {self.albums}")
        logger.debug(f"location: {self.location}")
        logger.debug(f"base_url: {self.base_url}")

    def _get_abs_path(self, name):
        return os.path.join(self.location, name)

    def _open(self, name, mode="rb"):
        name = name.split(".")[0]
        response = requests.get(f"https://i.imgur.com/{name}")

        return response

    def _save(self, name, content: InMemoryUploadedFile):
        name = self._get_abs_path(name)
        directory = os.path.dirname(name)

        image_b64 = ""
        with content.open() as stream:
            image = Image.open(stream)

            if image.mode in ("RGBA", "LA"):
                background = Image.new(image.mode[:-1], image.size, "#fff")
                background.paste(image, image.split()[-1])
                image = background

            image_io = BytesIO()
            image.save(image_io, format="JPEG", quality=100)

            image_b64 = base64.b64encode(image_io.getvalue())

        logger.info(f"albums: {[a.title for a in self.albums]}")
        logger.info(f"name: {name}")
        logger.info(f"directory: {directory}")
        logger.info(f"content: {content}")

        logger.debug(f"self.exists(directory): {self.exists(directory)}")

        if directory not in [album.title for album in self.albums]:
            logger.debug(f"Album {directory} does not exist, creating it")
            album = self.client.create_album({"title": directory})
            logger.debug(f"Creted album: {album}")

            self.albums = self.client.get_account_albums(settings.IMGUR_USERNAME)

        album = [a for a in self.albums if a.title == directory][0]
        response = self._client_upload_from_fd(
            image_b64,
            {
                "album": album.id,
                "name": name,
                "title": name,
            },
            False,
        )
        logger.info(f"Imgur response: {response}")

        return response["link"].split("/")[-1]

    def _client_upload_from_fd(self, b64: str, config=None, anon=True):
        """use a file descriptor to perform a make_request"""
        if not config:
            config = dict()

        data = {
            "image": b64,
            "type": "base64",
        }
        data.update(
            {
                meta: config[meta]
                for meta in set(self.client.allowed_image_fields).intersection(
                    list(config.keys())
                )
            }
        )
        return self.client.make_request("POST", "upload", data, anon)

    def delete(self, name):
        name = name.split(".")[0]
        logger.debug(f"Deleting {name}")

        res: bool = self.client.delete_image(name)

        if res:
            logger.debug(f"Image {name} deleted")

    def exists(self, name):
        name = name.split(".")[0]

        try:
            self.client.get_image(name)

        except ImgurClientError as e:
            logger.error(e)
            if e.status_code == 404:  # not found
                return False

            raise e
        except IndexError:
            return False
        else:
            return True
        return False

    def listdir(self, path):
        path = self._get_abs_path(path)
        response = self.client.get_image(path)
        directories = []
        files = []
        for entry in response.get("contents", []):
            if entry["is_dir"]:
                directories.append(os.path.basename(entry["path"]))
            else:
                files.append(os.path.basename(entry["path"]))
        return directories, files

    def size(self, name):
        name = name.split(".")[0]

        cache_key = f"django-imgur-size:{name}"
        size = cache.get(cache_key)

        if not size:
            size = self.client.get_image(name).size
            cache.set(cache_key, size)

        return size

    def url(self, path):
        return f"https://i.imgur.com/{path}"

    def get_available_name(self, name, max_length=None):
        """
        Returns a filename that's free on the target storage system, and
        available for new content to be written to.
        """
        # name = self._get_abs_path(name)
        # dir_name, file_name = os.path.split(name)
        # file_root, file_ext = os.path.splitext(file_name)
        ## If the filename already exists, add an underscore and a number (before
        ## the file extension, if one exists) to the filename until the generated
        ## filename doesn't exist.
        # count = itertools.count(1)
        # while self.exists(name):
        #    # file_ext includes the dot.
        #    name = os.path.join(dir_name, "%s_%s%s" % (file_root, count.next(), file_ext))

        return name


@deconstructible
class ImgurFile(File):
    def __init__(self, name, storage, mode):
        self._storage = storage
        self._mode = mode
        self._is_dirty = False
        self.file = StringIO()
        self.start_range = 0
        self._name = name

    @property
    def size(self):
        if not hasattr(self, "_size"):
            self._size = self._storage.size(self._name)
        return self._size

    def read(self, num_bytes=None):
        return requests.get(self._storage.url(self._name)).content

    def write(self, content):
        if "w" not in self._mode:
            raise AttributeError("File was opened for read-only access.")
        self.file = StringIO(content)
        self._is_dirty = True

    def close(self):
        # if self._is_dirty:
        #    self._storage.client.put_file(self._name, self.file.getvalue())
        self.file.close()
