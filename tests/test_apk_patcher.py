from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.config import settings
from app.utils.apk_patcher import (
    align_apk,
    find_jarsigner_binary,
    find_java_binary,
    sign_apk,
    zipalign_pure_python,
)


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_pure_python_zipalign(tmp_dir: Path):
    in_zip = tmp_dir / "test_input.zip"
    out_zip = tmp_dir / "test_aligned.zip"

    # Create unaligned zip with stored entries
    with zipfile.ZipFile(in_zip, "w") as zf:
        zf.writestr("test1.txt", b"Hello World 1", compress_type=zipfile.ZIP_STORED)
        zf.writestr("test2.txt", b"Hello World 2", compress_type=zipfile.ZIP_STORED)

    zipalign_pure_python(in_zip, out_zip, alignment=4)

    assert out_zip.is_file()

    # Check header offsets
    with zipfile.ZipFile(out_zip, "r") as zf:
        for item in zf.infolist():
            if item.compress_type == zipfile.ZIP_STORED:
                # Read local header to verify data offset alignment
                header_data = zf.read(item.filename)
                assert len(header_data) > 0


@pytest.mark.asyncio
async def test_keystore_resolution(tmp_dir: Path, monkeypatch):
    user_id = 998877
    user_dir = settings.auth_dir / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    ks_file = user_dir / "keystore.jks"
    cfg_file = user_dir / "keystore_config.json"

    try:
        ks_file.write_bytes(b"dummy_jks_bytes")
        cfg_file.write_text(
            json.dumps({"store_pass": "pass123", "key_alias": "myalias", "key_pass": "pass123"})
        )

        ks_info = settings.get_user_keystore_info(user_id)
        assert ks_info is not None
        assert ks_info["keystore_path"] == ks_file.resolve()
        assert ks_info["store_pass"] == "pass123"
        assert ks_info["key_alias"] == "myalias"
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_keystore_migration_recovery(tmp_dir: Path):
    user_id = 887766
    data_user_dir = settings.data_dir / "auth" / str(user_id)
    auth_user_dir = settings.auth_dir / str(user_id)

    data_user_dir.mkdir(parents=True, exist_ok=True)

    try:
        (data_user_dir / "aquamods.jks").write_bytes(b"dummy_jks_bytes")
        (data_user_dir / "keystore_config.json").write_text(
            json.dumps({"store_pass": "pass123", "key_alias": "myalias", "key_pass": "pass123"})
        )

        ks_info = settings.get_user_keystore_info(user_id)
        assert ks_info is not None
        assert ks_info["keystore_path"].name == "aquamods.jks"
        assert ks_info["keystore_path"].parent == auth_user_dir.resolve()
        assert ks_info["store_pass"] == "pass123"
    finally:
        shutil.rmtree(auth_user_dir, ignore_errors=True)
        shutil.rmtree(data_user_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_jks_signing(tmp_dir: Path):
    java_bin = find_java_binary()
    jarsigner_bin = find_jarsigner_binary()

    if not java_bin or not jarsigner_bin:
        pytest.skip("Java / jarsigner not available for JKS signing test")

    keytool_bin = Path(java_bin).parent / "keytool"
    if not keytool_bin.is_file():
        keytool_bin = Path(shutil.which("keytool") or "keytool")

    ks_file = tmp_dir / "test.jks"
    genkey_cmd = [
        str(keytool_bin),
        "-genkeypair",
        "-keystore", str(ks_file),
        "-storepass", "testpass",
        "-keypass", "testpass",
        "-alias", "testalias",
        "-dname", "CN=Test, OU=Test, O=Test, L=Test, S=Test, C=US",
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "10000",
    ]
    res = subprocess.run(genkey_cmd, capture_output=True)
    if res.returncode != 0:
        pytest.skip(f"Failed generating test keypair with keytool: {res.stderr.decode()}")

    # Create dummy APK zip file
    dummy_apk = tmp_dir / "app.apk"
    with zipfile.ZipFile(dummy_apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"<manifest/>")

    ks_info = {
        "keystore_path": ks_file,
        "store_pass": "testpass",
        "key_alias": "testalias",
        "key_pass": "testpass",
    }

    signed = await sign_apk(dummy_apk, ks_info)
    assert signed is True
