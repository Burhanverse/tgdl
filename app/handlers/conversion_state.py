from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


class ConversionSessionStore:
    """Encapsulates per-job media conversion choice and tracking state."""

    def __init__(self) -> None:
        self._conversion_ids: dict[str, dict[str, str]] = {}
        self._conversion_events: dict[str, dict[str, asyncio.Event]] = {}
        self._conversion_choices: dict[str, dict[str, str]] = {}
        self._converted_files: dict[str, set[str]] = {}

    def register_conversion_id(self, job_id: str, conv_id: str, filename: str) -> None:
        if job_id not in self._conversion_ids:
            self._conversion_ids[job_id] = {}
        self._conversion_ids[job_id][conv_id] = filename

    def get_conversion_filename(self, job_id: str, conv_id: str) -> str | None:
        return self._conversion_ids.get(job_id, {}).get(conv_id)

    def get_conversion_ids(self, job_id: str) -> dict[str, str]:
        return self._conversion_ids.get(job_id, {})

    def get_next_conversion_id(self, job_id: str) -> str:
        return str(len(self._conversion_ids.get(job_id, {})) + 1)

    def set_choice(self, job_id: str, conv_id: str, choice: str) -> None:
        if job_id not in self._conversion_choices:
            self._conversion_choices[job_id] = {}
        self._conversion_choices[job_id][conv_id] = choice

    def get_choice(self, job_id: str, conv_id: str) -> str | None:
        return self._conversion_choices.get(job_id, {}).get(conv_id)

    def has_choice(self, job_id: str, conv_id: str) -> bool:
        return job_id in self._conversion_choices and conv_id in self._conversion_choices[job_id]

    def create_event(self, job_id: str, conv_id: str) -> asyncio.Event:
        if job_id not in self._conversion_events:
            self._conversion_events[job_id] = {}
        evt = asyncio.Event()
        self._conversion_events[job_id][conv_id] = evt
        return evt

    def get_event(self, job_id: str, conv_id: str) -> asyncio.Event | None:
        return self._conversion_events.get(job_id, {}).get(conv_id)

    def set_event(self, job_id: str, conv_id: str) -> bool:
        evt = self.get_event(job_id, conv_id)
        if evt:
            evt.set()
            return True
        return False

    def is_event_set(self, job_id: str, conv_id: str) -> bool:
        evt = self.get_event(job_id, conv_id)
        return evt.is_set() if evt else False

    def add_converted_file(self, job_id: str, filename: str) -> None:
        if job_id not in self._converted_files:
            self._converted_files[job_id] = set()
        self._converted_files[job_id].add(filename)

    def get_converted_files(self, job_id: str) -> set[str]:
        return self._converted_files.get(job_id, set())

    def pop_job(self, job_id: str) -> None:
        """Clears all conversion tracking entries across all dictionaries at once."""
        self._conversion_ids.pop(job_id, None)
        self._conversion_events.pop(job_id, None)
        self._conversion_choices.pop(job_id, None)
        self._converted_files.pop(job_id, None)

    def contains_job(self, job_id: str) -> bool:
        return (
            job_id in self._conversion_ids
            or job_id in self._conversion_choices
            or job_id in self._conversion_events
            or job_id in self._converted_files
        )


conversion_session_store = ConversionSessionStore()
