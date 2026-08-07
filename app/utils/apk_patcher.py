from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from ..config import settings

log = logging.getLogger(__name__)

TOOLS_DIR = settings.data_dir / "tools"
APKEDITOR_JAR = TOOLS_DIR / "APKEditor.jar"
TGPATCHER_PY = TOOLS_DIR / "tgpatcher.py"

APKEDITOR_RELEASE_API = "https://api.github.com/repos/REAndroid/APKEditor/releases/latest"
TGPATCHER_URL = "https://raw.githubusercontent.com/AbhiTheModder/termux-scripts/refs/heads/main/tgpatcher.py"


def find_java_binary() -> str:
    """Finds available java binary on the system."""
    java_cmd = shutil.which("java")
    if java_cmd:
        return java_cmd

    # Check common SDKMAN / OpenJDK locations
    home = Path.home()
    candidates = [
        home / ".sdkman/candidates/java/current/bin/java",
        Path("/usr/lib/jvm/default-jvm/bin/java"),
        Path("/usr/lib/jvm/java-21-openjdk/bin/java"),
        Path("/usr/lib/jvm/java-17-openjdk/bin/java"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)

    return "java"


def find_jarsigner_binary() -> str | None:
    """Finds available jarsigner binary on the system."""
    js_cmd = shutil.which("jarsigner")
    if js_cmd:
        return js_cmd

    java_bin = find_java_binary()
    if java_bin and java_bin != "java":
        candidate = Path(java_bin).parent / "jarsigner"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    home = Path.home()
    candidates = [
        home / ".sdkman/candidates/java/current/bin/jarsigner",
        Path("/usr/lib/jvm/default-jvm/bin/jarsigner"),
        Path("/usr/lib/jvm/java-21-openjdk/bin/jarsigner"),
        Path("/usr/lib/jvm/java-17-openjdk/bin/jarsigner"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)

    return None


async def ensure_tools() -> tuple[Path, Path]:
    """Ensures APKEditor.jar and tgpatcher.py are downloaded and ready."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        # 1. Download APKEditor.jar if missing
        if not APKEDITOR_JAR.is_file() or APKEDITOR_JAR.stat().st_size == 0:
            log.info("Fetching APKEditor.jar release info from GitHub...")
            resp = await client.get(APKEDITOR_RELEASE_API)
            resp.raise_for_status()
            release_info = resp.json()
            assets = release_info.get("assets", [])
            jar_asset = next((a for a in assets if str(a.get("name", "")).endswith(".jar")), None)
            if not jar_asset or "browser_download_url" not in jar_asset:
                raise RuntimeError("Could not find .jar asset in APKEditor GitHub release.")

            download_url = jar_asset["browser_download_url"]
            log.info("Downloading APKEditor.jar from %s...", download_url)
            jar_resp = await client.get(download_url)
            jar_resp.raise_for_status()
            APKEDITOR_JAR.write_bytes(jar_resp.content)
            log.info("APKEditor.jar saved to %s", APKEDITOR_JAR)

        # 2. Download tgpatcher.py if missing
        if not TGPATCHER_PY.is_file() or TGPATCHER_PY.stat().st_size == 0:
            log.info("Downloading tgpatcher.py from %s...", TGPATCHER_URL)
            py_resp = await client.get(TGPATCHER_URL)
            py_resp.raise_for_status()
            content = py_resp.text
            # Apply branding edit
            content = content.replace("Mod by Abhi", "by AquaLabs")
            TGPATCHER_PY.write_text(content, encoding="utf-8")
            log.info("tgpatcher.py saved to %s", TGPATCHER_PY)
        else:
            # Ensure branding is applied
            content = TGPATCHER_PY.read_text(encoding="utf-8")
            if "Mod by Abhi" in content:
                content = content.replace("Mod by Abhi", "by AquaLabs")
                TGPATCHER_PY.write_text(content, encoding="utf-8")

    return APKEDITOR_JAR, TGPATCHER_PY


def zipalign_pure_python(input_zip: Path, output_zip: Path, alignment: int = 4) -> None:
    """Pure Python 4-byte zip alignment for stored (uncompressed) entries in an APK."""
    with zipfile.ZipFile(input_zip, "r") as in_zf, zipfile.ZipFile(
        output_zip, "w", compression=zipfile.ZIP_DEFLATED
    ) as out_zf:
        for item in in_zf.infolist():
            data = in_zf.read(item.filename)
            if item.compress_type == zipfile.ZIP_STORED:
                filename_bytes = item.filename.encode("utf-8")
                current_offset = out_zf.fp.tell()
                header_size = 30 + len(filename_bytes)
                data_offset = current_offset + header_size + len(item.extra)
                padding = (alignment - (data_offset % alignment)) % alignment
                if padding > 0:
                    item.extra = item.extra + b"\x00" * padding
            out_zf.writestr(item, data)


async def align_apk(input_apk: Path, output_apk: Path) -> None:
    """Aligns APK entries using zipalign CLI if available, or pure Python fallback."""
    zipalign_bin = shutil.which("zipalign")
    if zipalign_bin:
        cmd = [zipalign_bin, "-p", "-f", "4", str(input_apk), str(output_apk)]
        log.info("Running zipalign CLI: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("zipalign CLI failed (code %s): %s. Falling back to pure Python zipalign.", proc.returncode, stderr.decode())
            zipalign_pure_python(input_apk, output_apk)
    else:
        log.info("zipalign binary not found in PATH. Using pure Python 4-byte zip alignment.")
        await asyncio.to_thread(zipalign_pure_python, input_apk, output_apk)


async def sign_apk(apk_path: Path, keystore_info: dict) -> bool:
    """Signs APK using apksigner or jarsigner with provided JKS keystore details."""
    ks_path = keystore_info.get("keystore_path")
    store_pass = keystore_info.get("store_pass", "")
    key_alias = keystore_info.get("key_alias", "")
    key_pass = keystore_info.get("key_pass") or store_pass

    if not ks_path or not Path(ks_path).is_file():
        log.warning("Keystore file %s not found. Skipping signing.", ks_path)
        return False

    apksigner_bin = shutil.which("apksigner")
    if apksigner_bin:
        cmd = [
            apksigner_bin,
            "sign",
            "--ks", str(ks_path),
            "--ks-pass", f"pass:{store_pass}",
            "--ks-key-alias", str(key_alias),
            "--key-pass", f"pass:{key_pass}",
            str(apk_path),
        ]
        log.info("Signing APK with apksigner...")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log.info("Successfully signed APK with apksigner.")
            return True
        log.warning("apksigner failed (code %s): %s. Trying jarsigner...", proc.returncode, stderr.decode())

    jarsigner_bin = find_jarsigner_binary()
    if jarsigner_bin:
        cmd = [
            jarsigner_bin,
            "-keystore", str(ks_path),
            "-storepass", str(store_pass),
            "-keypass", str(key_pass),
            "-sigalg", "SHA256withRSA",
            "-digestalg", "SHA-256",
            str(apk_path),
            str(key_alias),
        ]
        log.info("Signing APK with jarsigner...")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log.info("Successfully signed APK with jarsigner.")
            return True
        log.error("jarsigner failed (code %s): %s", proc.returncode, stderr.decode())
        return False

    log.warning("Neither apksigner nor jarsigner found. APK left unsigned.")
    return False


async def patch_apk_async(
    input_apk: Path,
    output_dir: Path,
    original_filename: str,
    keystore_info: dict | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> Path:
    """Pure Python implementation of patch.sh:
    Decompiles APK -> Patches via tgpatcher.py --anti -> Recompiles -> Zip-aligns -> Signs with JKS keystore.
    Final product name: <original_filename>_patched.apk
    """
    if progress_cb:
        progress_cb("Ensuring APKEditor & tgpatcher tools...")

    apkeditor_jar, tgpatcher_py = await ensure_tools()
    java_bin = find_java_binary()

    # Determine original filename base
    clean_orig = original_filename.strip()
    if clean_orig.lower().endswith(".apk"):
        orig_base = clean_orig[:-4]
    else:
        orig_base = clean_orig or "app"

    out_filename = f"{orig_base}_patched.apk"
    final_output_path = output_dir / out_filename

    work_dir = output_dir / "patcher_tmp"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        decompiled_dir = work_dir / "plus"
        unaligned_apk = work_dir / "unaligned_patched.apk"
        aligned_apk = work_dir / "aligned_patched.apk"

        # 1. Decompile APK
        if progress_cb:
            progress_cb("Decompiling APK with APKEditor...")
        log.info("Decompiling %s to %s...", input_apk, decompiled_dir)
        d_cmd = [java_bin, "-jar", str(apkeditor_jar), "d", "-i", str(input_apk), "-o", str(decompiled_dir), "-dex-lib", "jf"]
        proc = await asyncio.create_subprocess_exec(
            *d_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(work_dir)
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Decompilation failed (code {proc.returncode}): {stderr.decode()}")

        # 2. Run tgpatcher.py --anti --dir plus
        if progress_cb:
            progress_cb("Applying tgpatcher.py --anti patch...")
        log.info("Patching decompiled directory %s with tgpatcher.py...", decompiled_dir)
        p_cmd = [
            "python3", str(tgpatcher_py), "--anti", "--dir", "plus"
        ]
        proc = await asyncio.create_subprocess_exec(
            *p_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(work_dir)
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("tgpatcher.py returned non-zero code %s: %s", proc.returncode, stderr.decode())

        # 3. Recompile APK
        if progress_cb:
            progress_cb("Recompiling APK with APKEditor...")
        log.info("Recompiling %s to %s...", decompiled_dir, unaligned_apk)
        b_cmd = [java_bin, "-jar", str(apkeditor_jar), "b", "-i", str(decompiled_dir), "-o", str(unaligned_apk), "-dex-lib", "jf"]
        proc = await asyncio.create_subprocess_exec(
            *b_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(work_dir)
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Recompilation failed (code {proc.returncode}): {stderr.decode()}")

        # 4. Zip Align
        if progress_cb:
            progress_cb("Zip-aligning APK entries...")
        await align_apk(unaligned_apk, aligned_apk)

        # 5. Sign APK
        if keystore_info:
            if progress_cb:
                progress_cb("Signing APK with JKS keystore...")
            await sign_apk(aligned_apk, keystore_info)
        else:
            log.warning("No keystore info provided. APK was aligned but not signed.")

        # 6. Move final product to output_dir / <original_filename>_patched.apk
        shutil.move(str(aligned_apk), str(final_output_path))
        log.info("Patching completed successfully! Output file: %s", final_output_path)
        return final_output_path

    finally:
        # Cleanup temporary patcher work directory
        shutil.rmtree(work_dir, ignore_errors=True)
