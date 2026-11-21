"""Goals (one great goal and its horizons) and the self-image: the words, the order, and the upgrade."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fuzzy_journey.database import SCHEMA_VERSION, Database
from fuzzy_journey.goals import (
    KIND_GREAT,
    KIND_HORIZON,
    MAX_HORIZONS,
    MAX_STATEMENT,
    MAX_TITLE,
    Goal,
    SelfStatement,
    check_goal,
    check_self,
    next_horizon,
    reached_count,
    speaks_of_the_future,
)

from .helpers import DbTestCase


class CheckTests(unittest.TestCase):
    def test_a_goal_needs_a_title_of_sensible_length(self):
        self.assertIsNone(check_goal(KIND_GREAT, "A free life"))
        self.assertIsNotNone(check_goal(KIND_HORIZON, "   "))
        self.assertIsNotNone(check_goal(KIND_HORIZON, "x" * (MAX_TITLE + 1)))
        self.assertIsNotNone(check_goal("other", "A free life"))

    def test_a_statement_must_not_begin_as_a_promise_or_a_wish(self):
        for text in ("I will have money", "I’ll be calm", "I want to be free", "I am going to be rich",
                     "i wish I had time", "One day I am free", "I hope it works", "  I  will   win "):
            self.assertTrue(speaks_of_the_future(text), text)
            self.assertIsNotNone(check_self(text), text)

    def test_present_tense_statements_pass(self):
        for text in ("I am calm", "I have full control over my life", "I know what I want",
                     "My loved ones are safe", "I willingly rest", "I wanted nothing yesterday"):
            self.assertFalse(speaks_of_the_future(text), text)
            self.assertIsNone(check_self(text), text)

    def test_a_statement_needs_words_and_a_limit(self):
        self.assertIsNotNone(check_self("  "))
        self.assertIsNotNone(check_self("I am " + "x" * MAX_STATEMENT))


class GoalStoreTests(DbTestCase):
    def test_a_new_database_has_no_goals_and_nothing_is_seeded(self):
        self.assertIsNone(self.db.great_goal())
        self.assertEqual(self.db.horizons(), [])
        self.assertEqual(self.db.list_self_image(), [])

    def test_there_is_only_one_great_goal(self):
        self.db.save_goal(Goal(KIND_GREAT, "First words"))
        self.db.save_goal(Goal(KIND_GREAT, "  Better   words ", "Because."))
        great = self.db.great_goal()
        self.assertEqual((great.title, great.note), ("Better words", "Because."))
        with self.db.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM goals WHERE kind='great'").fetchone()[0], 1)

    def test_horizons_keep_the_order_they_were_added_in_and_can_be_moved(self):
        a, b, c = (Goal(KIND_HORIZON, t) for t in "abc")
        for goal in (a, b, c):
            self.db.save_goal(goal)
        self.assertEqual([h.title for h in self.db.horizons()], ["a", "b", "c"])
        self.assertTrue(self.db.move_horizon(c, -1))
        self.assertEqual([h.title for h in self.db.horizons()], ["a", "c", "b"])
        self.assertFalse(self.db.move_horizon(a, -1))  # already first
        self.assertFalse(self.db.move_horizon(b, 1))  # already last

    def test_reaching_a_horizon_is_reversible_and_does_not_reorder(self):
        a, b = Goal(KIND_HORIZON, "a"), Goal(KIND_HORIZON, "b")
        self.db.save_goal(a)
        self.db.save_goal(b)
        self.db.set_horizon_reached(a.id, True)
        horizons = self.db.horizons()
        self.assertEqual(reached_count(horizons), (1, 2))
        self.assertEqual(next_horizon(horizons).title, "b")
        self.db.set_horizon_reached(a.id, False)
        self.assertEqual(reached_count(self.db.horizons()), (0, 2))
        self.assertEqual(next_horizon(self.db.horizons()).title, "a")

    def test_the_great_goal_cannot_be_marked_reached(self):
        great = Goal(KIND_GREAT, "Free")
        self.db.save_goal(great)
        self.db.set_horizon_reached(great.id, True)
        self.assertFalse(self.db.great_goal().reached)

    def test_removing_the_great_goal_keeps_the_horizons(self):
        great = Goal(KIND_GREAT, "Free")
        self.db.save_goal(great)
        self.db.save_goal(Goal(KIND_HORIZON, "Debt free"))
        self.db.delete_goal(great.id)
        self.assertIsNone(self.db.great_goal())
        self.assertEqual([h.title for h in self.db.horizons()], ["Debt free"])

    def test_invalid_goals_are_refused(self):
        with self.assertRaises(ValueError):
            self.db.save_goal(Goal(KIND_HORIZON, ""))

    def test_there_is_a_limit_on_horizons(self):
        for n in range(MAX_HORIZONS):
            self.db.save_goal(Goal(KIND_HORIZON, f"h{n}"))
        with self.assertRaises(ValueError):
            self.db.save_goal(Goal(KIND_HORIZON, "one too many"))


class SelfImageStoreTests(DbTestCase):
    def test_statements_are_stored_in_order_and_can_be_edited_moved_and_deleted(self):
        a, b = SelfStatement("I am calm"), SelfStatement("I have enough", "Warm and light.")
        self.db.save_self_statement(a)
        self.db.save_self_statement(b)
        self.assertEqual([s.statement for s in self.db.list_self_image()], ["I am calm", "I have enough"])
        self.assertTrue(self.db.move_self_statement(b, -1))
        self.assertEqual([s.statement for s in self.db.list_self_image()], ["I have enough", "I am calm"])
        a.statement = "I am very calm"
        self.db.save_self_statement(a)
        self.assertEqual(self.db.list_self_image()[1].statement, "I am very calm")
        self.db.delete_self_statement(a.id)
        self.assertEqual([s.feeling for s in self.db.list_self_image()], ["Warm and light."])

    def test_the_database_refuses_a_statement_about_the_future(self):
        with self.assertRaises(ValueError):
            self.db.save_self_statement(SelfStatement("I will be free"))
        self.assertEqual(self.db.list_self_image(), [])


class UpgradeTests(unittest.TestCase):
    def test_a_v12_database_is_upgraded_and_keeps_its_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v12.sqlite3"
            old = Database(path)
            old.settings.set("theme", "dark")
            with old.connection() as conn:  # roll the file back to what the previous version made
                conn.execute("DROP TABLE goals")
                conn.execute("DROP TABLE self_image")
                conn.execute("PRAGMA user_version = 12")
            upgraded = Database(path)
            self.assertEqual(upgraded.settings.theme, "dark")
            self.assertIsNone(upgraded.great_goal())
            self.assertEqual(upgraded.list_self_image(), [])
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_goals_survive_a_backup_and_restore(self):
        from fuzzy_journey import backup

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "a.sqlite3")
            db.save_goal(Goal(KIND_GREAT, "A free life"))
            db.save_goal(Goal(KIND_HORIZON, "Debt free"))
            db.save_self_statement(SelfStatement("I am calm"))
            archive = Path(tmp) / "b.zip"
            backup.create_backup(db, archive)
            with sqlite3.connect(db.path) as conn:  # the snapshot itself must hold the new tables
                names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertLessEqual({"goals", "self_image"}, names)
            self.assertEqual(backup.read_backup_info(archive).schema, SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()


class AnchorTests(DbTestCase):
    def test_the_anchor_asks_you_to_say_it_first_by_default(self):
        from fuzzy_journey.goals import ANCHOR_MODES, ANCHOR_TAP

        self.assertEqual(self.db.settings.anchor_mode, ANCHOR_TAP)
        for mode in ANCHOR_MODES:
            self.db.settings.anchor_mode = mode
            self.assertEqual(self.db.settings.anchor_mode, mode)
        self.db.settings.anchor_mode = "nonsense"
        self.assertEqual(self.db.settings.anchor_mode, ANCHOR_TAP)

    def test_the_statement_of_the_day_is_steady_all_day_and_comes_round(self):
        from datetime import date, timedelta

        from fuzzy_journey.goals import SelfStatement, statement_of_the_day

        self.assertIsNone(statement_of_the_day([], date(2026, 11, 2)))
        items = [SelfStatement(f"I am {n}") for n in range(3)]
        start = date(2026, 11, 2)
        seen = [statement_of_the_day(items, start + timedelta(days=n)).statement for n in range(3)]
        self.assertEqual(sorted(seen), sorted(i.statement for i in items))  # none is favoured
        self.assertEqual(statement_of_the_day(items, start), statement_of_the_day(items, start))
        self.assertEqual(statement_of_the_day(items, start), statement_of_the_day(items, start + timedelta(days=3)))
