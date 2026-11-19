"""Personal rules and the recovery plan: stored, ordered, edited and seeded exactly once."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fuzzy_journey.database import SCHEMA_VERSION, Database
from fuzzy_journey.principles import (
    DEFAULT_RECOVERY,
    DEFAULT_RULES,
    MAX_BODY,
    MAX_TITLE,
    SECTION_RECOVERY,
    SECTION_RULES,
    Principle,
    check_principle,
)

from .helpers import DbTestCase


class SeedTests(DbTestCase):
    def test_a_new_database_starts_with_the_default_rules_and_recovery_steps(self):
        rules = self.db.list_principles(SECTION_RULES)
        self.assertEqual([r.title for r in rules], [d.title for d in DEFAULT_RULES])
        self.assertEqual(rules[0].title, "Computer-use boundary")
        self.assertEqual(
            rules[0].lines,
            [
                "The PC is for work only.",
                "Outside work time the PC must be off. Inside work time it is used only for work.",
                "No chatting with friends or casual entertainment.",
                "Small, necessary customer conversations are allowed.",
            ],
        )
        self.assertEqual([r.title for r in self.db.list_principles(SECTION_RECOVERY)], [d.title for d in DEFAULT_RECOVERY])

    def test_the_default_rules_cover_disruption_mode_and_brain_first_planning(self):
        by_title = {r.title: r for r in self.db.list_principles(SECTION_RULES)}
        self.assertTrue(any("25%" in line for line in by_title["Disruption Mode"].lines))
        self.assertTrue(any("brain" in line for line in by_title["Brain-first planning"].lines))

    def test_deleted_defaults_stay_deleted_after_reopening_the_database(self):
        for rule in self.db.list_principles(SECTION_RULES):
            self.db.delete_principle(rule.id)
        again = Database(self.db.path)
        self.assertEqual(again.list_principles(SECTION_RULES), [])
        self.assertEqual(len(again.list_principles(SECTION_RECOVERY)), len(DEFAULT_RECOVERY))

    def test_a_v6_database_is_upgraded_and_keeps_its_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v6.sqlite3"
            old = Database(path)
            old.settings.set("theme", "dark")
            with old.connection() as conn:  # roll the file back to what a 2.0.0 database looks like
                conn.execute("DROP TABLE principles")
                conn.execute("PRAGMA user_version = 6")
            upgraded = Database(path)
            self.assertEqual(upgraded.settings.theme, "dark")
            self.assertEqual(len(upgraded.list_principles(SECTION_RULES)), len(DEFAULT_RULES))
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)


class EditingTests(DbTestCase):
    def test_a_new_rule_goes_to_the_end_of_its_own_section_only(self):
        rule_id = self.db.save_principle(Principle(SECTION_RULES, "  Sleep before midnight ", "Phone off at 23:00.\n\n"))
        rules = self.db.list_principles(SECTION_RULES)
        self.assertEqual(rules[-1].id, rule_id)
        self.assertEqual((rules[-1].title, rules[-1].body), ("Sleep before midnight", "Phone off at 23:00."))
        self.assertEqual(len(self.db.list_principles(SECTION_RECOVERY)), len(DEFAULT_RECOVERY))

    def test_editing_keeps_the_position(self):
        first = self.db.list_principles(SECTION_RULES)[0]
        first.title, first.body = "PC for work", "Work only."
        self.db.save_principle(first)
        again = self.db.list_principles(SECTION_RULES)[0]
        self.assertEqual((again.id, again.title, again.body), (first.id, "PC for work", "Work only."))

    def test_moving_changes_the_order_and_stops_at_the_ends(self):
        steps = self.db.list_principles(SECTION_RECOVERY)
        self.assertFalse(self.db.move_principle(steps[0], -1))
        self.assertFalse(self.db.move_principle(steps[-1], 1))
        self.assertTrue(self.db.move_principle(steps[0], 1))
        titles = [s.title for s in self.db.list_principles(SECTION_RECOVERY)]
        self.assertEqual(titles[:2], [steps[1].title, steps[0].title])
        self.assertTrue(self.db.move_principle(steps[0], -1))
        self.assertEqual([s.title for s in self.db.list_principles(SECTION_RECOVERY)], [s.title for s in steps])

    def test_moving_never_crosses_into_another_section(self):
        last_rule = self.db.list_principles(SECTION_RULES)[-1]
        self.assertFalse(self.db.move_principle(last_rule, 1))

    def test_delete_removes_only_that_entry(self):
        rules = self.db.list_principles(SECTION_RULES)
        self.db.delete_principle(rules[1].id)
        self.assertEqual([r.title for r in self.db.list_principles(SECTION_RULES)], [rules[0].title, rules[2].title])

    def test_an_invalid_entry_is_refused_and_nothing_is_written(self):
        before = len(self.db.list_principles(SECTION_RULES))
        with self.assertRaises(ValueError):
            self.db.save_principle(Principle(SECTION_RULES, "   ", "text"))
        self.assertEqual(len(self.db.list_principles(SECTION_RULES)), before)


class ValidationTests(unittest.TestCase):
    def test_check_principle(self):
        self.assertIsNone(check_principle(SECTION_RULES, "Rule", ""))
        self.assertIsNotNone(check_principle(SECTION_RULES, " ", "x"))
        self.assertIsNotNone(check_principle(SECTION_RULES, "x" * (MAX_TITLE + 1), ""))
        self.assertIsNotNone(check_principle(SECTION_RULES, "Rule", "x" * (MAX_BODY + 1)))
        self.assertIsNotNone(check_principle("elsewhere", "Rule", ""))

    def test_lines_skip_blanks_and_trim(self):
        self.assertEqual(Principle(SECTION_RULES, "t", " a \n\n b\n").lines, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
