"""The philosophy is written in four places. This keeps them from drifting apart."""

from __future__ import annotations

import unittest
from pathlib import Path

from fuzzy_journey.philosophy import IDEAS, MANTRA, PRACTICES

ROOT = Path(__file__).resolve().parent.parent


class PhilosophyInSyncTests(unittest.TestCase):
    def test_readme_leads_with_the_mantra_and_names_every_idea(self):
        # The README condenses each idea; PHILOSOPHY.md carries the full wording.
        text = ROOT.joinpath("README.md").read_text(encoding="utf-8")
        for line in MANTRA:
            self.assertIn(f"**{line}**", text)
        for idea in IDEAS:
            self.assertIn(f"| **{idea.title}** |", text, f"README is missing idea {idea.number}")

    def test_philosophy_md_contains_every_word_the_app_shows(self):
        text = ROOT.joinpath("PHILOSOPHY.md").read_text(encoding="utf-8")
        self.assertIn(" ".join(MANTRA), text)
        for idea in (*IDEAS, *PRACTICES):
            for part in (idea.title, idea.summary, idea.detail):
                self.assertIn(part, text, f"PHILOSOPHY.md is missing: {part}")

    def test_changelog_mentions_current_version(self):
        from fuzzy_journey.meta import VERSION

        self.assertIn(f"## {VERSION}", ROOT.joinpath("CHANGELOG.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
