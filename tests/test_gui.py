import ast
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

# test_wrangler first: importing it puts the repo root on sys.path.
from test_wrangler import HEADERS, data_tabs, row, write_partner_workbook

import wrangler_gui as gui


class GuiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.batch = self.root / "spring-batch"
        self.batch.mkdir()
        self.lines = []

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, ask=None, file_per_tab=False, replace=False):
        def never_asked(gap):
            raise AssertionError(f"unexpected question: {gap}")

        return gui.make_batch_import(
            self.batch, file_per_tab, ask or never_asked, self.lines.append, replace=replace
        )


class MakeBatchImportTests(GuiTestCase):
    def test_writes_batch_import_next_to_the_batch_and_shows_the_log(self):
        write_partner_workbook(self.batch, "md468.xlsx", [row("Summer 2026, MED 4", "MD468")])
        result = self.make()
        output = self.batch / "spring-batch-batch-import.xlsx"
        self.assertEqual(result.paths, [output])
        self.assertEqual(data_tabs(load_workbook(output)), ["Summer 2026, MED 4"])
        self.assertTrue(any("Run type: Check Run" in line for line in self.lines))

    def test_answers_to_the_portfolio_question_fill_the_blanks(self):
        no_portfolio = HEADERS[1:]
        write_partner_workbook(self.batch, "bio.xlsx", [row(None, "Intro to Biology")[1:]], no_portfolio)
        write_partner_workbook(self.batch, "anat.xlsx", [row(None, "Anatomy I")[1:]], no_portfolio)
        asked = []

        def ask(gap):
            asked.append(gap.kind)
            return {name: "Summer 2026, MED 4" for name in gap.courses}

        result = self.make(ask, file_per_tab=True)
        self.assertEqual(asked, ["none"])
        self.assertEqual(
            result.paths, [self.batch / "spring-batch-batch-import" / "Summer 2026, MED 4.xlsx"]
        )

    def test_giving_each_file_its_own_tab_writes_everything(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468")])
        write_partner_workbook(self.batch, "b.xlsx", [row(None, "MD300")])
        result = self.make(ask=lambda gap: gui.OWN_TABS)
        self.assertEqual(data_tabs(load_workbook(result.paths[0])), ["Summer 2026, MED 4", "b"])
        self.assertEqual(result.unassigned_tabs, 1)

    def test_cancelling_the_question_writes_nothing(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468")])
        write_partner_workbook(self.batch, "b.xlsx", [row(None, "MD300")])
        self.assertIsNone(self.make(ask=lambda gap: None))
        self.assertEqual(sorted(p.name for p in self.batch.iterdir()), ["a.xlsx", "b.xlsx"])

    def test_replacing_a_folder_of_files_waits_until_the_questions_are_answered(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468")])
        write_partner_workbook(self.batch, "b.xlsx", [row(None, "MD300")])
        old = self.batch / "spring-batch-batch-import"
        old.mkdir()
        (old / "Fall 2025, MED 4.xlsx").write_text("last term")

        self.assertIsNone(self.make(ask=lambda gap: None, file_per_tab=True, replace=True))
        self.assertTrue((old / "Fall 2025, MED 4.xlsx").exists())

        self.make(ask=lambda gap: {"b.xlsx": "Summer 2026, MED 4"}, file_per_tab=True, replace=True)
        self.assertEqual([p.name for p in old.iterdir()], ["Summer 2026, MED 4.xlsx"])

    def test_a_folder_without_workbooks_says_so(self):
        with self.assertRaises(SystemExit) as stopped:
            self.make()
        self.assertIn("No .xlsx workbooks found", str(stopped.exception.code))


class FirstOpenTests(GuiTestCase):
    def test_instructions_show_only_on_first_open(self):
        marker = self.root / "support" / "instructions-seen"
        self.assertTrue(gui.first_open(marker))
        self.assertFalse(gui.first_open(marker))


class SettingsTests(GuiTestCase):
    def test_remembers_folder_and_output_choice(self):
        path = self.root / "support" / "settings.json"
        gui.save_settings(path, gui.Settings(folder=self.batch, file_per_tab=True))
        self.assertEqual(gui.load_settings(path), gui.Settings(folder=self.batch, file_per_tab=True))

    def test_falls_back_to_downloads(self):
        missing = gui.load_settings(self.root / "nothing-here.json")
        self.assertEqual(missing, gui.Settings(folder=Path.home() / "Downloads", file_per_tab=False))

        path = self.root / "settings.json"
        gui.save_settings(path, gui.Settings(folder=self.root / "moved-away", file_per_tab=False))
        self.assertEqual(gui.load_settings(path).folder, Path.home() / "Downloads")


class ExistingOutputTests(GuiTestCase):
    def test_finds_only_the_output_this_run_would_replace(self):
        self.assertIsNone(gui.existing_output(self.batch, file_per_tab=False))
        (self.batch / "older_schedule-import.xlsx").write_text("x")
        self.assertIsNone(gui.existing_output(self.batch, file_per_tab=False))

        existing = self.batch / "spring-batch-batch-import.xlsx"
        existing.write_text("x")
        self.assertEqual(gui.existing_output(self.batch, file_per_tab=False), existing)
        self.assertIsNone(gui.existing_output(self.batch, file_per_tab=True))

    def test_keeping_the_old_one_renames_it_so_it_is_never_read_as_input(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468")])
        first = self.make().paths[0]

        kept = gui.keep_old(first, datetime(2026, 10, 27, 14, 32))

        self.assertEqual(kept.name, "spring-batch-batch-import (previous 2026-10-27 1432).xlsx")
        self.assertFalse(first.exists())
        self.lines.clear()
        self.make()
        self.assertTrue(any("skipped 1 earlier output" in line for line in self.lines))

    def test_keeping_twice_in_the_same_minute_keeps_both(self):
        when = datetime(2026, 10, 27, 14, 32)
        existing = self.batch / "spring-batch-batch-import.xlsx"
        existing.write_text("first")
        gui.keep_old(existing, when)
        existing.write_text("second")
        kept = gui.keep_old(existing, when)
        self.assertEqual(kept.name, "spring-batch-batch-import (previous 2026-10-27 1432) 2.xlsx")
        self.assertEqual(len(list(self.batch.iterdir())), 2)

    def test_keeping_an_old_folder_of_files(self):
        folder = self.batch / "spring-batch-batch-import"
        folder.mkdir()
        self.assertEqual(gui.existing_output(self.batch, file_per_tab=True), folder)
        kept = gui.keep_old(folder, datetime(2026, 10, 27, 14, 32))
        self.assertEqual(kept.name, "spring-batch-batch-import (previous 2026-10-27 1432)")
        self.assertTrue(kept.is_dir())


class ShortPathTests(GuiTestCase):
    def test_home_becomes_a_tilde(self):
        self.assertEqual(gui.short_path(Path.home() / "Downloads" / "spring-batch"), "~/Downloads/spring-batch")

    def test_long_paths_keep_the_folder_name_and_drop_the_middle(self):
        path = Path("/Volumes/Shared/Partners/University of Somewhere/Medicine/2026/Spring/spring-batch")
        short = gui.short_path(path, limit=40)
        self.assertLessEqual(len(short), 40)
        self.assertTrue(short.startswith("/Volumes"))
        self.assertTrue(short.endswith("/Spring/spring-batch"))
        self.assertIn("...", short)


class WorkbookLabelTests(GuiTestCase):
    def test_lists_a_few_courses(self):
        self.assertEqual(gui.workbook_label("b.xlsx", ["MD300", "MD301"]), "b.xlsx (MD300, MD301)")
        self.assertEqual(gui.workbook_label("b.xlsx", []), "b.xlsx (no Course Name)")

    def test_long_course_lists_are_cut_short(self):
        label = gui.workbook_label("contacts.xlsx", [f"Person {n}" for n in range(731)])
        self.assertEqual(label, "contacts.xlsx (Person 0, Person 1, Person 2 and 728 more)")


class CalloutTests(GuiTestCase):
    def result(self, flagged=0, unreadable=0, terms=(), unassigned=0):
        return gui.wrangler.RunResult(
            paths=[], tabs=[], flagged_rows=flagged, unreadable_values=unreadable, terms=list(terms),
            unassigned_tabs=unassigned,
        )

    def test_nothing_to_call_out(self):
        self.assertEqual(gui.callout(self.result(terms=["Summer 2026"])), "")

    def test_calls_out_what_to_fix_before_import(self):
        text = gui.callout(self.result(flagged=2, unreadable=1, terms=["Summer 2026", "Spring 2026"]))
        self.assertIn("2 rows flagged red", text)
        self.assertIn("1 date or time could not be read", text)
        self.assertIn("Summer 2026 and Spring 2026", text)

    def test_calls_out_files_without_a_portfolio(self):
        self.assertIn("2 files had no Portfolio", gui.callout(self.result(unassigned=2)))
        self.assertIn("1 file had no Portfolio", gui.callout(self.result(unassigned=1)))

    def test_singular_and_plural(self):
        self.assertIn("1 row flagged red", gui.callout(self.result(flagged=1)))
        self.assertIn("3 dates or times could not be read", gui.callout(self.result(unreadable=3)))


class InstructionsTests(unittest.TestCase):
    """Every "quoted" label in the How to use text must be a real string in the
    window code, so the instructions never name a button that doesn't exist."""

    @staticmethod
    def window_strings():
        tree = ast.parse(Path(gui.__file__).read_text(encoding="utf-8"))
        skip = set()
        for node in tree.body:
            targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
            if any(getattr(t, "id", "") == "INSTRUCTIONS" for t in targets):
                skip = {id(n) for n in ast.walk(node)}
        assert skip, "INSTRUCTIONS assignment not found"
        return {
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
        }

    @staticmethod
    def instruction_texts():
        for heading, items in gui.INSTRUCTIONS:
            yield heading
            for _marker, text, subitems in items:
                yield text
                yield from subitems

    def test_quoted_labels_exist_in_the_window(self):
        strings = self.window_strings()
        quoted = [q.rstrip(".,:;") for text in self.instruction_texts() for q in re.findall(r'"([^"]+)"', text)]
        self.assertTrue(quoted)
        self.assertEqual([q for q in quoted if q not in strings], [])


if __name__ == "__main__":
    unittest.main()
