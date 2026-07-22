from __future__ import annotations

import asyncio
import logging
import os
import shutil
import zipfile

from pathlib import Path
from typing import Optional

from ..config import settings

log = logging.getLogger(__name__)


async def _run_cmd_in_cwd(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    output = (stdout.decode(errors="ignore") + stderr.decode(errors="ignore")).strip()
    return proc.returncode or 0, output


async def archive_folder_async(
    folder_path: Path,
    archive_format: str = "zip",
    max_part_size_mb: int = 1900
) -> list[Path]:
    """Compresses a folder into single or split .zip / .7z archives using 7z, zip CLI, or python zipfile.

    Deletes the original folder upon successful compression.
    Returns a list of created archive file paths.
    """
    if not folder_path.exists() or not folder_path.is_dir():
        log.warning("Path %s is not a directory or does not exist. Skipping archive.", folder_path)
        return [folder_path] if folder_path.exists() else []

    parent_dir = folder_path.parent
    folder_name = folder_path.name
    fmt = archive_format.lower().lstrip("-")
    if fmt not in ("zip", "7z"):
        fmt = "zip"

    output_archive = parent_dir / f"{folder_name}.{fmt}"
    has_7z = shutil.which("7z") is not None
    has_zip = shutil.which("zip") is not None

    log.info("Archiving folder '%s' into %s format...", folder_name, fmt)

    success = False
    if has_7z:
        type_flag = "-tzip" if fmt == "zip" else "-t7z"
        split_flag = f"-v{max_part_size_mb}m"
        cmd = [
            "7z", "a", type_flag, split_flag, "-y",
            str(output_archive),
            "."
        ]
        code, out = await _run_cmd_in_cwd(cmd, folder_path)
        if code == 0:
            success = True
        else:
            log.warning("7z archive command failed (code %s): %s", code, out)

    elif fmt == "zip" and has_zip:
        cmd = [
            "zip", "-r", "-s", f"{max_part_size_mb}m",
            str(output_archive),
            "."
        ]
        code, out = await _run_cmd_in_cwd(cmd, folder_path)
        if code == 0:
            success = True
        else:
            log.warning("zip command failed: %s", out)

    elif fmt == "zip":
        try:
            log.info("7z and zip CLI tools not found. Using standard Python zipfile library for %s", output_archive.name)
            def _create_zip():
                with zipfile.ZipFile(output_archive, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(folder_path):
                        for file in files:
                            full_path = Path(root) / file
                            arcname = full_path.relative_to(folder_path)
                            zf.write(full_path, arcname)

            await asyncio.to_thread(_create_zip)
            if output_archive.exists() and output_archive.stat().st_size > 0:
                success = True
        except Exception as ze:
            log.exception("Python zipfile fallback failed: %s", ze)

    if not success:
        log.error("Failed to archive folder %s. Keeping uncompressed files.", folder_path)
        return list(folder_path.rglob("*"))

    created_archives = []
    prefix = f"{folder_name}.{fmt}"
    for p in parent_dir.iterdir():
        if p.is_file() and (p.name == prefix or p.name.startswith(f"{prefix}.")):
            created_archives.append(p)

    if created_archives:
        shutil.rmtree(folder_path, ignore_errors=True)
        log.info("Successfully archived '%s' into %d volume(s). Original folder deleted.", folder_name, len(created_archives))
        return created_archives
    else:
        return [folder_path]


async def archive_all_folders_in_dir(
    target_dir: Path,
    archive_format: str = "zip"
) -> list[Path]:
    """Iterates through target_dir and archives each folder individually.
    
    If top-level files exist alongside or without subfolders, they are also archived.
    """
    final_paths = []
    if not target_dir.exists() or not target_dir.is_dir():
        return final_paths

    subdirs = [p for p in target_dir.iterdir() if p.is_dir()]
    top_files = [p for p in target_dir.iterdir() if p.is_file()]

    for item in subdirs:
        archives = await archive_folder_async(item, archive_format=archive_format)
        final_paths.extend(archives)

    if top_files and archive_format:
        top_files_dir = target_dir / "Files"
        top_files_dir.mkdir(exist_ok=True)
        for f in top_files:
            try:
                f.rename(top_files_dir / f.name)
            except Exception as e:
                log.warning("Could not move %s into %s: %s", f.name, top_files_dir.name, e)

        archives = await archive_folder_async(top_files_dir, archive_format=archive_format)
        final_paths.extend(archives)

    return final_paths