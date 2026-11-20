"""The Idea Bank: a place to drop a new idea in a few seconds, and an order that says what to follow up first.

An idea is only a line of text, plus an optional note you can add later. Capturing one never asks for
anything else: type it, press Enter, and it is saved at the bottom of the list. The list *is* the
priority: the idea at the top is the one to follow up first, and you drag ideas up or down to change that.

Nothing here touches the day's arithmetic: ideas are never tasks, never focus time, never part of the bank.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_TITLE = 160
MAX_NOTE = 4000
MAX_IDEAS = 500

IDEAS_INTRO = (
    "Drop a new idea here the moment you have it, without stopping to work it out. Drag ideas to put the one "
    "you must follow up first at the top. Nothing here changes the schedule."
)


@dataclass
class Idea:
    """One idea. ``position`` is its place in the order: 0 is the one to follow up first."""

    title: str
    note: str = ""
    id: int | None = None
    position: int = 0


def check_idea(title: str, note: str = "") -> str | None:
    """Why an idea cannot be saved, or None when it is fine."""
    if not title.strip():
        return "Write the idea first."
    if len(title.strip()) > MAX_TITLE:
        return f"Keep the idea under {MAX_TITLE} characters. Put the rest in the note."
    if len(note) > MAX_NOTE:
        return f"Keep the note under {MAX_NOTE} characters."
    return None


def reordered(ids: list[int], moving: int, target: int, after: bool) -> list[int]:
    """``ids`` with ``moving`` taken out and put just before (or, with ``after``, just after) ``target``.

    Unknown ids, or dropping an idea on itself, leave the order as it was.
    """
    if moving == target or moving not in ids or target not in ids:
        return list(ids)
    rest = [i for i in ids if i != moving]
    at = rest.index(target) + (1 if after else 0)
    return rest[:at] + [moving] + rest[at:]
