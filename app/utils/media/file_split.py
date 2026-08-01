from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

async def split_binary(file_path: Path, max_size_bytes: int) -> list[Path]:
    parts = []
    chunk_size = int(max_size_bytes * 0.98)
    buffer_size = 1024 * 1024

    part_num = 1
    try:
        with open(file_path, "rb") as infile:
            while True:
                part_path = file_path.parent / f"{file_path.name}.{part_num:03d}"
                bytes_written = 0

                with open(part_path, "wb") as outfile:
                    while bytes_written < chunk_size:
                        chunk = infile.read(min(buffer_size, chunk_size - bytes_written))
                        if not chunk:
                            break
                        outfile.write(chunk)
                        bytes_written += len(chunk)

                if bytes_written == 0:
                    try:
                        part_path.unlink()
                    except Exception:
                        # expected: empty part file already unlinked
                        pass
                    break

                parts.append(part_path)
                part_num += 1
    except Exception:
        log.exception("Failed to binary split file: %s", file_path.name)
        for p in parts:
            try:
                p.unlink()
            except Exception:
                # expected: split part file already unlinked
                pass
        return []

    return parts
