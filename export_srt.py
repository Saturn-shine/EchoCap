"""
Convert transcripts.txt to SubRip (.srt) subtitle format.
"""

import logging
import os
import re
from datetime import timedelta

logger = logging.getLogger(__name__)

# Line format: [HH:MM:SS] EN text  |  ZH text
LINE_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+(.+)$")


def _parse_time(t_str):
    parts = t_str.strip().split(":")
    return timedelta(hours=int(parts[0]), minutes=int(parts[1]),
                     seconds=int(parts[2]))


def _format_timedelta(td):
    total_sec = int(td.total_seconds())
    ms = int((td.total_seconds() - total_sec) * 1000)
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def export_srt(transcripts_path, output_path, default_gap_s=3.0):
    """Parse transcripts.txt and write an SRT file.

    Each entry's end time is the next entry's start time.
    The last entry gets default_gap_s added.
    """
    entries = []
    with open(transcripts_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = LINE_RE.match(line)
            if not m:
                continue
            time_str, text = m.group(1), m.group(2).strip()
            if not text:
                continue
            entries.append((_parse_time(time_str), text))

    if not entries:
        raise ValueError("No parseable entries found in transcript file.")

    with open(output_path, "w", encoding="utf-8") as f:
        for i, (start, text) in enumerate(entries):
            if i + 1 < len(entries):
                end = entries[i + 1][0]
            else:
                end = start + timedelta(seconds=default_gap_s)

            f.write(f"{i + 1}\n")
            f.write(f"{_format_timedelta(start)} --> {_format_timedelta(end)}\n")
            f.write(f"{text}\n\n")

    logger.info("Exported %d entries to %s", len(entries), output_path)
    return len(entries)
