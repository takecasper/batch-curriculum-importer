import contextlib
import io
import sys
import tempfile
import unittest
from datetime import date, time
from pathlib import Path

from openpyxl import Workbook, load_workbook

# The app modules sit in the repo root, one level up; the other test files
# import this one first, so this makes them importable everywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wrangler  # noqa: E402

HEADERS = [
    "portfolio",
    "Course Name",
    "Session Type",
    "Session Name",
    "Section Name",
    "Section Date",
    "Start Time",
    "End Time",
    "Location",
]


def row(portfolio, course, session="Lecture 1", start=time(10), end=time(11), when=date(2026, 5, 5)):
    return [portfolio, course, "Lecture", session, 1, when, start, end, "Hall 4"]


def write_partner_workbook(folder: Path, name: str, rows, headers=HEADERS):
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Schedule Upload"
    sheet.append(headers)
    for values in rows:
        sheet.append(values)
    mapping = wb.create_sheet("Mapping Upload")
    mapping.append(["Course", "Session", "Objective"])
    mapping.append(["MD468", "Lecture 1", "Describe things"])
    wb.save(folder / name)


def data_tabs(out):
    return [name for name in out.sheetnames if name != "Change Log"]


class WranglerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.batch = Path(self._tmp.name) / "batch"
        self.batch.mkdir()
        self.output = Path(self._tmp.name) / "out.xlsx"

    def tearDown(self):
        self._tmp.cleanup()

    def run_wrangler(self, *extra):
        argv = ["wrangler", "--input-dir", str(self.batch), "--output", str(self.output), *extra]
        stdout = io.StringIO()
        old_argv = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(stdout):
                wrangler.main()
        finally:
            sys.argv = old_argv
        self.log = stdout.getvalue()
        return load_workbook(self.output)

    def run_expecting_stop(self, *extra):
        with self.assertRaises(SystemExit) as stopped:
            self.run_wrangler(*extra)
        self.assertFalse(self.output.exists())
        return str(stopped.exception.code)

    def log_entries(self, out):
        sheet = out["Change Log"]
        headers = [c.value for c in sheet[1]]
        return [
            dict(zip(headers, (c.value for c in cells)))
            for cells in sheet.iter_rows(min_row=2)
        ]

    def find(self, entries, change, **fields):
        return [
            e for e in entries
            if e["Change"] == change and all(e[k] == v for k, v in fields.items())
        ]

    @staticmethod
    def column(sheet, header):
        headers = [cell.value for cell in sheet[1]]
        idx = headers.index(header) + 1
        return [sheet.cell(r, idx).value for r in range(2, sheet.max_row + 1)]


class CheckRunTests(WranglerTestCase):
    def test_single_workbook_with_portfolio_becomes_portfolio_tab_without_portfolio_column(self):
        write_partner_workbook(
            self.batch,
            "MedPharm.xlsx",
            [
                row("Summer 2026, MED 4", "MD468 Medical Pharmacology"),
                row(" summer 2026, med 4", "MD468 Medical Pharmacology", session="Lecture 2"),
            ],
        )
        out = self.run_wrangler()
        self.assertEqual(data_tabs(out), ["Summer 2026, MED 4"])
        sheet = out["Summer 2026, MED 4"]
        self.assertNotIn("portfolio", [c.value for c in sheet[1]])
        self.assertEqual(sheet.max_row, 3)
        self.assertIn("Check Run", self.log)

    def test_single_workbook_splits_by_portfolio_when_it_holds_several(self):
        write_partner_workbook(
            self.batch,
            "MedPharm.xlsx",
            [
                row("Summer 2026, MED 4", "MD468 Medical Pharmacology"),
                row("Summer 2026, MED 5", "MD468 Medical Pharmacology", session="Lecture 2"),
            ],
        )
        out = self.run_wrangler()
        self.assertEqual(data_tabs(out), ["Summer 2026, MED 4", "Summer 2026, MED 5"])

    def test_single_workbook_without_portfolio_becomes_one_course_tab(self):
        no_portfolio = HEADERS[1:]
        write_partner_workbook(
            self.batch,
            "MedPharm.xlsx",
            [row(None, "MD468 Medical Pharmacology")[1:], row(None, "MD468 Medical Pharmacology")[1:]],
            no_portfolio,
        )
        out = self.run_wrangler()
        self.assertEqual(data_tabs(out), ["MD468 Medical Pharmacology"])
        self.assertEqual(out["MD468 Medical Pharmacology"].max_row, 3)
        self.assertIn("Check Run", self.log)


