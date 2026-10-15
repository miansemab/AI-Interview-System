"""Ephemeral, local speaker comparison for interview audio samples."""

from __future__ import annotations

import io
import math
import wave
from functools import lru_cache

import numpy as np
import torch
from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from speechbrain.inference.speaker import SpeakerRecognition


SAMPLE_RATE = 16_000
MIN_SAMPLE_SECONDS = 4
MAX_SAMPLE_SECONDS = 15
MAX_AUDIO_BYTES = 1_000_000


class BoundedSpeakerAudioUploadHandler(FileUploadHandler):
    """Stop oversized speaker audio while Django is parsing multipart input."""

    chunk_size = 64 * 1024

    def new_file(self, field_name, *args, **kwargs):
        super().new_file(field_name, *args, **kwargs)
        self.is_speaker_audio = field_name in {
            "speaker_audio",
            "reference_sample_1",
            "reference_sample_2",
        }

    def receive_data_chunk(self, raw_data, start):
        if self.is_speaker_audio and start + len(raw_data) > MAX_AUDIO_BYTES:
            self.request.speaker_audio_too_large = True
            raise StopUpload(connection_reset=False)
        return raw_data

    def file_complete(self, file_size):
        return None


def limit_speaker_audio_upload(request):
    """Install the streaming limit before any middleware parses POST or FILES."""
    if (
        request._read_started
        or hasattr(request, "_post")
        or hasattr(request, "_files")
    ):
        raise RuntimeError("Speaker audio upload limits must be installed before request parsing.")
    request.upload_handlers.insert(0, BoundedSpeakerAudioUploadHandler(request))


class AudioSampleError(ValueError):
    """The recording is unsuitable for a reliable verification attempt."""


@lru_cache(maxsize=1)
def get_speaker_model():
    """Load the local CPU model lazily, only after voice consent."""
    model = SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        run_opts={"device": "cpu"},
    )
    model.eval()
    return model


def decode_wav(uploaded_file) -> np.ndarray:
    """Decode bounded mono PCM WAV uploaded from the same-origin browser."""
    if uploaded_file.size > MAX_AUDIO_BYTES:
        raise AudioSampleError("The recording is too large. Please record again.")

    try:
        payload = uploaded_file.read(MAX_AUDIO_BYTES + 1)
        if len(payload) > MAX_AUDIO_BYTES:
            raise AudioSampleError("The recording is too large. Please record again.")
        with wave.open(io.BytesIO(payload), "rb") as wav_file:
            if (
                wav_file.getnchannels() != 1
                or wav_file.getsampwidth() != 2
                or wav_file.getframerate() != SAMPLE_RATE
                or wav_file.getcomptype() != "NONE"
            ):
                raise AudioSampleError("Use a mono PCM WAV recording at 16 kHz.")
            frame_count = wav_file.getnframes()
            duration = frame_count / SAMPLE_RATE
            if duration < MIN_SAMPLE_SECONDS or duration > MAX_SAMPLE_SECONDS:
                raise AudioSampleError(
                    f"Record between {MIN_SAMPLE_SECONDS} and {MAX_SAMPLE_SECONDS} seconds of speech."
                )
            audio = np.frombuffer(wav_file.readframes(frame_count), dtype="<i2")
    except (wave.Error, EOFError, OSError) as error:
        raise AudioSampleError("The audio file is invalid. Please record again.") from error

    if audio.size == 0:
        raise AudioSampleError("The recording is empty. Please record again.")
    if audio.size != frame_count:
        raise AudioSampleError("The recording is incomplete. Please record again.")

    normalized = audio.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(np.square(normalized))))
    clipped_ratio = float(np.mean(np.abs(audio) >= 32760))
    if not math.isfinite(rms) or rms < 0.006:
        raise AudioSampleError("The recording is too quiet to verify. Please record again.")
    if clipped_ratio > 0.02:
        raise AudioSampleError("The recording is distorted. Please record again.")

    # Reject obvious stationary broadband noise as inconclusive. This is only
    # an audio-quality gate; it is never used to compare speaker identity.
    frame_size = 320  # 20 ms at the required 16 kHz sample rate
    usable_length = (normalized.size // frame_size) * frame_size
    frames = normalized[:usable_length].reshape(-1, frame_size)
    window = np.hanning(frame_size).astype(np.float32)
    power = np.square(np.abs(np.fft.rfft(frames * window, axis=1))) + 1e-12
    spectral_flatness = np.exp(np.mean(np.log(power), axis=1)) / np.mean(power, axis=1)
    if float(np.mean(spectral_flatness)) > 0.40:
        raise AudioSampleError(
            "The recording sounds too noisy for a reliable check. Move somewhere quieter and retry."
        )

    return normalized


def embed_audio(audio: np.ndarray) -> np.ndarray:
    """Return a normalized ECAPA-TDNN speaker embedding for 16 kHz audio."""
    model = get_speaker_model()
    waveform = torch.from_numpy(audio.copy()).unsqueeze(0)
    with torch.inference_mode():
        embedding = model.encode_batch(waveform).detach().cpu().numpy().reshape(-1)
    norm = float(np.linalg.norm(embedding))
    if not math.isfinite(norm) or norm == 0:
        raise AudioSampleError("The voice sample was inconclusive. Please retry.")
    return (embedding / norm).astype(np.float32)


def enroll_samples(uploaded_samples: list) -> list[float]:
    """Create a normalized profile centroid from two separate voice samples."""
    if len(uploaded_samples) != 2:
        raise AudioSampleError("Two separate reference samples are required.")
    embeddings = [embed_audio(decode_wav(sample)) for sample in uploaded_samples]
    score = float(np.dot(embeddings[0], embeddings[1]))
    if score < settings.SPEAKER_VERIFICATION_THRESHOLD:
        raise AudioSampleError(
            "The two reference samples did not match reliably. Please record both again."
        )
    centroid = np.mean(np.stack(embeddings), axis=0)
    centroid /= np.linalg.norm(centroid)
    return centroid.astype(np.float32).tolist()


def compare_sample(uploaded_file, reference_embedding: list[float]) -> float:
    """Compare one captured voice sample to its ephemeral enrolled profile."""
    embedding = embed_audio(decode_wav(uploaded_file))
    reference = np.asarray(reference_embedding, dtype=np.float32)
    if embedding.shape != reference.shape:
        raise AudioSampleError("The voice check was inconclusive. Please retry.")
    score = float(np.dot(embedding, reference))
    if not math.isfinite(score):
        raise AudioSampleError("The voice check was inconclusive. Please retry.")
    return score
