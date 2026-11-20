"""The Idea Bank: quick capture, an order you set, and an upgrade that adds it without touching anything else."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fuzzy_journey.database import SCHEMA_VERSION, Database
from fuzzy_journey.ideas import MAX_IDEAS, MAX_NOTE, MAX_TITLE, Idea, check_idea, reordered

from .helpers import DbTestCase


class CheckTests(unittest.TestCase):
    def test_only_the_idea_itself_is_required(self):
        self.assertIsNone(check_idea("A podcast about habits"))
        self.assertIsNotNone(check_idea("   "))
        self.assertIsNotNone(check_idea("x" * (MAX_TITLE + 1)))
        self.assertIsNone(check_idea("x" * MAX_TITLE))
        self.assertIsNotNone(check_idea("ok", "n" * (MAX_NOTE + 1)))


class ReorderTests(unittest.TestCase):
    def test_before_and_after_a_target(self):
        ids = [1, 2, 3, 4]
        self.assertEqual(reordered(ids, 4, 1, after=False), [4, 1, 2, 3])
        self.assertEqual(reordered(ids, 1, 3, after=True), [2, 3, 1, 4])
        self.assertEqual(reordered(ids, 1, 4, after=True), [2, 3, 4, 1])
        self.assertEqual(reordered(ids, 3, 2, after=False), [1, 3, 2, 4])

    def test_nothing_to_do_leaves_the_order_alone(self):
        ids = [1, 2, 3]
        self.assertEqual(reordered(ids, 2, 2, after=True), ids)  # dropped on itself
        self.assertEqual(reordered(ids, 9, 1, after=True), ids)  # an idea that no longer exists
        self.assertEqual(reordered(ids, 1, 9, after=False), ids)
        self.assertEqual(reordered(ids, 2, 1, after=True), ids)  # already just after it


class StoreTests(DbTestCase):
    def add(self, *titles):
        out = []
        for title in titles:
            idea = Idea(title)
            self.db.save_idea(idea)
            out.append(idea)
        return out

    def titles(self):
        return [i.title for i in self.db.list_ideas()]

    def test_a_new_database_has_no_ideas(self):
        self.assertEqual(self.db.list_ideas(), [])

    def test_a_new_idea_goes_to_the_bottom_with_no_other_detail(self):
        a, b, c = self.add("first", "second", "third")
        self.assertEqual(self.titles(), ["first", "second", "third"])
        self.assertEqual((a.position, b.position, c.position), (0, 1, 2))
        self.assertEqual(self.db.list_ideas()[0].note, "")

    def test_blank_space_is_tidied_and_empty_ideas_are_refused(self):
        (idea,) = self.add("  a   spaced \n idea ")
        self.assertEqual(idea.title, "a spaced idea")
        with self.assertRaises(ValueError):
            self.db.save_idea(Idea("   "))
        self.assertEqual(len(self.db.list_ideas()), 1)

    def test_editing_keeps_the_place_in_the_order(self):
        a, b, c = self.add("a", "b", "c")
        b.title, b.note = "b renamed", "more detail"
        self.db.save_idea(b)
        self.assertEqual(self.titles(), ["a", "b renamed", "c"])
        self.assertEqual(self.db.list_ideas()[1].note, "more detail")

    def test_move_up_and_down_stop_at_the_ends(self):
        a, b, c = self.add("a", "b", "c")
        self.assertTrue(self.db.move_idea(c, -1))
        self.assertEqual(self.titles(), ["a", "c", "b"])
        self.assertTrue(self.db.move_idea(a, 1))
        self.assertEqual(self.titles(), ["c", "a", "b"])
        self.assertFalse(self.db.move_idea(c, -1))  # already first
        self.assertFalse(self.db.move_idea(b, 1))  # already last
        self.assertFalse(self.db.move_idea(Idea("never saved"), 1))

    def test_dragging_one_idea_onto_another(self):
        a, b, c, d = self.add("a", "b", "c", "d")
        self.assertTrue(self.db.drop_idea(d.id, a.id, after=False))  # to the very top
        self.assertEqual(self.titles(), ["d", "a", "b", "c"])
        self.assertTrue(self.db.drop_idea(d.id, c.id, after=True))  # to the very bottom
        self.assertEqual(self.titles(), ["a", "b", "c", "d"])
        self.assertTrue(self.db.drop_idea(c.id, a.id, after=True))  # into the middle
        self.assertEqual(self.titles(), ["a", "c", "b", "d"])

    def test_a_drop_that_changes_nothing_says_so(self):
        a, b = self.add("a", "b")
        self.assertFalse(self.db.drop_idea(a.id, a.id, after=True))
        self.assertFalse(self.db.drop_idea(a.id, b.id, after=False))  # already just before it
        self.assertFalse(self.db.drop_idea(999, a.id, after=False))
        self.assertEqual(self.titles(), ["a", "b"])

    def test_the_order_is_dense_after_every_change(self):
        a, b, c, d = self.add("a", "b", "c", "d")
        self.db.delete_idea(b.id)
        self.db.drop_idea(d.id, a.id, after=False)
        self.assertEqual([i.position for i in self.db.list_ideas()], [0, 1, 2])
        self.assertEqual(self.titles(), ["d", "a", "c"])

    def test_a_new_idea_after_a_delete_still_goes_last(self):
        a, b, c = self.add("a", "b", "c")
        self.db.delete_idea(c.id)
        (e,) = self.add("e")
        self.assertEqual(self.titles(), ["a", "b", "e"])

    def test_the_bank_has_a_limit(self):
        with self.db.transaction() as conn:
            conn.executemany(
                "INSERT INTO ideas(title, note, position, created_at, updated_at) VALUES (?, '', ?, 'x', 'x')",
                [(f"i{n}", n) for n in range(MAX_IDEAS)],
            )
        with self.assertRaises(ValueError):
            self.db.save_idea(Idea("one too many"))


class UpgradeTests(unittest.TestCase):
    def test_a_version_10_database_gains_an_empty_bank_and_keeps_its_habits(self):
        from fuzzy_journey import database

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            db = Database(path)
            with db.transaction() as conn:
                conn.execute("DROP TABLE ideas")
                conn.execute("PRAGMA user_version = 10")
                conn.execute("INSERT INTO habits(name, kind, start_date, position, created_at) "
                             "VALUES ('Reading', 'build', '2026-11-01', 0, 'x')")
            self.assertEqual(SCHEMA_VERSION, 11)
            upgraded = Database(path)
            self.assertEqual(upgraded.list_ideas(), [])
            self.assertEqual([h.name for h in upgraded.list_habits()], ["Reading"])
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], database.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
