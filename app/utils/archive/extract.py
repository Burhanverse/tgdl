from __future__ import annotations

import asyncio
import logging
import shutil
import zipfile
from pathlib import Path

import patoolib
from patoolib.util import PatoolError

from .split_detect import get_split_archive_info, normalize_split_archive_filenames

log = logging.getLogger(__name__)

ARCHIVE_EXT = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz",
    ".tbz2", ".txz", ".Z", ".lz", ".lzma", ".lzo", ".zst", ".cab",
    ".iso", ".ar", ".cpio", ".rpm", ".deb"
}


class ArchivePasswordRequired(Exception):
    """Raised when an archive requires a password or an incorrect password was provided."""


def is_archive(path_or_filename: str | Path) -> bool:
    """Checks whether a given file path or filename is recognized as a supported archive."""
    path = Path(path_or_filename)
    ext = path.suffix.lower()
    if ext in ARCHIVE_EXT:
        return True
    try:
        mime_or_fmt = patoolib.get_archive_format(str(path))
        return mime_or_fmt is not None
    except Exception:
        # expected: file is not a valid archive format
        return False


def _is_password_err(err_text: str) -> bool:
    low = err_text.lower()
    # Structural archive / missing volume errors are NOT password errors
    if any(k in low for k in (
        "cannot find volume", "volume missing", "volume not found",
        "unexpected end of archive", "no files to extract", "cannot open volume"
    )):
        return False

    return any(k in low for k in (
        "password", "incorrect", "encrypted", "bad password",
        "cannot decrypt", "crc failed", "checksum error", "wrong password",
        "non-zero exit status 6", "non-zero exit status 3", "non-zero exit status 2",
        "non-zero exit status 50", "non-zero exit status 82",
        "corrupt input data", "password is required", "header encrypted"
    ))


