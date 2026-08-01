from __future__ import annotations

from pathlib import Path
import pytest

from app.utils.filetype import detect_extension, ensure_extension, needs_extension_fix


# Sample magic byte signatures for filetype detection
ZIP_BYTES = b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x00\x00\x00\x00" + b"\x00" * 50
MP4_BYTES = b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 50
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00\x60\x00\x60\x00\x00\xff\xd9"


def test_needs_extension_fix():
    """Verify needs_extension_fix returns True for generic/missing extensions and False for specific ones."""
    assert needs_extension_fix(Path("file.tmp")) is True
    assert needs_extension_fix(Path("file.bin")) is True
    assert needs_extension_fix(Path("file.part")) is True
    assert needs_extension_fix(Path("file.download")) is True
    assert needs_extension_fix(Path("file_without_extension")) is True

    assert needs_extension_fix(Path("video.cbz")) is False
    assert needs_extension_fix(Path("video.mp4")) is False
    assert needs_extension_fix(Path("archive.zip")) is False
    assert needs_extension_fix(Path("photo.jpg")) is False


def test_detect_extension(tmp_path: Path):
    """Verify detect_extension correctly identifies magic bytes for zip, mp4, and jpeg."""
    zip_file = tmp_path / "test_archive.tmp"
    zip_file.write_bytes(ZIP_BYTES)
    assert detect_extension(zip_file) == ".zip"

    mp4_file = tmp_path / "test_video.bin"
    mp4_file.write_bytes(MP4_BYTES)
    assert detect_extension(mp4_file) == ".mp4"

    jpg_file = tmp_path / "test_photo.part"
    jpg_file.write_bytes(JPEG_BYTES)
    assert detect_extension(jpg_file) == ".jpg"

    unknown_file = tmp_path / "unknown.tmp"
    unknown_file.write_bytes(b"random arbitrary bytes without known signature")
    assert detect_extension(unknown_file) is None


@pytest.mark.asyncio
async def test_ensure_extension_repairs_generic_file(tmp_path: Path):
    """Verify ensure_extension renames generic/missing extension files to detected extensions."""
    tmp_file = tmp_path / "sample.tmp"
    tmp_file.write_bytes(ZIP_BYTES)

    result_path = await ensure_extension(tmp_file)
    assert result_path == tmp_path / "sample.zip"
    assert result_path.exists()
    assert not tmp_file.exists()

    no_ext_file = tmp_path / "my_movie"
    no_ext_file.write_bytes(MP4_BYTES)

    result_movie = await ensure_extension(no_ext_file)
    assert result_movie == tmp_path / "my_movie.mp4"
    assert result_movie.exists()
    assert not no_ext_file.exists()


@pytest.mark.asyncio
async def test_ensure_extension_handles_filename_collisions(tmp_path: Path):
    """Verify ensure_extension appends numeric suffix when target filename already exists."""
    existing_zip = tmp_path / "sample.zip"
    existing_zip.write_bytes(b"existing file content")

    tmp_file = tmp_path / "sample.tmp"
    tmp_file.write_bytes(ZIP_BYTES)

    result_path = await ensure_extension(tmp_file)
    assert result_path == tmp_path / "sample_1.zip"
    assert result_path.exists()
    assert existing_zip.exists()
    assert not tmp_file.exists()


@pytest.mark.asyncio
async def test_ensure_extension_preserves_non_generic_extension(tmp_path: Path):
    """CRITICAL TEST: Verify files with specific non-generic extensions (e.g. .cbz) are left untouched."""
    cbz_file = tmp_path / "comic_book.cbz"
    cbz_file.write_bytes(ZIP_BYTES)

    result_path = await ensure_extension(cbz_file)
    assert result_path == cbz_file
    assert result_path.name == "comic_book.cbz"
    assert cbz_file.exists()
