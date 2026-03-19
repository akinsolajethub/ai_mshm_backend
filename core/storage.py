"""
core/storage.py
────────────────
Centralised Cloudinary storage classes.
Import these anywhere you need file uploads — avatars, rPPG, documents, etc.
Never hardcode cloudinary paths in individual apps.
"""
from cloudinary_storage.storage import MediaCloudinaryStorage


class AvatarStorage(MediaCloudinaryStorage):
    """User profile pictures → cloudinary/avatars/"""
    def _get_folder(self):
        return "avatars"


class RppgStorage(MediaCloudinaryStorage):
    """rPPG video/signal files → cloudinary/rppg/"""
    def _get_folder(self):
        return "rppg"


class DocumentStorage(MediaCloudinaryStorage):
    """General documents (reports, exports) → cloudinary/documents/"""
    def _get_folder(self):
        return "documents"