async def extract_archive_async(
    archive_path: Path,
    extract_dir: Path,
    password: str | None = None
) -> bool:
    """Extracts an archive to extract_dir using patoolib and fallback CLI/Python tools.

    Raises ArchivePasswordRequired if password is wrong or missing.
    Returns True if extraction succeeded, False otherwise.
    """
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    if not archive_path.exists():
        log.error("Archive path %s does not exist", archive_path)
        return False

    renamed_map = normalize_split_archive_filenames(archive_path.parent)
    if archive_path in renamed_map:
        archive_path = renamed_map[archive_path]
        log.info("Archive path updated after normalization to %s", archive_path.name)

    split_info = get_split_archive_info(archive_path.name)
    if split_info and split_info["part"] > 1:
        log.info("Path %s is part %d of split archive prefix '%s'. Searching for part 1 in %s...",
                 archive_path.name, split_info["part"], split_info["prefix"], archive_path.parent)
        parent_dir = archive_path.parent
        part1_candidates = []
        for sibling in parent_dir.iterdir():
            if sibling.is_file():
                s_info = get_split_archive_info(sibling.name)
                if s_info and s_info["prefix"] == split_info["prefix"] and s_info["part"] == 1:
                    part1_candidates.append(sibling)

        if part1_candidates:
            archive_path = part1_candidates[0]
            log.info("Redirecting extraction to part 1: %s", archive_path.name)
        else:
            log.warning("Part 1 for split archive prefix '%s' not found in %s", split_info["prefix"], parent_dir)

    log.info("Extracting %s (password_supplied=%s) to %s...",
             archive_path.name, bool(password), extract_dir)

    # 1. Try patool
    try:
        def _patool_extract():
            kwargs = {"outdir": str(extract_dir), "verbosity": -1}
            if password:
                kwargs["password"] = password
            patoolib.extract_archive(str(archive_path), **kwargs)

        await asyncio.to_thread(_patool_extract)
        return True
    except PatoolError as pe:
        err_msg = str(pe)
        log.warning("patool extraction error for %s: %s", archive_path.name, err_msg)
        if _is_password_err(err_msg):
            raise ArchivePasswordRequired(err_msg) from pe
    except ArchivePasswordRequired:
        raise
    except Exception as e:
        err_msg = str(e)
        log.warning("patool exception for %s: %s", archive_path.name, err_msg)
        if _is_password_err(err_msg):
            raise ArchivePasswordRequired(err_msg) from e

    ext = archive_path.suffix.lower()

    # 2. Fallback: unrar CLI for .rar archives
    if ext == ".rar" or archive_path.name.lower().endswith(".rar"):
        unrar_bin = shutil.which("unrar")
        if unrar_bin:
            try:
                log.info("Attempting direct unrar CLI extraction for %s", archive_path.name)
                args = [unrar_bin, "x", "-y"]
                if password:
                    args.append(f"-p{password}")
                else:
                    args.append("-p-")
                args.extend(["-kb", "-or", "--", str(archive_path), f"{extract_dir}/"])

                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                out_str = (stdout.decode(errors="ignore") + stderr.decode(errors="ignore")).lower()
                if proc.returncode == 0:
                    return True
                log.warning("unrar CLI returned code %s: %s", proc.returncode, out_str)
                if proc.returncode in (3, 6) or _is_password_err(out_str):
                    raise ArchivePasswordRequired(out_str)
            except ArchivePasswordRequired:
                raise
            except Exception as e:
                log.warning("unrar CLI fallback error: %s", e)

    # 3. Fallback: py7zr or 7z CLI for .7z archives
    if ext in (".7z", ".7za") or "7z" in archive_path.name.lower():
        cmd7z = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")
        if cmd7z:
            try:
                log.info("Attempting direct 7z CLI extraction for %s", archive_path.name)
                args = [cmd7z, "x", "-y", f"-o{extract_dir}"]
                if password:
                    args.append(f"-p{password}")
                else:
                    args.append("-p-")
                args.append(str(archive_path))

                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                out_str = (stdout.decode(errors="ignore") + stderr.decode(errors="ignore")).lower()
                if proc.returncode == 0:
                    return True
                log.warning("7z CLI returned code %s: %s", proc.returncode, out_str)
                if proc.returncode in (2, 8) or _is_password_err(out_str):
                    raise ArchivePasswordRequired(out_str)
            except ArchivePasswordRequired:
                raise
            except Exception as e:
                log.warning("7z CLI fallback error: %s", e)

        try:
            import py7zr
            def _py7zr_extract():
                with py7zr.SevenZipFile(archive_path, mode='r', password=password) as z:
                    target_dir = extract_dir.resolve()
                    for name in z.getnames():
                        member_path = (target_dir / name).resolve()
                        if not member_path.is_relative_to(target_dir):
                            log.warning("Zip-slip path traversal attempt detected in 7z member '%s' of %s. Skipping.", name, archive_path.name)
                            raise ValueError(f"Path traversal detected in archive member '{name}'")
                    z.extractall(path=extract_dir)

            await asyncio.to_thread(_py7zr_extract)
            return True
        except ArchivePasswordRequired:
            raise
        except Exception as py7e:
            err_str = str(py7e)
            log.warning("py7zr extraction error: %s", err_str)
            if _is_password_err(err_str) or "password" in type(py7e).__name__.lower():
                raise ArchivePasswordRequired(err_str) from py7e

    # 4. Fallback: unzip CLI or zipfile for .zip archives
    if ext == ".zip":
        unzip_bin = shutil.which("unzip")
        if unzip_bin:
            try:
                log.info("Attempting direct unzip CLI extraction for %s", archive_path.name)
                args = [unzip_bin, "-o"]
                if password:
                    args.extend(["-P", password])
                args.extend([str(archive_path), "-d", str(extract_dir)])

                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                out_str = (stdout.decode(errors="ignore") + stderr.decode(errors="ignore")).lower()
                if proc.returncode == 0:
                    return True
                log.warning("unzip CLI returned code %s: %s", proc.returncode, out_str)
                if proc.returncode in (50, 82) or _is_password_err(out_str):
                    raise ArchivePasswordRequired(out_str)
            except ArchivePasswordRequired:
                raise
            except Exception as e:
                log.warning("unzip CLI fallback error: %s", e)

        try:
            def _zip_extract():
                with zipfile.ZipFile(archive_path) as zf:
                    pwd_bytes = password.encode("utf-8") if password else None
                    target_dir = extract_dir.resolve()
                    for member in zf.infolist():
                        member_path = (target_dir / member.filename).resolve()
                        if not member_path.is_relative_to(target_dir):
                            log.warning("Zip-slip path traversal attempt detected in zip member '%s' of %s. Skipping.", member.filename, archive_path.name)
                            continue
                        zf.extract(member, path=extract_dir, pwd=pwd_bytes)

            await asyncio.to_thread(_zip_extract)
            return True
        except ArchivePasswordRequired:
            raise
        except RuntimeError as rte:
            if "password" in str(rte).lower() or "bad password" in str(rte).lower():
                raise ArchivePasswordRequired(str(rte)) from rte
        except Exception as ze:
            log.warning("zipfile extraction error: %s", ze)

    # 5. Final check: if password was explicitly provided but all extractions failed, raise ArchivePasswordRequired
    if password:
        log.warning("Extraction failed with provided password <redacted, length=%d> for %s. Requesting password retry.", len(password), archive_path.name)
        raise ArchivePasswordRequired(f"Incorrect password for {archive_path.name}")

    return False
