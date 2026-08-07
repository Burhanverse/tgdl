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

TOOLS_DIR = (settings.data_dir / "tools").resolve()
APKEDITOR_JAR = (TOOLS_DIR / "APKEditor.jar").resolve()
UBER_APK_SIGNER_JAR = (TOOLS_DIR / "uber-apk-signer.jar").resolve()
TGPATCHER_PY = (TOOLS_DIR / "tgpatcher.py").resolve()

APKEDITOR_RELEASE_API = "https://api.github.com/repos/REAndroid/APKEditor/releases/latest"
UBER_APK_SIGNER_RELEASE_API = "https://api.github.com/repos/patrickfav/uber-apk-signer/releases/latest"
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


def find_apksigner_binary() -> str | None:
    """Finds available apksigner binary on the system."""
    apk_cmd = shutil.which("apksigner")
    if apk_cmd:
        return apk_cmd

    search_dirs = []
    for env_var in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK"):
        val = os.getenv(env_var)
        if val:
            search_dirs.append(Path(val) / "build-tools")

    home = Path.home()
    search_dirs.extend([
        home / "Android/Sdk/build-tools",
        Path("/usr/lib/android-sdk/build-tools"),
        Path("/opt/android-sdk/build-tools"),
    ])

    for base_dir in search_dirs:
        try:
            if base_dir.is_dir():
                for sub in base_dir.iterdir():
                    candidate = sub / "apksigner"
                    if candidate.is_file() and os.access(candidate, os.X_OK):
                        return str(candidate)
        except Exception:
            pass

    return None


