from django.conf import settings
from django.core.management.base import BaseCommand
from imgurpython import ImgurClient


class Command(BaseCommand):
    """Before using this command, the application need to be registered
    by an imgur user. See https://api.imgur.com/oauth2"""

    def handle(self, *args, **options):
        client = ImgurClient(
            client_id=settings.IMGUR_CONSUMER_ID,
            client_secret=settings.IMGUR_CONSUMER_SECRET,
        )

        url = client.get_auth_url("pin")
        print(("Url:", url))
        print(
            "Please visit this website and press the 'Allow' button, then paste the PIN code you receive from Imgur."
        )
        # pin = raw_input().strip()
        pin = input().strip()

        # This will fail if the user didn't visit the above URL and hit 'Allow'
        credentials = client.authorize(pin, "pin")

        print(("IMGUR_ACCESS_TOKEN = '%s'" % credentials["access_token"]))
        print(("IMGUR_ACCESS_TOKEN_REFRESH = '%s'" % credentials["refresh_token"]))
