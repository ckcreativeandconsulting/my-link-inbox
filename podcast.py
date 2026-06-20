"""Podcast detection, audio download, and transcription.

Steps 1-3 of podcast support: detect podcast URLs, download audio with
yt-dlp, and transcribe locally with faster-whisper.

Dependencies:
    pip install yt-dlp faster-whisper
    System: ffmpeg must be installed and on PATH (used by yt-dlp for audio extraction)

Environment variables:
    WHISPER_MODEL  - model size: tiny | base | small | medium | large  (default: base)
"""

import os
import tempfile
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

_PODCAST_DOMAINS = frozenset({
    "podcasts.apple.com",
    "open.spotify.com",
    "anchor.fm",
    "buzzsprout.com",
    "feeds.buzzsprout.com",
    "podbean.com",
    "transistor.fm",
    "simplecast.com",
    "pinecast.com",
    "spreaker.com",
    "soundcloud.com",
    "overcast.fm",
    "pca.st",                # Pocket Casts short links
    "pocketcasts.com",
    "listen.pocketcasts.com",
    "podcastaddict.com",
    "youtube.com",           # YouTube (yt-dlp handles perfectly)
    "youtu.be",              # YouTube short links
    "music.youtube.com",
    "podcasts.youtube.com",
    "iheart.com",
    "stitcher.com",
    "radiopublic.com",
    "castbox.fm",
    "player.fm",
    "podchaser.com",
    "omny.fm",
    "acast.com",
    "megaphone.fm",
    "art19.com",
    "audioboom.com",
})

_AUDIO_EXTS = frozenset({".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac", ".opus"})
_RSS_EXTS   = frozenset({".xml", ".rss"})


def is_podcast_url(url: str) -> bool:
    """Return True if the URL looks like a podcast episode, audio file, or RSS feed."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower().lstrip("www.")
    path   = parsed.path.lower()
    suffix = Path(path).suffix

    if suffix in _AUDIO_EXTS:
        return True
    if suffix in _RSS_EXTS or "/feed/" in path or path.endswith("/rss") or path.endswith("/feed"):
        return True
    if domain in _PODCAST_DOMAINS or any(domain.endswith("." + d) for d in _PODCAST_DOMAINS):
        return True

    return False


# ---------------------------------------------------------------------------
# Model cache
# ---------------------------------------------------------------------------

_whisper_model = None


def _get_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper is not installed.\n"
            "Run: pip install faster-whisper\n"
            "Also required: ffmpeg on PATH (already installed per your setup)."
        )
    size = os.environ.get("WHISPER_MODEL", "base")
    print(f"  [whisper] Loading '{size}' model (first load downloads weights if needed)...")
    _whisper_model = WhisperModel(size, device="cpu", compute_type="int8")
    return _whisper_model


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_audio(url: str, dest_dir: str) -> tuple[Path | None, dict]:
    """Download best-quality audio from url into dest_dir via yt-dlp.

    Returns (mp3_path, metadata_dict). mp3_path is None on failure.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError(
            "yt-dlp is not installed.\n"
            "Run: pip install yt-dlp"
        )

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(Path(dest_dir) / "%(id)s.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    meta = {
        "title":    info.get("title"),
        "duration": info.get("duration"),  # seconds, may be None
        "uploader": info.get("uploader") or info.get("channel"),
    }

    mp3_files = list(Path(dest_dir).glob("*.mp3"))
    return (mp3_files[0] if mp3_files else None), meta


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def _transcribe(audio_path: Path) -> str:
    """Transcribe an audio file and return the full plain-text transcript."""
    model = _get_model()
    segments, _ = model.transcribe(str(audio_path), beam_size=5)
    return " ".join(seg.text.strip() for seg in segments)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_podcast(url: str) -> tuple[str | None, str | None, int | None]:
    """Download and transcribe a podcast URL.

    Returns:
        (transcript, episode_title, duration_mins)
        Any value may be None if that piece of info is unavailable or fails.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        print("  [podcast] Downloading audio...")
        try:
            audio_path, meta = _download_audio(url, tmpdir)
        except Exception as exc:
            raise RuntimeError(f"Audio download failed: {exc}") from exc

        if audio_path is None:
            return None, meta.get("title"), None

        duration_secs = meta.get("duration")
        duration_mins = int(duration_secs // 60) if duration_secs else None

        if duration_mins:
            print(f"  [podcast] Transcribing ~{duration_mins} min episode...")
        else:
            print("  [podcast] Transcribing...")

        try:
            transcript = _transcribe(audio_path)
        except Exception as exc:
            raise RuntimeError(f"Transcription failed: {exc}") from exc

        return transcript, meta.get("title"), duration_mins