def find_jarsigner_binary() -> str | None:
    """Finds available jarsigner binary on the system by resolving java symlinks and checking JDK paths."""
    js_cmd = shutil.which("jarsigner")
    if js_cmd:
        return js_cmd

    # Check JAVA_HOME
    java_home = os.getenv("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / "jarsigner"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    # Check resolved symlink of java binary
    java_bin = find_java_binary()
    if java_bin:
        try:
            resolved_bin = Path(java_bin).resolve()
            candidate = resolved_bin.parent / "jarsigner"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except Exception:
            pass

    home = Path.home()
    candidates = [
        home / ".sdkman/candidates/java/current/bin/jarsigner",
        Path("/usr/lib/jvm/default-jvm/bin/jarsigner"),
    ]

    try:
        jvm_dir = Path("/usr/lib/jvm")
        if jvm_dir.is_dir():
            for p in jvm_dir.rglob("jarsigner"):
                if p.is_file() and os.access(p, os.X_OK):
                    candidates.append(p)
    except Exception:
        pass

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

        # 2. Download uber-apk-signer.jar if missing
        if not UBER_APK_SIGNER_JAR.is_file() or UBER_APK_SIGNER_JAR.stat().st_size == 0:
            log.info("Fetching uber-apk-signer.jar release info from GitHub...")
            try:
                resp = await client.get(UBER_APK_SIGNER_RELEASE_API)
                resp.raise_for_status()
                release_info = resp.json()
                assets = release_info.get("assets", [])
                jar_asset = next((a for a in assets if str(a.get("name", "")).endswith(".jar")), None)
                if jar_asset and "browser_download_url" in jar_asset:
                    download_url = jar_asset["browser_download_url"]
                    log.info("Downloading uber-apk-signer.jar from %s...", download_url)
                    jar_resp = await client.get(download_url)
                    jar_resp.raise_for_status()
                    UBER_APK_SIGNER_JAR.write_bytes(jar_resp.content)
                    log.info("uber-apk-signer.jar saved to %s", UBER_APK_SIGNER_JAR)
            except Exception as e:
                log.warning("Could not download uber-apk-signer.jar: %s", e)

        # 3. Download tgpatcher.py if missing
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


def find_zipalign_binary() -> str | None:
    """Finds available zipalign binary on the system (PATH, Termux, Android SDK)."""
    za_cmd = shutil.which("zipalign")
    if za_cmd:
        return za_cmd

    prefix = os.getenv("PREFIX")
    if prefix:
        candidate = Path(prefix) / "bin" / "zipalign"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    search_dirs = []
    for env_var in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK"):
        val = os.getenv(env_var)
        if val:
            search_dirs.append(Path(val) / "build-tools")

    home = Path.home()
    search_dirs.extend([
        home / "Android/Sdk/build-tools",
        Path("/usr/lib/android-sdk/build-tools"),
        Path("/opt/android-sdk/build-tools"),
    ])

    for base_dir in search_dirs:
        try:
            if base_dir.is_dir():
                for sub in base_dir.iterdir():
                    candidate = sub / "zipalign"
                    if candidate.is_file() and os.access(candidate, os.X_OK):
                        return str(candidate)
        except Exception:
            pass

    return None


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
    input_apk = Path(input_apk).resolve()
    output_apk = Path(output_apk).resolve()
    zipalign_bin = find_zipalign_binary()
    if zipalign_bin:
        cmd = [zipalign_bin, "-p", "-f", "4", str(input_apk), str(output_apk)]
        log.info("Running zipalign CLI (%s)...", zipalign_bin)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log.info("Successfully aligned APK with zipalign CLI.")
            return
        log.warning("zipalign CLI failed (code %s): %s. Falling back to pure Python zipalign.", proc.returncode, stderr.decode())

    log.info("Using pure Python 4-byte zip alignment.")
    await asyncio.to_thread(zipalign_pure_python, input_apk, output_apk)


async def sign_apk(apk_path: Path, keystore_info: dict) -> bool:
    """Signs APK using apksigner, uber-apk-signer, or jarsigner with provided JKS keystore details."""
    apk_path = Path(apk_path).resolve()
    raw_ks = keystore_info.get("keystore_path")
    ks_path = Path(raw_ks).resolve() if raw_ks else None
    store_pass = keystore_info.get("store_pass", "")
    key_alias = keystore_info.get("key_alias", "")
    key_pass = keystore_info.get("key_pass") or store_pass

    if not ks_path or not Path(ks_path).is_file():
        log.warning("Keystore file %s not found. Skipping signing.", ks_path)
        return False

    apksigner_bin = find_apksigner_binary()
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
        log.info("Signing APK with apksigner (%s)...", apksigner_bin)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log.info("Successfully signed APK with apksigner.")
            return True
        log.warning("apksigner failed (code %s): %s. Trying uber-apk-signer...", proc.returncode, stderr.decode())

    java_bin = find_java_binary()
    if UBER_APK_SIGNER_JAR.is_file() and UBER_APK_SIGNER_JAR.stat().st_size > 0:
        cmd = [
            java_bin,
            "-jar", str(UBER_APK_SIGNER_JAR),
            "--apks", str(apk_path),
            "--ks", str(ks_path),
            "--ksAlias", str(key_alias),
            "--ksPass", str(store_pass),
            "--keyPass", str(key_pass),
            "--overwrite",
        ]
        log.info("Signing APK with uber-apk-signer (v1+v2+v3+v4)...")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log.info("Successfully signed APK with uber-apk-signer.")
            return True
        log.warning("uber-apk-signer failed (code %s): %s. Trying jarsigner...", proc.returncode, stderr.decode())

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
        log.info("Signing APK with jarsigner (%s)...", jarsigner_bin)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            log.info("Successfully signed APK with jarsigner.")
            return True
        log.error("jarsigner failed (code %s): %s", proc.returncode, stderr.decode())
        return False

    return False


async def sign_and_align_apk(
    unaligned_apk: Path,
    output_apk: Path,
    keystore_info: dict | None = None,
) -> bool:
    """Uses uber-apk-signer.jar as primary tool to zip-align, sign (v1+v2+v3+v4), and verify APK in a single step."""
    unaligned_apk = Path(unaligned_apk).resolve()
    output_apk = Path(output_apk).resolve()
    java_bin = find_java_binary()

    # 1. Primary Tool: uber-apk-signer.jar (Zip-aligns & signs with v1+v2+v3+v4 in one step)
    if UBER_APK_SIGNER_JAR.is_file() and UBER_APK_SIGNER_JAR.stat().st_size > 0:
        cmd = [
            java_bin,
            "-jar", str(UBER_APK_SIGNER_JAR),
            "--apks", str(unaligned_apk),
            "--out", str(output_apk.parent),
        ]

        has_keystore = False
        if keystore_info:
            raw_ks = keystore_info.get("keystore_path")
            ks_path = Path(raw_ks).resolve() if raw_ks else None
            store_pass = keystore_info.get("store_pass", "")
            key_alias = keystore_info.get("key_alias", "")
            key_pass = keystore_info.get("key_pass") or store_pass

            if ks_path and ks_path.is_file():
                has_keystore = True
                cmd.extend([
                    "--ks", str(ks_path),
                    "--ksAlias", str(key_alias),
                    "--ksPass", str(store_pass),
                    "--keyPass", str(key_pass),
                ])

        log.info("Running uber-apk-signer (zipalign + v1+v2+v3+v4 sign)...")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        # uber-apk-signer names output as <stem>-aligned-signed.apk (or -aligned-unsigned.apk)
        signed_out = output_apk.parent / f"{unaligned_apk.stem}-aligned-signed.apk"
        unsigned_out = output_apk.parent / f"{unaligned_apk.stem}-aligned-unsigned.apk"

        target_out = signed_out if signed_out.is_file() else (unsigned_out if unsigned_out.is_file() else None)
        if target_out and target_out.is_file():
            if output_apk.exists():
                output_apk.unlink()
            shutil.move(str(target_out), str(output_apk))
            log.info("Successfully zip-aligned & signed APK with uber-apk-signer.")
            return True
        log.warning("uber-apk-signer finished but output not found (stdout: %s, stderr: %s). Falling back...", stdout.decode(), stderr.decode())

    # Fallback 1: align_apk
    log.info("Falling back to align_apk...")
    await align_apk(unaligned_apk, output_apk)

    # Fallback 2: sign_apk
    if keystore_info:
        log.info("Falling back to sign_apk...")
        await sign_apk(output_apk, keystore_info)

    return output_apk.is_file()


async def patch_apk_async(
    input_apk: Path,
    output_dir: Path,
    original_filename: str,
    keystore_info: dict | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> Path:
    """Pure Python implementation of patch.sh:
    Decompiles APK -> Patches via tgpatcher.py --anti -> Recompiles -> Zip-aligns & Signs (v1-v4) via uber-apk-signer.jar.
    Final product name: <original_filename>_patched.apk
    """
    if progress_cb:
        progress_cb("Ensuring APKEditor, tgpatcher & uber-apk-signer tools...")

    input_apk = input_apk.resolve()
    output_dir = output_dir.resolve()
    apkeditor_jar, tgpatcher_py = await ensure_tools()
    apkeditor_jar = apkeditor_jar.resolve()
    tgpatcher_py = tgpatcher_py.resolve()
    java_bin = find_java_binary()

    # Determine original filename base
    clean_orig = original_filename.strip()
    if clean_orig.lower().endswith(".apk"):
        orig_base = clean_orig[:-4]
    else:
        orig_base = clean_orig or "app"

    out_filename = f"{orig_base}_patched.apk"
    final_output_path = (output_dir / out_filename).resolve()

    work_dir = (output_dir / "patcher_tmp").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        decompiled_dir = (work_dir / "plus").resolve()
        unaligned_apk = (work_dir / "unaligned_patched.apk").resolve()

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

        # 4. Zip-align & Sign APK via uber-apk-signer.jar (v1+v2+v3+v4)
        if progress_cb:
            progress_cb("Zip-aligning & Signing APK (v1+v2+v3+v4) with uber-apk-signer...")
        await sign_and_align_apk(unaligned_apk, final_output_path, keystore_info)

        log.info("Patching completed successfully! Output file: %s", final_output_path)
        return final_output_path

    finally:
        # Cleanup temporary patcher work directory
        shutil.rmtree(work_dir, ignore_errors=True)