class CombineRunTests(WranglerTestCase):
    def test_portfolio_tabs_merge_names_differing_only_by_case_or_whitespace(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm")])
        write_partner_workbook(self.batch, "b.xlsx", [row(" summer 2026,  med 4 ", "MD482 Path 1")])
        write_partner_workbook(self.batch, "c.xlsx", [row("Summer 2026, MED 5", "MD516 Clin")])
        out = self.run_wrangler()
        self.assertEqual(sorted(data_tabs(out)), ["Summer 2026, MED 4", "Summer 2026, MED 5"])
        self.assertEqual(
            self.column(out["Summer 2026, MED 4"], "Course Name"), ["MD468 Pharm", "MD482 Path 1"]
        )

    def test_several_courses_without_any_portfolio_stop_and_list_the_courses(self):
        no_portfolio = HEADERS[1:]
        write_partner_workbook(self.batch, "bio.xlsx", [row(None, "Intro to Biology")[1:]], no_portfolio)
        write_partner_workbook(self.batch, "anat.xlsx", [row(None, "Anatomy I")[1:]], no_portfolio)
        message = self.run_expecting_stop()
        self.assertIn("no Portfolio", message)
        self.assertIn("bio.xlsx: Intro to Biology", message)
        self.assertIn("anat.xlsx: Anatomy I", message)
        self.assertIn("--portfolio", message)

    def test_portfolio_option_puts_every_course_into_that_portfolio(self):
        no_portfolio = HEADERS[1:]
        write_partner_workbook(self.batch, "bio.xlsx", [row(None, "Intro to Biology")[1:]], no_portfolio)
        write_partner_workbook(self.batch, "anat.xlsx", [row(None, "Anatomy I")[1:]] * 2, no_portfolio)
        out = self.run_wrangler("--portfolio", "Summer 2026, MED 4")
        self.assertEqual(data_tabs(out), ["Summer 2026, MED 4"])
        self.assertEqual(out["Summer 2026, MED 4"].max_row, 4)
        filled = [
            (cells[0].value, cells[8].value)
            for cells in out["Change Log"].iter_rows(min_row=2)
            if cells[6].value == "Portfolio filled in"
        ]
        self.assertEqual(
            sorted(filled), [("anat.xlsx", "Summer 2026, MED 4"), ("bio.xlsx", "Summer 2026, MED 4")]
        )

    def test_blank_portfolios_alongside_filled_ones_stop_and_list_the_workbooks(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm")])
        write_partner_workbook(self.batch, "b.xlsx", [row(None, "MD300 Spanish")])
        message = self.run_expecting_stop()
        self.assertIn("rows with no Portfolio", message)
        self.assertIn("b.xlsx: MD300 Spanish", message)
        self.assertNotIn("a.xlsx", message)
        self.assertIn("--portfolio", message)

    def test_portfolio_option_fills_only_the_blank_rows(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm")])
        write_partner_workbook(
            self.batch, "b.xlsx", [row("Summer 2026, MED 5", "MD300 Spanish"), row(None, "MD300 Spanish")]
        )
        out = self.run_wrangler("--portfolio", "Summer 2026, MED 5")
        self.assertEqual(sorted(data_tabs(out)), ["Summer 2026, MED 4", "Summer 2026, MED 5"])
        self.assertEqual(out["Summer 2026, MED 5"].max_row, 3)

    def test_unassigned_file_tabs_give_each_file_without_a_portfolio_its_own_tab(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468")])
        write_partner_workbook(self.batch, "Spanish MD300.xlsx", [row(None, "MD300")] * 2)
        write_partner_workbook(
            self.batch, "mixed.xlsx", [row("Summer 2026, MED 4", "MD470"), row(None, "MD470", session="Lab")]
        )
        out = self.run_wrangler("--unassigned-file-tabs")
        self.assertEqual(data_tabs(out), ["Summer 2026, MED 4", "Spanish MD300", "mixed"])
        self.assertEqual(self.column(out["Summer 2026, MED 4"], "Course Name"), ["MD468", "MD470"])
        self.assertEqual(out["Spanish MD300"].max_row, 3)
        self.assertEqual(self.column(out["mixed"], "Session Name"), ["Lab"])
        entries = self.log_entries(out)
        self.assertEqual(
            [(e["Source File"], e["Tab"]) for e in self.find(entries, "No Portfolio: given its own tab")],
            [("Spanish MD300.xlsx", "Spanish MD300"), ("mixed.xlsx", "mixed")],
        )

    def test_unassigned_file_tabs_when_no_file_has_a_portfolio(self):
        no_portfolio = HEADERS[1:]
        write_partner_workbook(self.batch, "bio.xlsx", [row(None, "Intro to Biology")[1:]], no_portfolio)
        write_partner_workbook(self.batch, "anat.xlsx", [row(None, "Anatomy I")[1:]], no_portfolio)
        out = self.run_wrangler("--unassigned-file-tabs")
        self.assertEqual(sorted(data_tabs(out)), ["anat", "bio"])

    def test_summary_maps_truncated_tab_to_full_portfolio_name(self):
        long_name = "Summer 2026, Undergraduate Medical Education Year 4"
        write_partner_workbook(self.batch, "a.xlsx", [row(long_name, "MD468 Pharm")])
        write_partner_workbook(self.batch, "b.xlsx", [row(long_name, "MD482 Path")])
        out = self.run_wrangler()
        self.assertEqual(data_tabs(out), [long_name[:31]])
        self.assertIn(long_name, self.log)

    def test_earlier_outputs_in_the_folder_are_not_read_as_input(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm")])
        for name in ("batch-batch-import.xlsx", "batch-master-schedule.xlsx", "school_schedule-import.xlsx"):
            write_partner_workbook(self.batch, name, [row("Fall 2025, MED 4", "Old")])
        out = self.run_wrangler()
        self.assertEqual(data_tabs(out), ["Summer 2026, MED 4"])
        self.assertIn("skipped 3 earlier output", self.log)

    def test_warns_when_portfolios_span_more_than_one_term(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm")])
        write_partner_workbook(self.batch, "b.xlsx", [row("Spring 2026, MED 4", "MD482 Path")])
        self.run_wrangler()
        self.assertIn("more than one term", self.log)

    def test_single_term_batch_does_not_warn(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm")])
        write_partner_workbook(self.batch, "b.xlsx", [row("Summer 2026, MED 5", "MD482 Path")])
        self.run_wrangler()
        self.assertNotIn("more than one term", self.log)


class CellCheckTests(WranglerTestCase):
    def only_sheet(self, rows):
        write_partner_workbook(self.batch, "a.xlsx", rows)
        out = self.run_wrangler()
        return out[out.sheetnames[0]]

    def test_end_not_after_start_is_flagged(self):
        sheet = self.only_sheet([row("P", "C", start=time(11), end=time(10))])
        start_col = [c.value for c in sheet[1]].index("Start Time") + 1
        self.assertEqual(sheet.cell(2, start_col).fill.fgColor.rgb[-6:], "FFCCCC")

    def test_semicolons_are_not_flagged(self):
        sheet = self.only_sheet([row("P", "C", session="Intro; overview")])
        session_col = [c.value for c in sheet[1]].index("Session Name") + 1
        self.assertIsNone(sheet.cell(2, session_col).fill.fill_type)
        self.assertNotIn("semicolon", self.log.lower())

    def test_fixable_times_and_dates_are_fixed(self):
        sheet = self.only_sheet(
            [
                row("P", "C", start="9:00 a.m.", end="1000", when=46147),
                row("P", "C", start="9:00AM", end="10:30:00", when="May 5, 2026"),
            ]
        )
        self.assertEqual(self.column(sheet, "Start Time"), [time(9), time(9)])
        self.assertEqual(self.column(sheet, "End Time"), [time(10), time(10, 30)])
        dates = [v.date() for v in self.column(sheet, "Section Date")]
        self.assertEqual(dates, [date(2026, 5, 5), date(2026, 5, 5)])

    def test_unreadable_values_pass_through_and_are_listed_not_flagged(self):
        sheet = self.only_sheet([row("P", "C", start="TBD", when="sometime")])
        self.assertEqual(self.column(sheet, "Start Time"), ["TBD"])
        self.assertEqual(self.column(sheet, "Section Date"), ["sometime"])
        start_col = [c.value for c in sheet[1]].index("Start Time") + 1
        self.assertIsNone(sheet.cell(2, start_col).fill.fill_type)
        self.assertIn("could not be read", self.log)
        self.assertIn("TBD", self.log)


class MappingPreFilterTests(WranglerTestCase):
    def test_objective_in_a_session_name_keeps_the_schedule_sheet(self):
        sessions = ["Learning Objectives Review", "Lecture 2"]
        write_partner_workbook(self.batch, "a.xlsx", [row("P", "C", session=s) for s in sessions])
        out = self.run_wrangler()
        self.assertEqual(self.column(out["P"], "Session Name"), sessions)
        entries = self.log_entries(out)
        self.assertFalse(self.find(entries, "Sheet skipped (mapping sheet)", **{"Source Sheet": "Schedule Upload"}))

    def test_mapping_sheet_with_extra_rows_above_its_header_is_still_skipped(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("P", "C")])
        wb = Workbook()
        sheet = wb.active
        sheet.title = "Objectives Map"
        for title in (["MD468 curriculum map"], [None], ["Draft"], ["Owner: Dr. Lee"], [None], ["v3"]):
            sheet.append(title)
        sheet.append(HEADERS + ["Objectives"])
        sheet.append(row("P", "C", session="Mapped Lecture") + ["Describe things"])
        wb.save(self.batch / "b.xlsx")
        out = self.run_wrangler()
        self.assertNotIn("Mapped Lecture", self.column(out["P"], "Session Name"))
        entries = self.log_entries(out)
        self.assertTrue(self.find(entries, "Sheet skipped (mapping sheet)", **{"Source Sheet": "Objectives Map"}))

    def test_objective_in_a_title_row_above_the_header_skips_the_sheet(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("P", "C")])
        wb = Workbook()
        sheet = wb.active
        sheet.title = "Map"
        sheet.append(["MD468 Learning Objectives Map"])
        sheet.append(HEADERS)
        sheet.append(row("P", "C", session="Mapped Lecture"))
        wb.save(self.batch / "b.xlsx")
        out = self.run_wrangler()
        self.assertNotIn("Mapped Lecture", self.column(out["P"], "Session Name"))
        self.assertTrue(self.find(self.log_entries(out), "Sheet skipped (mapping sheet)", **{"Source Sheet": "Map"}))


class AssessmentModeTests(WranglerTestCase):
    def test_formative_summative_casing_is_fixed_and_logged(self):
        modes = ["summative", " FORMATIVE ", "Formative", "Both"]
        write_partner_workbook(
            self.batch,
            "a.xlsx",
            [row("P", "C", session=f"Lecture {n}") + [m] for n, m in enumerate(modes)],
            HEADERS + ["Session Formative/Summative"],
        )
        out = self.run_wrangler()
        self.assertEqual(
            self.column(out["P"], "Session Formative/Summative"), ["Summative", "Formative", "Formative", "Both"]
        )
        fixed = self.find(self.log_entries(out), "Formative/Summative fixed")
        self.assertEqual([(e["Original"], e["New"], e["Tab Row"]) for e in fixed], [
            ("summative", "Summative", 2), (" FORMATIVE ", "Formative", 3),
        ])


class ChangeLogTests(WranglerTestCase):

    def test_change_log_is_the_last_tab_and_records_column_changes(self):
        headers = ["Portfolio", "Course"] + HEADERS[2:] + ["Zzz Extra"]
        write_partner_workbook(self.batch, "a.xlsx", [row("P", "C") + ["x"]], headers)
        out = self.run_wrangler()
        self.assertEqual(out.sheetnames[-1], "Change Log")
        entries = self.log_entries(out)
        self.assertTrue(self.find(entries, "Header renamed", Original="Course", New="Course Name"))
        self.assertTrue(self.find(entries, "Portfolio column removed", Original="Portfolio"))
        self.assertTrue(
            self.find(entries, "Column dropped (no matching import header)", Original="Zzz Extra")
        )
        self.assertTrue(self.find(entries, "Column added (blank)", New="Course Number"))
        self.assertFalse(self.find(entries, "Header renamed", Original="Session Name"))
        self.assertIn("Change Log entries:", self.log)

    def test_fixed_and_unreadable_values_are_logged_with_their_tab_row(self):
        write_partner_workbook(
            self.batch,
            "a.xlsx",
            [row("P", "C"), row("P", "C", start="9:00AM", when="sometime")],
        )
        entries = self.log_entries(self.run_wrangler())
        fixed = self.find(entries, "Time fixed", Column="Start Time")
        self.assertEqual(len(fixed), 1)
        self.assertEqual(
            (fixed[0]["Source File"], fixed[0]["Source Row"], fixed[0]["Tab"], fixed[0]["Tab Row"]),
            ("a.xlsx", 3, "P", 3),
        )
        self.assertEqual(fixed[0]["Original"], "9:00AM")
        self.assertEqual(fixed[0]["New"], time(9))
        self.assertTrue(
            self.find(entries, "Could not read (left unchanged)", Column="Section Date", Original="sometime")
        )
        self.assertFalse(self.find(entries, "Date fixed"))
        self.assertFalse(self.find(entries, "Time fixed", Column="End Time"))

    def test_flagged_rows_and_skipped_mapping_sheets_are_logged(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("P", "C", start=time(11), end=time(10))])
        entries = self.log_entries(self.run_wrangler())
        self.assertTrue(
            self.find(entries, "Flagged: End Time not after Start Time", Tab="P", **{"Tab Row": 2})
        )
        self.assertTrue(self.find(entries, "Sheet skipped (mapping sheet)", **{"Source Sheet": "Mapping Upload"}))


class FilePerTabTests(WranglerTestCase):
    def test_each_portfolio_gets_its_own_file_and_change_log(self):
        write_partner_workbook(
            self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468", start="9:00AM")]
        )
        write_partner_workbook(
            self.batch, "b.xlsx", [row("Fall 2026/MED 3", "MD300")], ["portfolio", "Course"] + HEADERS[2:]
        )
        (self.batch / "bad.xlsx").write_text("not a workbook")
        folder = Path(self._tmp.name) / "out"
        argv = ["wrangler", "--input-dir", str(self.batch), "--output", str(folder), "--file-per-tab"]
        old_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                wrangler.main()
        finally:
            sys.argv = old_argv

        self.assertEqual(
            sorted(p.name for p in folder.iterdir()),
            ["Fall 2026_MED 3.xlsx", "Summer 2026, MED 4.xlsx"],
        )
        summer = load_workbook(folder / "Summer 2026, MED 4.xlsx")
        fall = load_workbook(folder / "Fall 2026_MED 3.xlsx")
        self.assertEqual(summer.sheetnames, ["Summer 2026, MED 4", "Change Log"])
        summer_log, fall_log = self.log_entries(summer), self.log_entries(fall)

        self.assertTrue(self.find(summer_log, "Time fixed", **{"Source File": "a.xlsx", "Tab Row": 2}))
        self.assertFalse(self.find(fall_log, "Time fixed"))
        self.assertTrue(self.find(fall_log, "Header renamed", **{"Source File": "b.xlsx"}))
        self.assertFalse(self.find(summer_log, "Header renamed"))
        for log in (summer_log, fall_log):
            self.assertTrue(self.find(log, "Workbook skipped (could not open)", **{"Source File": "bad.xlsx"}))


class AppStepsTests(WranglerTestCase):
    """The read, ask, then write steps the GUI drives."""

    def read(self):
        options = wrangler.parse_args(["--input-dir", str(self.batch)])
        with contextlib.redirect_stdout(io.StringIO()):
            return wrangler.read_batch(self.batch, self.output, options)

    def write(self, batch, file_per_tab=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return wrangler.write_batch_import(batch, self.output, file_per_tab)

    def test_blank_portfolios_are_reported_then_filled_per_workbook(self):
        write_partner_workbook(self.batch, "a.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm")])
        write_partner_workbook(self.batch, "b.xlsx", [row(None, "MD300 Spanish")])
        batch = self.read()

        gap = wrangler.portfolio_gap(batch)
        self.assertEqual(gap.kind, "blank")
        self.assertEqual(gap.courses, {"b.xlsx": ["MD300 Spanish"]})
        self.assertEqual(gap.portfolios, ["Summer 2026, MED 4"])

        batch.fill({"b.xlsx": "Summer 2026, MED 4"})
        self.assertIsNone(wrangler.portfolio_gap(batch))
        result = self.write(batch)
        self.assertEqual(result.paths, [self.output])
        self.assertEqual(data_tabs(load_workbook(self.output)), ["Summer 2026, MED 4"])

    def test_several_courses_without_a_portfolio_ask_for_one(self):
        no_portfolio = HEADERS[1:]
        write_partner_workbook(self.batch, "bio.xlsx", [row(None, "Intro to Biology")[1:]], no_portfolio)
        write_partner_workbook(self.batch, "anat.xlsx", [row(None, "Anatomy I")[1:]], no_portfolio)
        gap = wrangler.portfolio_gap(self.read())
        self.assertEqual(gap.kind, "none")
        self.assertEqual(gap.portfolios, [])

    def test_one_course_without_a_portfolio_needs_nothing(self):
        no_portfolio = HEADERS[1:]
        write_partner_workbook(self.batch, "bio.xlsx", [row(None, "Intro to Biology")[1:]], no_portfolio)
        self.assertIsNone(wrangler.portfolio_gap(self.read()))

    def test_result_reports_what_needs_attention(self):
        write_partner_workbook(
            self.batch,
            "a.xlsx",
            [
                row("Summer 2026, MED 4", "C", start=time(11), end=time(10)),
                row("Spring 2026, MED 4", "C", when="sometime"),
            ],
        )
        result = self.write(self.read())
        self.assertEqual(result.flagged_rows, 1)
        self.assertEqual(result.unreadable_values, 1)
        self.assertEqual(result.terms, ["Summer 2026", "Spring 2026"])


if __name__ == "__main__":
    unittest.main()
