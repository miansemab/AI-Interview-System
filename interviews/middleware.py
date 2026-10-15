"""Install bounded speaker-audio upload handling before CSRF parses POST data."""

from django.urls import Resolver404, resolve
from django.utils.deprecation import MiddlewareMixin

from .speaker_verification import limit_speaker_audio_upload


SPEAKER_AUDIO_POST_ROUTES = {
    "speaker_enrollment",
    "speaker_recheck",
    "submit_answer",
}


class SpeakerAudioUploadLimitMiddleware(MiddlewareMixin):
    """Configure streaming file limits before Django's CSRF middleware reads POST."""

    def process_request(self, request):
        if request.method != "POST":
            return None
        try:
            route = resolve(request.path_info)
        except Resolver404:
            return None
        if route.url_name in SPEAKER_AUDIO_POST_ROUTES:
            limit_speaker_audio_upload(request)
        return None
