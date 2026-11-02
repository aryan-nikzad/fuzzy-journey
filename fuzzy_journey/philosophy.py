"""The ideas behind Fuzzy Journey, in one place.

Everything the app says about itself (the welcome screen, the Philosophy
dialog, the page captions) comes from here, so the wording never drifts.
README.md and PHILOSOPHY.md repeat the same text; a test keeps them in sync.

The rules below are not decoration. Each one is implemented in
:mod:`fuzzy_journey.rhythm`, and the docstring there says where.
"""

from __future__ import annotations

from dataclasses import dataclass

MANTRA = (
    "The day is given.",
    "Work a share.",
    "Bank the rest.",
    "Protect the night.",
)


@dataclass(frozen=True)
class Idea:
    number: int
    title: str
    summary: str
    detail: str


IDEAS = (
    Idea(
        1,
        MANTRA[0],
        "Fajr to Isha is your day.",
        "Prayer times, not arbitrary hours, set the edges of your day. "
        "Long summer days and short winter days both stay in proportion.",
    ),
    Idea(
        2,
        MANTRA[1],
        "Give work a share of the day, not a number of hours.",
        "A Steady day gives 50% of the day to work; a Push day gives 75%. "
        "Work fills the morning first, until 14:00. The afternoon stays yours, "
        "and the evening is used only for what overflows.",
    ),
    Idea(
        3,
        MANTRA[2],
        "Rest is earned, banked and spent.",
        "Each Push day banks half a day. Each Rest day spends a whole one, "
        "so two Push days buy one Rest day. The balance may go negative, "
        "but you always see it.",
    ),
    Idea(
        4,
        MANTRA[3],
        "Sleep is measured against the natural night.",
        "The night runs from Isha to the next Fajr. Evening work is the last "
        "resort, and its cost is shown honestly as sleep given up.",
    ),
)

PRACTICES = (
    Idea(
        5,
        "Count focus, not clock time.",
        "A call or an errand pauses the work clock.",
        "The finish moves later, but the amount of work stays whole.",
    ),
    Idea(
        6,
        "Keep it yours.",
        "Everything lives on this computer.",
        "No account, no cloud. Alarms ring without internet.",
    ),
)
