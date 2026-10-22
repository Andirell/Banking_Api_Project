import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateMediaStorage(FileSystemStorage):
    # Where KYC documents (ID cards, proof of address) are saved.
    # These files have NO public URL. The only way to get one is the download
    # view in users/views.py, which checks it's the owner or staff asking.

    # We read the folder from settings every time (instead of once at start-up)
    # so the tests can point it at a temporary folder.
    @property
    def base_location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Private files have no public URL; use the KYC document download endpoint.")


def private_kyc_storage():
    return PrivateMediaStorage()
