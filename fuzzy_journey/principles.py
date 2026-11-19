"""Personal rules and the recovery plan: words the person writes, not arithmetic.

Two pages share one small store. **Rules** are the must-do rules of a life
(``SECTION_RULES``); the **Recovery** plan is an ordered list of steps
(``SECTION_RECOVERY``). Nothing here touches the day's arithmetic: no rule in
:mod:`fuzzy_journey.rhythm`, :mod:`~fuzzy_journey.pomodoro` or
:mod:`~fuzzy_journey.tasks` reads these entries.

The defaults below are only a starting point, written once when the table is
created. After that the text belongs to the person: every entry can be edited,
reordered or deleted, and deleting one is never undone by an upgrade.
"""

from __future__ import annotations

from dataclasses import dataclass

SECTION_RULES = "rules"
SECTION_RECOVERY = "recovery"
SECTIONS = (SECTION_RULES, SECTION_RECOVERY)

MAX_TITLE = 80
MAX_BODY = 2000


@dataclass
class Principle:
    """One rule, or one step of the recovery plan. A body's lines are shown as bullet points."""

    section: str
    title: str
    body: str = ""
    id: int | None = None
    position: int = 0

    @property
    def lines(self) -> list[str]:
        return [line.strip() for line in self.body.splitlines() if line.strip()]


def check_principle(section: str, title: str, body: str) -> str | None:
    """Why an entry cannot be saved, or None when it is fine."""
    if section not in SECTIONS:
        return "Unknown section."
    if not title.strip():
        return "Give it a short title."
    if len(title.strip()) > MAX_TITLE:
        return f"Keep the title under {MAX_TITLE} characters."
    if len(body) > MAX_BODY:
        return f"Keep the text under {MAX_BODY} characters."
    return None


# --------------------------------------------------------------------------
# Starting content
# --------------------------------------------------------------------------

#: The rules page starts with these; the person is expected to rewrite and add to them.
DEFAULT_RULES: tuple[Principle, ...] = (
    Principle(
        SECTION_RULES,
        "Computer-use boundary",
        "The PC is for work only.\n"
        "Outside work time the PC must be off. Inside work time it is used only for work.\n"
        "No chatting with friends or casual entertainment.\n"
        "Small, necessary customer conversations are allowed.",
    ),
    Principle(
        SECTION_RULES,
        "Disruption Mode",
        "Reduced workload starts at 25% of the normal daily workload.\n"
        "Prayers, exercise, book reading, and other routine activities remain required, even on 25% days.\n"
        "If I cannot manage even that, the fallback is staying home, resting or sleeping, "
        "or remaining completely offline with the PC off.",
    ),
    Principle(
        SECTION_RULES,
        "Brain-first planning",
        "The plan must primarily live in my brain.\n"
        "Fuzzy Journey is a reminder and safety check, not the primary place where the plan exists.\n"
        "The recovery plan must be independently remembered and executable without a computer.",
    ),
)

#: The first wording of the computer rule (schema 7). Schema 8 replaces it with the current one, but only
#: where the person never changed it.
FIRST_COMPUTER_RULE = (
    "The PC is for work only.\n"
    "No chatting with friends or casual entertainment.\n"
    "Small, necessary customer conversations are allowed."
)

#: The recovery plan starts with these steps, in order.
DEFAULT_RECOVERY: tuple[Principle, ...] = (
    Principle(
        SECTION_RECOVERY,
        "Stop the spiral",
        "Do not call the whole day ruined, keep analysing, or escape into distractions. "
        "Pause and choose the next sensible action.",
    ),
    Principle(
        SECTION_RECOVERY,
        "Check reality",
        "Am I ill, exhausted, unsafe, grieving, or facing a real emergency? "
        "Health, safety and urgent responsibilities come first.",
    ),
    Principle(
        SECTION_RECOVERY,
        "Choose the scale",
        "Can function, but not a normal day: Disruption Mode.\n"
        "Cannot manage even that: an offline day. Rest, sleep or stay awake with the PC off.",
    ),
    Principle(
        SECTION_RECOVERY,
        "Return to the anchors",
        "Prayers at their proper times. Exercise, reading and the rest of the routine as health allows; "
        "adapt them when it does not.",
    ),
    Principle(
        SECTION_RECOVERY,
        "Reset simply",
        "Shower if it helps. Finish any remaining prayers. "
        "Prepare only tomorrow's essential plan, not hours of planning.",
    ),
    Principle(
        SECTION_RECOVERY,
        "Sleep, wake, start",
        "Sleep as soon as possible. Wake at the time Fuzzy Journey scheduled. "
        "Do the next planned action without waiting for a perfect plan or a perfect feeling.",
    ),
)

#: What the Recovery page says about itself.
RECOVERY_INTRO = (
    "Know these steps by heart. This page is only the backup, for refreshing the plan in your mind "
    "when you are calm, and for checking a detail you cannot remember. It must never be the only place "
    "the plan exists."
)
RULES_INTRO = "The must-do rules of your life, in your own words. Nothing here changes the schedule; it is for you to read."
