from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Union, Sequence

log = logging.getLogger(__name__)


def get_split_archive_info(filename: str) -> Optional[dict]:
    """Detects multi-part / split archive naming patterns.

    Supported patterns:
    1. name.ext.001, name.ext.002, ... (e.g. archive.zip.001)
    2. name.001, name.002, ... (e.g. archive.001)
    3. name.part1.rar, name.part02.rar, ... (e.g. archive.part1.rar)
    """
    # Pattern 1: name.ext.001, name.ext.002, etc. (e.g. archive.zip.001)
    m1 = re.match(r'^(.*)\.([a-zA-Z0-9]+)\.(\d+)$', filename, re.IGNORECASE)
    if m1:
        prefix = m1.group(1)
        ext = m1.group(2)
        part = m1.group(3)
        return {
            "type": "numeric_suffix",
            "prefix": prefix,
            "ext": ext,
            "part": int(part),
            "pattern": re.compile(rf'^{re.escape(prefix)}\.{re.escape(ext)}\.\d+$', re.IGNORECASE),
            "first_part_filename": f"{prefix}.{ext}.{'0' * (len(part) - 1)}1" if len(part) > 1 else f"{prefix}.{ext}.1"
        }

    # Pattern 2: name.001, name.002, etc. (e.g. archive.001)
    m2 = re.match(r'^(.*)\.(\d+)$', filename, re.IGNORECASE)
    if m2:
        prefix = m2.group(1)
        part = m2.group(2)
        return {
            "type": "numeric_suffix_no_ext",
            "prefix": prefix,
            "ext": "",
            "part": int(part),
            "pattern": re.compile(rf'^{re.escape(prefix)}\.\d+$', re.IGNORECASE),
            "first_part_filename": f"{prefix}.{'0' * (len(part) - 1)}1" if len(part) > 1 else f"{prefix}.1"
        }

    # Pattern 3: name.part1.rar, name.part02.rar, etc.
    m3 = re.match(r'^(.*)\.part(\d+)\.([a-zA-Z0-9]+)$', filename, re.IGNORECASE)
    if m3:
        prefix = m3.group(1)
        part = m3.group(2)
        ext = m3.group(3)
        return {
            "type": "part_infix",
            "prefix": prefix,
            "ext": ext,
            "part": int(part),
            "pattern": re.compile(rf'^{re.escape(prefix)}\.part\d+\.{re.escape(ext)}$', re.IGNORECASE),
            "first_part_filename": f"{prefix}.part{'0' * (len(part) - 1)}1.{ext}" if len(part) > 1 else f"{prefix}.part1.{ext}"
        }

    return None


def is_split_archive(target: Union[str, Path, Sequence[Union[str, Path]]]) -> bool:
    """Returns True if the file name or any file in target list matches a split archive pattern."""
    if isinstance(target, (str, Path)):
        return get_split_archive_info(Path(target).name) is not None
    
    for item in target:
        if get_split_archive_info(Path(item).name) is not None:
            return True
    return False
