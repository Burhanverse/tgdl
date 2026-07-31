from __future__ import annotations

from .audio import convert_audio_async
from .image import convert_image_to_png_async
from .telegram import (
    _conversion_choices,
    _conversion_events,
    _conversion_ids,
    _converted_files,
    handle_conversion_choice,
)
from .video import convert_video_async, split_video_async

CONVERSION_EXT = {
    ".ts", ".flv", ".avi", ".wmv", ".asf", ".mkv", ".m4v",
    ".webm", ".mov", ".3gp", ".mpeg", ".mpg", ".f4v", ".vob"
}
AUDIO_CONVERSION_EXT = {".wav", ".flac", ".ogg", ".opus", ".aiff", ".aac"}

async def convert_media_async(input_path, output_path) -> bool:
    """Backward compatible video conversion entry point utilizing PyAV."""
    return await convert_video_async(input_path, output_path)

__all__ = [
    "AUDIO_CONVERSION_EXT",
    "CONVERSION_EXT",
    "_conversion_choices",
    "_conversion_events",
    "_conversion_ids",
    "_converted_files",
    "convert_audio_async",
    "convert_image_to_png_async",
    "convert_media_async",
    "handle_conversion_choice",
    "split_video_async",
]


