"""Goals and the self-image: words the person writes, not arithmetic.

**Goals** have two levels. There is one *great goal* (what the whole life is aimed at) and many
*horizons*: the sub-goals that must be reached first for the great goal to be possible. Horizons are kept
in the order to reach them, and each can be marked reached.

The **self-image** is a list of statements about who the person is, said in the present tense, as if
already true ("I have full control over my life"), so they can be felt and not only hoped for.

Nothing here touches the day's arithmetic: no rule in :mod:`fuzzy_journey.rhythm`,
:mod:`~fuzzy_journey.pomodoro` or :mod:`~fuzzy_journey.tasks` reads these entries, and there are no
scores or streaks. Nothing is seeded: every word is the person's own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

KIND_GREAT = "great"
KIND_HORIZON = "horizon"
KINDS = (KIND_GREAT, KIND_HORIZON)

MAX_TITLE = 120
MAX_NOTE = 2000
MAX_HORIZONS = 50

MAX_STATEMENT = 200
MAX_FEELING = 1000
MAX_STATEMENTS = 100

GOALS_INTRO = (
    "The one great goal your life is aimed at, and the horizons: what must be true first, in the order "
    "you will reach them. Nothing here changes the schedule; it is for you to read and to know."
)
SELF_INTRO = (
    "Who you are, said as if it is already true. Not “I will have the money I need” but “I have the money "
    "I need.” Say each one until you can feel it. Nothing here changes the schedule."
)
SELF_EXAMPLES = (
    "For example: “I have full control over my life.” “I have the money I need for what I need, and for "
    "the people I love.”"
)


@dataclass
class Goal:
    """The great goal (``kind`` great, at most one) or one horizon.

    ``reached`` only means something for a horizon. ``position`` orders the horizons: 0 is the first to reach.
    """

    kind: str
    title: str
    note: str = ""
    reached: bool = False
    id: int | None = None
    position: int = 0


@dataclass
class SelfStatement:
    """One sentence about who the person is, in the present tense, and how it feels when it is true."""

    statement: str
    feeling: str = ""
    id: int | None = None
    position: int = 0


def check_goal(kind: str, title: str, note: str = "") -> str | None:
    """Why a goal cannot be saved, or None when it is fine."""
    if kind not in KINDS:
        return "Unknown kind of goal."
    if not title.strip():
        return "Give it a short title."
    if len(title.strip()) > MAX_TITLE:
        return f"Keep the title under {MAX_TITLE} characters. Put the rest in the note."
    if len(note) > MAX_NOTE:
        return f"Keep the note under {MAX_NOTE} characters."
    return None


#: Ways of speaking about the future or a wish. A self-image statement must not begin with one.
NOT_YET = (
    "i will", "i'll", "i shall", "i want", "i wanna", "i wish", "i hope", "i would", "i'd", "i should",
    "i must", "i need to", "i plan", "i'm going to", "i am going to", "i'm gonna", "i am gonna",
    "i'm trying", "i am trying", "someday", "one day", "soon",
)
PRESENT_TENSE_HINT = "Say it as if it is already true. Instead of “I will…” or “I want…”, write “I am…” or “I have…”."


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace("’", "'").replace("‘", "'"))


def speaks_of_the_future(statement: str) -> bool:
    """True when a statement begins as a promise or a wish (“I will…”, “I want…”) instead of as a fact."""
    text = _normal(statement)
    return any(text == lead or text.startswith(lead + " ") for lead in NOT_YET)


def check_self(statement: str, feeling: str = "") -> str | None:
    """Why a self-image statement cannot be saved, or None when it is fine."""
    if not statement.strip():
        return "Write who you are, as if it is already true."
    if len(statement.strip()) > MAX_STATEMENT:
        return f"Keep the statement under {MAX_STATEMENT} characters. Put the rest in how it feels."
    if speaks_of_the_future(statement):
        return PRESENT_TENSE_HINT
    if len(feeling) > MAX_FEELING:
        return f"Keep the text under {MAX_FEELING} characters."
    return None


def reached_count(horizons: list[Goal]) -> tuple[int, int]:
    """(reached, total) for a list of horizons."""
    return sum(1 for h in horizons if h.reached), len(horizons)


def next_horizon(horizons: list[Goal]) -> Goal | None:
    """The first horizon, in order, that is not reached yet."""
    return next((h for h in horizons if not h.reached), None)


# -- the anchor on Today ---------------------------------------------------
#
# The plan should live in your head, not on a screen. So by default Today does not show your goal and
# self-image: it asks you to say them from memory and only then lets you check. Showing them outright,
# or not at all, are the two other choices. It is only a reading of your own words: it never changes the day.

ANCHOR_TAP = "tap"    # a cue; say it aloud, tap to check (the default, the same practice as Recall)
ANCHOR_SHOW = "show"  # the words are simply there
ANCHOR_OFF = "off"    # nothing on Today
ANCHOR_MODES = (ANCHOR_TAP, ANCHOR_SHOW, ANCHOR_OFF)
ANCHOR_LABELS = {
    ANCHOR_TAP: "Ask me to say them, then check",
    ANCHOR_SHOW: "Show them",
    ANCHOR_OFF: "Do not show them",
}


def statement_of_the_day(statements: list[SelfStatement], day: date) -> SelfStatement | None:
    """One self-image statement for a day. It stays the same all day and moves on to the next tomorrow,
    in the order the person keeps them, so each one comes round and none is favoured."""
    if not statements:
        return None
    return statements[day.toordinal() % len(statements)]
