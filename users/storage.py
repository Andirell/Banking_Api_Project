import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateMediaStorage(FileSystemStorage):
    """Storage for files that must never be reachable by URL (e.g. KYC documents).

    The location is read from settings on each access, so tests can point it at
    a temporary directory. Serve files only through a view that checks access.
    """

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
