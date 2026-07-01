"""Daily-artwork persistence (kept separate from device/account repo)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from .db import get_connection
from .repositories import now_iso

READY = "ready"
FAILED = "failed"


@dataclass(frozen=True)
class DailyArtwork:
    device_id: str
    date: str
    image_path: Optional[str]
    archive_path: Optional[str]
    event_text_en: Optional[str]
    event_text_he: Optional[str]
    weather_summary: Optional[str]
    status: str
    created_at: str
    orientation: Optional[str] = None
    image_prompt: Optional[str] = None
    event_caption: Optional[str] = None
    event_visual: Optional[str] = None

    @staticmethod
    def from_row(row: sqlite3.Row) -> "DailyArtwork":
        return DailyArtwork(**{k: row[k] for k in row.keys()})


def upsert(artwork: DailyArtwork) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO daily_artwork
               (device_id, date, image_path, archive_path, event_text_en,
                event_text_he, weather_summary, orientation, image_prompt,
                event_caption, event_visual, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(device_id, date) DO UPDATE SET
                 image_path = excluded.image_path,
                 archive_path = excluded.archive_path,
                 event_text_en = excluded.event_text_en,
                 event_text_he = excluded.event_text_he,
                 weather_summary = excluded.weather_summary,
                 orientation = excluded.orientation,
                 image_prompt = excluded.image_prompt,
                 event_caption = excluded.event_caption,
                 event_visual = excluded.event_visual,
                 status = excluded.status""",
            (
                artwork.device_id, artwork.date, artwork.image_path,
                artwork.archive_path, artwork.event_text_en, artwork.event_text_he,
                artwork.weather_summary, artwork.orientation, artwork.image_prompt,
                artwork.event_caption, artwork.event_visual, artwork.status,
                artwork.created_at,
            ),
        )


def get(device_id: str, date: str) -> Optional[DailyArtwork]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_artwork WHERE device_id = ? AND date = ?",
            (device_id, date),
        ).fetchone()
        return DailyArtwork.from_row(row) if row else None


def latest_ready(device_id: str) -> Optional[DailyArtwork]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM daily_artwork WHERE device_id = ? AND status = ?
               ORDER BY date DESC LIMIT 1""",
            (device_id, READY),
        ).fetchone()
        return DailyArtwork.from_row(row) if row else None


def list_archive(device_id: str, limit: int = 30) -> list[DailyArtwork]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_artwork WHERE device_id = ? AND status = ?
               ORDER BY date DESC LIMIT ?""",
            (device_id, READY, limit),
        ).fetchall()
        return [DailyArtwork.from_row(r) for r in rows]


def list_all_ready(limit: int = 200) -> list[DailyArtwork]:
    """Every ready artwork across all devices, newest first (admin gallery)."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_artwork WHERE status = ?
               ORDER BY created_at DESC LIMIT ?""",
            (READY, limit),
        ).fetchall()
        return [DailyArtwork.from_row(r) for r in rows]


def count_by_day(days: int = 30) -> list[dict]:
    """Ready-artwork counts per calendar day (usage graph)."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n
               FROM daily_artwork WHERE status = ?
               GROUP BY day ORDER BY day DESC LIMIT ?""",
            (READY, days),
        ).fetchall()
        return [dict(r) for r in rows][::-1]


def counts() -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS ready
               FROM daily_artwork""",
            (READY,),
        ).fetchone()
        return dict(row)


def make_now() -> str:
    return now_iso()
