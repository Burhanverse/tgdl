from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional, Union

import patoolib
from patoolib.util import PatoolError

log = logging.getLogger(__name__)

ARCHIVE_EXT = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz",
    ".tbz2", ".txz", ".Z", ".lz", ".lzma", ".lzo", ".zst", ".cab",
    ".iso", ".ar", ".cpio", ".rpm", ".deb"
}


class ArchivePasswordRequired(Exception):
    """Raised when an archive requires a password or an incorrect password was provided."""
    pass


def is_archive(path_or_filename: Union[str, Path]) -> bool:
    """Checks whether a given file path or filename is recognized as a supported archive."""
    path = Path(path_or_filename)
    ext = path.suffix.lower()
    if ext in ARCHIVE_EXT:
        return True
    try:
        mime_or_fmt = patoolib.get_archive_format(str(path))
        return mime_or_fmt is not None
    except Exception:
        return False


async def extract_archive_async(
    archive_path: Path,
    extract_dir: Path,
    password: Optional[str] = None
) -> bool:
    """Extracts an archive to extract_dir using patoolib.

    Raises ArchivePasswordRequired if password is wrong or missing.
    Returns True if extraction succeeded, False otherwise.
    """
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    if not archive_path.exists():
        log.error("Archive path %s does not exist", archive_path)
        return False

    log.info("Extracting %s to %s using patool", archive_path.name, extract_dir)

    def _extract() -> None:
        kwargs = {
            "outdir": str(extract_dir),
            "verbosity": -1
        }
        if password:
            kwargs["password"] = password

        patoolib.extract_archive(str(archive_path), **kwargs)

    try:
        await asyncio.to_thread(_extract)
        return True
    except PatoolError as pe:
        err_msg = str(pe).lower()
        log.warning("patool extraction error for %s: %s", archive_path.name, pe)
        if any(k in err_msg for k in (
            "password", "incorrect", "encrypted", "bad password",
            "cannot decrypt", "crc failed", "checksum error", "wrong password"
        )):
            raise ArchivePasswordRequired(str(pe)) from pe
        return False
    except ArchivePasswordRequired:
        raise
    except Exception as e:
        err_msg = str(e).lower()
        log.exception("Unexpected error extracting archive %s with patool", archive_path.name)
        if any(k in err_msg for k in (
            "password", "incorrect", "encrypted", "bad password",
            "cannot decrypt", "crc failed", "checksum error", "wrong password"
        )):
            raise ArchivePasswordRequired(str(e)) from e
        return False
