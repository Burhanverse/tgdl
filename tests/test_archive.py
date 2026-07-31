from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.archive import (
    ArchivePasswordRequired,
    archive_folder_async,
    create_archive_async,
    extract_archive_async,
    get_split_archive_info,
    is_archive,
    is_split_archive,
)


def test_archive_type_detection():
    """Test is_archive and ARCHIVE_EXT detection."""
    assert is_archive("test.zip")
    assert is_archive("package.7z")
    assert is_archive("archive.tar.gz")
    assert is_archive("file.rar")
    assert not is_archive("document.txt")
    assert not is_archive("image.png")


def test_split_archive_pattern_detection():
    """Test get_split_archive_info and is_split_archive for supported naming patterns."""
    # Pattern 1: name.ext.001
    info1 = get_split_archive_info("mydata.zip.001")
    assert info1 is not None
    assert info1["type"] == "numeric_suffix"
    assert info1["prefix"] == "mydata"
    assert info1["ext"] == "zip"
    assert info1["part"] == 1

    info1_2 = get_split_archive_info("mydata.zip.002")
    assert info1_2 is not None
    assert info1_2["part"] == 2

    # Pattern 2: name.001
    info2 = get_split_archive_info("backup.001")
    assert info2 is not None
    assert info2["type"] == "numeric_suffix_no_ext"
    assert info2["prefix"] == "backup"
    assert info2["part"] == 1

    # Pattern 3: name.part1.rar / name.part02.rar
    info3 = get_split_archive_info("video.part1.rar")
    assert info3 is not None
    assert info3["type"] == "part_infix"
    assert info3["prefix"] == "video"
    assert info3["ext"] == "rar"
    assert info3["part"] == 1

    info3_2 = get_split_archive_info("video.part02.rar")
    assert info3_2 is not None
    assert info3_2["part"] == 2

    # Pattern with custom suffix after part number (e.g. xxyyzz -zzz.part2-yJ4ELhGA.rar)
    info_suffix = get_split_archive_info("xxyyzz -zzz.part2-yJ4ELhGA.rar")
    assert info_suffix is not None
    assert info_suffix["prefix"] == "xxyyzz -zzz"
    assert info_suffix["part"] == 2
    assert info_suffix["ext"] == "rar"

    # Normal non-split files
    assert get_split_archive_info("normal.zip") is None
    assert get_split_archive_info("archive.rar") is None

    # is_split_archive
    assert is_split_archive("mydata.zip.001")
    assert is_split_archive(["file.txt", "mydata.zip.001"])
    assert not is_split_archive("normal.zip")


@pytest.mark.asyncio
async def test_zip_creation_and_extraction():
    """Test creating a zip archive and extracting it with patool."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        # Create dummy source files
        file1 = source_dir / "file1.txt"
        file1.write_text("Hello World 1")
        file2 = source_dir / "file2.txt"
        file2.write_text("Hello World 2")

        archive_path = tmp_path / "test_out.zip"

        # Create archive
        created = await create_archive_async(source_dir, archive_path, archive_format="zip")
        assert created
        assert archive_path.exists()
        assert archive_path.stat().st_size > 0

        # Extract archive
        extract_dir = tmp_path / "extracted"
        extracted = await extract_archive_async(archive_path, extract_dir)
        assert extracted
        assert extract_dir.exists()

        extracted_files = [p.name for p in extract_dir.rglob("*") if p.is_file()]
        assert "file1.txt" in extracted_files
        assert "file2.txt" in extracted_files


@pytest.mark.asyncio
async def test_archive_folder_async_helper():
    """Test archive_folder_async creating single or split archives."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        folder = tmp_path / "data_folder"
        folder.mkdir()
        (folder / "item.txt").write_text("Sample file content")

        archives, pd_links = await archive_folder_async(folder, archive_format="zip")
        assert len(archives) >= 1
        assert archives[0].exists()
        assert not folder.exists()  # folder is deleted after archiving


@pytest.mark.asyncio
async def test_corrupt_archive_handling():
    """Test handling of corrupt archive files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        corrupt_zip = tmp_path / "corrupt.zip"
        corrupt_zip.write_bytes(b"THIS IS NOT A ZIP ARCHIVE DATA")

        extract_dir = tmp_path / "extracted_corrupt"
        # Should gracefully fail and return False without uncaught exception
        res = await extract_archive_async(corrupt_zip, extract_dir)
        assert res is False


@pytest.mark.asyncio
async def test_missing_archive_file():
    """Test extract_archive_async with non-existent archive path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_file = Path(tmpdir) / "does_not_exist.zip"
        extract_dir = Path(tmpdir) / "extracted"
        res = await extract_archive_async(missing_file, extract_dir)
        assert res is False


@pytest.mark.asyncio
async def test_multi_part_split_archive_assembly():
    """Test split archive part detection and structure verification."""
    part1_name = "archive.zip.001"
    part2_name = "archive.zip.002"

    info1 = get_split_archive_info(part1_name)
    info2 = get_split_archive_info(part2_name)

    assert info1["prefix"] == info2["prefix"]
    assert info1["part"] == 1
    assert info2["part"] == 2


@pytest.mark.asyncio
async def test_split_archive_filename_normalization():
    """Test normalizing split filenames with random Telegram hash suffixes."""
    from app.archive.split import normalize_split_archive_filenames
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        f1 = tmp_path / "xxyyzz -zzz.part1-tnfHAaap.rar"
        f2 = tmp_path / "xxyyzz -zzz.part2-yJ4ELhGA.rar"
        f1.write_text("dummy part 1")
        f2.write_text("dummy part 2")

        renamed = normalize_split_archive_filenames(tmp_path)
        assert len(renamed) == 2
        file_names = {p.name for p in tmp_path.iterdir()}
        assert "xxyyzz -zzz.part1.rar" in file_names
        assert "xxyyzz -zzz.part2.rar" in file_names


@pytest.mark.asyncio
async def test_password_protected_archive_handling():
    """Test password-protected 7z archive extraction with correct password and raising ArchivePasswordRequired on wrong password."""
    import py7zr
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        archive_path = tmp_path / "protected.7z"
        
        # Create an encrypted 7z archive
        with py7zr.SevenZipFile(archive_path, "w", password="mysecretpassword") as archive:
            archive.writestr("Top secret data content", "secret.txt")

        extract_dir1 = tmp_path / "out_correct"
        # Extraction with correct password should succeed
        success = await extract_archive_async(archive_path, extract_dir1, password="mysecretpassword")
        assert success
        assert (extract_dir1 / "secret.txt").read_text() == "Top secret data content"

        extract_dir2 = tmp_path / "out_wrong"
        # Extraction with wrong password should raise ArchivePasswordRequired
        with pytest.raises(ArchivePasswordRequired):
            await extract_archive_async(archive_path, extract_dir2, password="wrongpassword")

        extract_dir3 = tmp_path / "out_nopass"
        # Extraction with missing password should raise ArchivePasswordRequired
        with pytest.raises(ArchivePasswordRequired):
            await extract_archive_async(archive_path, extract_dir3, password=None)
