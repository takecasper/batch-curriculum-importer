#!/usr/bin/env python3
"""
One45 Schedule Wrangler: turn a Batch of Partner Workbooks into one Batch Import
using canonical, case/order-sensitive headers. See GLOSSARY.md for the terms below.

Behavior:
- Looks for .xlsx workbooks in (in order):
    1. The path given via --input-dir
    2. A `schedule-workbooks/` subfolder next to this script
    3. The user's ~/Downloads folder
- Step 0: materializes formula cells using cached computed values before mapping.
- Identifies candidate sheets by fuzzy-matching column headers against canonical
  headers (at least --min-header-matches hits at or above --fuzzy-threshold).
  The optional --tab-contains filter narrows which sheets are tried first, but a
  workbook is never skipped solely because no tab name matches.
- Detects the source header row.
- Fuzzy-maps source headers to canonical import headers.
- Fixes readable time/date variants; values it cannot read pass through and are
  listed in the summary.
- Writes one tab per Portfolio. Every row needs a Portfolio: blanks stop the run
  with a list of workbooks unless --portfolio fills them. A Batch of a single
  Course with no Portfolio gets one tab named after the Course.
- With --file-per-tab, writes one workbook per Portfolio into a folder instead.
- Flags rows where end time is not after start time with red cell fill.
- Ends each workbook with a "Change Log" tab listing every change made between
  the Partner Workbooks and it. It is never imported.

Example:
  python3 /path/to/create-master-schedule-workbook.py

wrangler-gui.py drives the same steps (read_batch, portfolio_gap,
write_batch_import) from a window, asking for missing Portfolios.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zipfile import BadZipFile

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.exceptions import InvalidFileException
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: openpyxl. Install with `python3 -m pip install openpyxl`."
    ) from exc


MAX_SHEET_NAME_LENGTH = 31
INVALID_SHEET_CHARS = set(r"[]:*?/\\")
INVALID_FILE_CHARS = set('/\\:*?"<>|')  # Windows and macOS
CHANGE_LOG_TAB_TITLE = "Change Log"
CHANGE_LOG_HEADERS = [
    "Source File",
    "Source Sheet",
    "Source Row",
    "Tab",
    "Tab Row",
    "Column",
    "Change",
    "Original",
    "New",
]
TERM_PATTERN = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(\d{4})\b", re.IGNORECASE)
MAX_UNREADABLE_LISTED = 20
ASSESSMENT_MODE_HEADER = "Session Formative/Summative"
CANONICAL_HEADERS = [
    "portfolio",
    "Course Name",
    "Course Number",
    "Subcourse Name",
    "Subcourse Number",
    "Session Type",
    ASSESSMENT_MODE_HEADER,
    "Session Name",
    "Section Name",
    "Section Date",
    "Start Time",
    "End Time",
    "Location",
    "Learner Group Family",
    "Learner Group In",
    "Learner Role",
    "Facilitator Last Name",
    "Facilitator First Name",
    "Facilitator email ",
    "Facilitator Role ",
]


PRESET_HEADER_ALIASES = {
    "session": "Session Name",
    "session title": "Session Name",
    "start date": "Section Date",
    "event type": "Session Type",
    "facilitator email": "Facilitator email ",
    "facilitator e-mail": "Facilitator email ",
    "facilitator role": "Facilitator Role ",
}


HeaderMap = Dict[int, int]  # canonical_header_index -> source_header_index


@dataclass
class ChangeLogEntry:
    source_file: str
    source_sheet: str = ""
    source_row: Optional[int] = None
    column: str = ""
    change: str = ""
    original: object = None
    new: object = None
    tab: str = ""  # row-level entries get their tab and row when written
    tab_row: Optional[int] = None


@dataclass
class CollectedRow:
    workbook_name: str
    values: List[object]  # canonical-length, already normalized
    bad_time: bool
    source_sheet: str = ""
    source_row: Optional[int] = None
    changes: List[ChangeLogEntry] = field(default_factory=list)


@dataclass
class UnreadableValue:
    location: str
    header: str
    value: object


@dataclass
class OutputTab:
    kind: str  # "Portfolio", "Course", or "Unassigned" (a workbook with no Portfolio)
    full_name: str
    rows: List[CollectedRow] = field(default_factory=list)
    title: str = ""


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One45 Schedule Wrangler: build one Batch Import from a Batch of "
            "Partner Workbooks by fuzzy matching source headers to hardcoded "
            "canonical headers."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help=(
            "Directory containing source .xlsx workbooks. "
            "Default: schedule-workbooks/ next to this script, then ~/Downloads"
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output workbook path. Default: <input-dir>/<input-dir-name>-batch-import.xlsx"
        ),
    )
    parser.add_argument(
        "--tab-contains",
        default="",
        help=(
            "Optional case-insensitive substring filter on tab names. When provided, "
            "sheets whose title contains this token are tried first; sheets that do NOT "
            "match are still processed if their headers pass fuzzy detection. "
            "Default: (empty — no tab-name pre-filter)"
        ),
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.72,
        help="Header fuzzy-match threshold in [0, 1]. Default: 0.72",
    )
    parser.add_argument(
        "--header-scan-rows",
        type=int,
        default=30,
        help="Max rows to scan for the source header row. Default: 30",
    )
    parser.add_argument(
        "--min-header-matches",
        type=int,
        default=3,
        help="Minimum canonical header matches required to accept a header row. Default: 3",
    )
    parser.add_argument(
        "--portfolio",
        default=None,
        help=(
            "Portfolio for every row whose Portfolio is blank, e.g. when a Batch of "
            "several Courses has no portfolio column. Default: stop and list them."
        ),
    )
    parser.add_argument(
        "--unassigned-file-tabs",
        action="store_true",
        help=(
            "Give each workbook with blank Portfolios its own tab, named after the file, "
            "instead of stopping. Default: stop and list them."
        ),
    )
    parser.add_argument(
        "--file-per-tab",
        action="store_true",
        help=(
            "Write a separate workbook per Portfolio into a folder instead of one "
            "workbook with a tab per Portfolio. --output is then the folder. "
            "Default folder: <input-dir>/<input-dir-name>-batch-import"
        ),
    )
    parser.add_argument(
        "--skip-formula-materialization",
        action="store_true",
        help=("Skip Step 0 formula-to-cached-value conversion before mapping rows."),
    )
    parser.add_argument(
        "--skip-hidden-rows",
        action="store_true",
        help=(
            "Skip rows that are hidden in the source workbook (e.g. via Excel "
            "auto-filter or manual hide). Default: include hidden rows."
        ),
    )
    args = parser.parse_args(argv)
    if not (0.0 <= args.fuzzy_threshold <= 1.0):
        parser.error("--fuzzy-threshold must be in the range [0, 1].")
    if args.header_scan_rows < 1:
        parser.error("--header-scan-rows must be >= 1.")
    if args.min_header_matches < 1:
        parser.error("--min-header-matches must be >= 1.")
    return args


def is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def sanitize_sheet_name(name: str) -> str:
    cleaned = "".join("_" if ch in INVALID_SHEET_CHARS else ch for ch in name).strip()
    if not cleaned:
        cleaned = "Sheet"
    return cleaned


def make_unique_file_name(name: str, used_names: set[str]) -> str:
    """A .xlsx file name for name, unique (case-insensitively) within used_names."""
    base = "".join("_" if ch in INVALID_FILE_CHARS else ch for ch in name).strip().rstrip(".")
    base = base or "Schedule"
    candidate, counter = base, 2
    while candidate.casefold() in used_names:
        candidate = f"{base} {counter}"
        counter += 1
    used_names.add(candidate.casefold())
    return f"{candidate}.xlsx"


def clamp_sheet_name(name: str) -> str:
    return name[:MAX_SHEET_NAME_LENGTH]


def make_unique_sheet_title(base_title: str, used_titles: set[str]) -> str:
    """Return a valid title not in used_titles. used_titles holds casefolded
    titles because Excel treats sheet names case-insensitively."""
    base = clamp_sheet_name(sanitize_sheet_name(base_title))
    if base.casefold() not in used_titles:
        return base
    counter = 2
    while True:
        suffix = f" {counter}"
        candidate = f"{base[: MAX_SHEET_NAME_LENGTH - len(suffix)]}{suffix}"
        if candidate.casefold() not in used_titles:
            return candidate
        counter += 1


def display_name(value: object) -> str:
    return " ".join(str(value).split())


def routing_key(value: object) -> str:
    """Names that differ only by case or whitespace route to the same tab."""
    return display_name(value).casefold()


def normalize_header(text: object) -> str:
    if is_blank(text):
        return ""
    value = str(text).strip().lower()
    value = value.replace("_", " ")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def military_time(number: int) -> Optional[time]:
    """900 / 0900 / 1330 style clock times."""
    hour, minute = divmod(number, 100)
    if 100 <= number <= 2359 and minute <= 59:
        return time(hour=hour, minute=minute)
    return None


def normalize_time_value(value: object) -> object:
    """Return a time when the value can be read, otherwise the value unchanged."""
    if is_blank(value):
        return value

    # openpyxl with data_only=True may return a time or datetime directly.
    if isinstance(value, time) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.time()

    # Whole numbers are clock times typed without a colon (930, 1400); fractions
    # are Excel's time-of-day storage (0.0 = midnight, 0.5 = noon).
    if isinstance(value, int) and not isinstance(value, bool):
        return military_time(value) or value
    if isinstance(value, float):
        frac = value % 1.0  # strip any date component
        total_seconds = round(frac * 86400)
        h, rem = divmod(total_seconds, 3600)
        m, _ = divmod(rem, 60)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return time(hour=h, minute=m)
        return value

    if not isinstance(value, str):
        return value

    # "9:00 a.m." -> "9:00 am"
    raw = re.sub(r"\s+", " ", value.strip().lower().replace(".", ""))
    if raw == "":
        return value
    if raw == "noon":
        return time(hour=12)

    meridiem_match = re.match(
        r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?::\d{2})?\s*(?P<meridiem>[ap])(?:\s*m)?$",
        raw,
    )
    if meridiem_match:
        hour = int(meridiem_match.group("hour"))
        minute_raw = meridiem_match.group("minute")
        minute = int(minute_raw) if minute_raw is not None else 0
        meridiem = meridiem_match.group("meridiem")

        if 0 <= minute <= 59 and 1 <= hour <= 12:
            if meridiem == "a" and hour == 12:
                hour = 0
            elif meridiem == "p" and hour < 12:
                hour += 12
            return time(hour=hour, minute=minute)

    clock_match = re.match(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::\d{2})?$", raw)
    if clock_match:
        hour = int(clock_match.group("hour"))
        minute = int(clock_match.group("minute"))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute)

    if re.fullmatch(r"\d{3,4}", raw):
        return military_time(int(raw)) or value

    return value


EXCEL_EPOCH = date(1899, 12, 30)


def normalize_date_value(value: object) -> object:
    """Return a date when the value can be read, otherwise the value unchanged."""
    if is_blank(value):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value)
        if 19000101 <= number <= 29991231:
            return normalize_date_value(str(number))
        # Excel serial day numbers, roughly 1954 to 2119.
        if 20000 <= number <= 80000:
            return EXCEL_EPOCH + timedelta(days=number)
        return value

    if not isinstance(value, str):
        return value

    raw = re.sub(r"\s+", " ", value.strip())
    if raw == "":
        return value

    formats = (
        "%Y%m%d",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%A, %B %d, %Y",
        "%a, %b %d, %Y",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
    )
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return value


def normalize_assessment_mode(value: object) -> object:
    """Formative/Summative in any case or padding becomes the importer's title
    case; anything else passes through."""
    if isinstance(value, str) and value.strip().casefold() in ("formative", "summative"):
        return value.strip().title()
    return value


def header_similarity(
    src_norm: str, canon_norm: str, alias_lookup: Dict[str, str]
) -> float:
    if not src_norm or not canon_norm:
        return 0.0
    if src_norm == canon_norm:
        return 1.0
    if alias_lookup.get(src_norm) == canon_norm:
        return 0.995
    if src_norm in canon_norm or canon_norm in src_norm:
        return 0.9
    return SequenceMatcher(None, src_norm, canon_norm).ratio()


def build_alias_lookup(canonical_headers: List[str]) -> Dict[str, str]:
    canonical_norms = {normalize_header(header) for header in canonical_headers}
    alias_lookup: Dict[str, str] = {}
    for alias, canonical_target in PRESET_HEADER_ALIASES.items():
        canonical_norm = normalize_header(canonical_target)
        if canonical_norm in canonical_norms:
            alias_lookup[normalize_header(alias)] = canonical_norm
    return alias_lookup


def match_headers(
    source_headers: List[object],
    canonical_headers: List[str],
    threshold: float,
    alias_lookup: Dict[str, str],
) -> Tuple[HeaderMap, Dict[int, float], List[int], List[int]]:
    canonical_norms = [normalize_header(header) for header in canonical_headers]
    source_norms = [normalize_header(header) for header in source_headers]

    candidates: List[Tuple[float, int, int]] = []
    for src_idx, src_norm in enumerate(source_norms):
        if not src_norm:
            continue
        for canon_idx, canon_norm in enumerate(canonical_norms):
            score = header_similarity(src_norm, canon_norm, alias_lookup)
            if score >= threshold:
                candidates.append((score, src_idx, canon_idx))

    candidates.sort(key=lambda item: item[0], reverse=True)

    assigned_source: set[int] = set()
    assigned_canonical: set[int] = set()
    mapping: HeaderMap = {}
    scores: Dict[int, float] = {}

    for score, src_idx, canon_idx in candidates:
        if src_idx in assigned_source or canon_idx in assigned_canonical:
            continue
        mapping[canon_idx] = src_idx
        scores[canon_idx] = score
        assigned_source.add(src_idx)
        assigned_canonical.add(canon_idx)

    unmatched_source = [
        src_idx
        for src_idx, src_norm in enumerate(source_norms)
        if src_norm and src_idx not in assigned_source
    ]
    missing_canonical = [
        canon_idx
        for canon_idx in range(len(canonical_headers))
        if canon_idx not in assigned_canonical
    ]

    return mapping, scores, unmatched_source, missing_canonical


def names_objective(cells: List[object]) -> bool:
    """True if any cell holds the word 'objective' or 'objectives', the mark of a
    Mapping Sheet's header ("Session Objectives" and the like)."""
    return any(re.search(r"\bobjectives?\b", normalize_header(cell)) for cell in cells)


def sheet_has_objective_header(worksheet, scan_rows: int) -> bool:
    """True if any of the first scan_rows rows names an objective."""
    return any(
        names_objective([cell.value for cell in cells])
        for cells in worksheet.iter_rows(max_row=min(scan_rows, worksheet.max_row))
    )


def detect_header_row(
    worksheet,
    canonical_headers: List[str],
    threshold: float,
    alias_lookup: Dict[str, str],
    scan_rows: int,
    min_header_matches: int,
) -> Optional[
    Tuple[int, List[object], HeaderMap, Dict[int, float], List[int], List[int]]
]:
    best_result: Optional[
        Tuple[
            int,
            List[object],
            HeaderMap,
            Dict[int, float],
            List[int],
            List[int],
            int,
            float,
        ]
    ] = None

    max_scan = min(scan_rows, worksheet.max_row)
    for row_idx in range(1, max_scan + 1):
        row_values = [
            worksheet.cell(row_idx, col_idx).value
            for col_idx in range(1, worksheet.max_column + 1)
        ]
        non_empty_count = sum(1 for value in row_values if not is_blank(value))
        if non_empty_count == 0:
            continue

        mapping, scores, unmatched_source, missing_canonical = match_headers(
            source_headers=row_values,
            canonical_headers=canonical_headers,
            threshold=threshold,
            alias_lookup=alias_lookup,
        )
        matched_count = len(mapping)
        if matched_count == 0:
            continue

        density = matched_count / max(1, min(non_empty_count, len(canonical_headers)))
        candidate = (
            row_idx,
            row_values,
            mapping,
            scores,
            unmatched_source,
            missing_canonical,
            matched_count,
            density,
        )
        if best_result is None:
            best_result = candidate
            continue

        best_matched = best_result[6]
        best_density = best_result[7]
        if matched_count > best_matched or (
            matched_count == best_matched and density > best_density
        ):
            best_result = candidate

    if not best_result:
        return None

    if best_result[6] < min_header_matches:
        return None

    return (
        best_result[0],
        best_result[1],
        best_result[2],
        best_result[3],
        best_result[4],
        best_result[5],
    )


def materialize_formula_cells(source_sheet, values_sheet) -> Tuple[int, int]:
    """
    Step 0: replace formula cells with cached computed values before any mapping.

    Returns (converted_count, unresolved_count). Unresolved formulas are left intact
    when the workbook has no cached value for the formula cell.
    """
    converted = 0
    unresolved = 0

    for row in source_sheet.iter_rows():
        for cell in row:
            if cell.data_type != "f":
                continue
            cached_value = values_sheet[cell.coordinate].value
            if cached_value is None:
                unresolved += 1
                continue
            cell.value = cached_value
            converted += 1

    return converted, unresolved


def collect_rows(
    source_sheet,
    workbook_name: str,
    header_row_idx: int,
    header_map: HeaderMap,
    canonical_headers: List[str],
    skip_hidden_rows: bool,
    time_header_indices: set[int],
    date_header_indices: set[int],
    start_time_idx: Optional[int],
    end_time_idx: Optional[int],
    unreadable: List[UnreadableValue],
    change_log: List[ChangeLogEntry],
) -> Tuple[List[CollectedRow], int, int]:
    """Read and normalize one Schedule Sheet. Routing happens later, once the
    whole Batch has been read."""
    rows: List[CollectedRow] = []
    invalid_time_rows = 0
    skipped_hidden = 0
    mode_idx = canonical_headers.index(ASSESSMENT_MODE_HEADER)

    for row_idx in range(header_row_idx + 1, source_sheet.max_row + 1):
        if skip_hidden_rows and source_sheet.row_dimensions[row_idx].hidden:
            skipped_hidden += 1
            change_log.append(
                ChangeLogEntry(
                    workbook_name, source_sheet.title, row_idx,
                    change="Row skipped (hidden in source)",
                )
            )
            continue

        row_values: List[object] = [None] * len(canonical_headers)
        has_data = False

        for canonical_idx, source_idx in header_map.items():
            value = source_sheet.cell(row_idx, source_idx + 1).value
            row_values[canonical_idx] = value
            if not is_blank(value):
                has_data = True

        if not has_data:
            continue

        normalized: List[object] = list(row_values)
        for canonical_idx in time_header_indices:
            normalized[canonical_idx] = normalize_time_value(row_values[canonical_idx])
        for canonical_idx in date_header_indices:
            normalized[canonical_idx] = normalize_date_value(row_values[canonical_idx])
        normalized[mode_idx] = normalize_assessment_mode(row_values[mode_idx])

        location = f"{workbook_name} :: {source_sheet.title} row {row_idx}"
        changes: List[ChangeLogEntry] = []

        def note(column: str, change: str, original: object, new: object = None) -> None:
            changes.append(
                ChangeLogEntry(
                    workbook_name, source_sheet.title, row_idx, column, change, original, new
                )
            )

        for canonical_idx in sorted(time_header_indices | date_header_indices):
            header = canonical_headers[canonical_idx].strip()
            original = row_values[canonical_idx]
            value = normalized[canonical_idx]
            if is_blank(value):
                continue
            if not isinstance(value, (time, date)):
                unreadable.append(UnreadableValue(location, header, value))
                note(header, "Could not read (left unchanged)", original)
            # Real date/time cells only change type (datetime -> date), so only
            # text and number sources count as fixed.
            elif not isinstance(original, (time, date)):
                kind = "Time" if canonical_idx in time_header_indices else "Date"
                note(header, f"{kind} fixed", original, value)
        if normalized[mode_idx] != row_values[mode_idx]:
            note(ASSESSMENT_MODE_HEADER, "Formative/Summative fixed", row_values[mode_idx], normalized[mode_idx])

        bad_time = False
        if start_time_idx is not None and end_time_idx is not None:
            start_val = normalized[start_time_idx]
            end_val = normalized[end_time_idx]
            if isinstance(start_val, time) and isinstance(end_val, time):
                if end_val <= start_val:
                    bad_time = True
                    invalid_time_rows += 1
                    note(
                        canonical_headers[end_time_idx].strip(),
                        "Flagged: End Time not after Start Time",
                        end_val,
                    )
                    print(
                        f"  WARNING row {row_idx}: end time ({end_val}) is not after "
                        f"start time ({start_val}) — cells flagged red"
                    )

        rows.append(
            CollectedRow(workbook_name, normalized, bad_time, source_sheet.title, row_idx, changes)
        )

    return rows, invalid_time_rows, skipped_hidden


def courses_by_workbook(
    rows: List[CollectedRow], course_name_idx: Optional[int]
) -> Dict[str, List[str]]:
    """Distinct Course Names per workbook, in the order first seen."""
    found: Dict[str, Dict[str, str]] = {}
    for row in rows:
        courses = found.setdefault(row.workbook_name, {})
        value = None if course_name_idx is None else row.values[course_name_idx]
        if not is_blank(value):
            courses.setdefault(routing_key(value), display_name(value))
    return {name: list(courses.values()) for name, courses in found.items()}


def plan_tabs(
    rows: List[CollectedRow],
    portfolio_idx: int,
    course_name_idx: Optional[int],
    unassigned_file_tabs: bool = False,
) -> Tuple[str, List[OutputTab]]:
    """Decide the run type for the whole Batch and assign every row to a tab.
    With unassigned_file_tabs, rows without a Portfolio go to a tab named
    after their workbook instead of stopping the run."""
    workbook_names = {row.workbook_name for row in rows}
    has_portfolio = any(not is_blank(row.values[portfolio_idx]) for row in rows)
    run_name = "Check Run" if len(workbook_names) == 1 else "Combine Run"

    if not has_portfolio and not unassigned_file_tabs:
        # Only reached for a single Course: several Courses without a
        # Portfolio stop the run before planning.
        courses = [c for cs in courses_by_workbook(rows, course_name_idx).values() for c in cs]
        name = courses[0] if courses else Path(rows[0].workbook_name).stem
        return run_name, [OutputTab("Course", name, list(rows))]

    # Blank Portfolios reach here only with unassigned_file_tabs; otherwise
    # they stop the run before planning.
    tabs: Dict[str, OutputTab] = {}
    file_tabs: Dict[str, OutputTab] = {}
    for row in rows:
        value = row.values[portfolio_idx]
        if is_blank(value):
            if row.workbook_name not in file_tabs:
                file_tabs[row.workbook_name] = OutputTab("Unassigned", Path(row.workbook_name).stem)
                row.changes.append(
                    ChangeLogEntry(
                        row.workbook_name, row.source_sheet, row.source_row, "portfolio",
                        "No Portfolio: given its own tab",
                    )
                )
            file_tabs[row.workbook_name].rows.append(row)
            continue
        key = routing_key(value)
        if key not in tabs:
            tabs[key] = OutputTab("Portfolio", display_name(value))
        tabs[key].rows.append(row)
    run_type = f"{run_name} (Portfolio Tabs{' and file tabs' if file_tabs else ''})"
    return run_type, list(tabs.values()) + list(file_tabs.values())


def workbooks_missing_portfolio(rows: List[CollectedRow], portfolio_idx: int) -> List[str]:
    """Workbooks with at least one row whose Portfolio is blank, in read order."""
    return list(
        dict.fromkeys(r.workbook_name for r in rows if is_blank(r.values[portfolio_idx]))
    )


def fill_portfolios(
    rows: List[CollectedRow], portfolio_idx: int, assignments: Dict[str, str]
) -> List[ChangeLogEntry]:
    """Give blank-Portfolio rows the Portfolio chosen for their workbook. Logged
    once per workbook, not per row."""
    filled: Dict[str, ChangeLogEntry] = {}
    for row in rows:
        portfolio = assignments.get(row.workbook_name)
        if portfolio and is_blank(row.values[portfolio_idx]):
            row.values[portfolio_idx] = portfolio
            filled.setdefault(
                row.workbook_name,
                ChangeLogEntry(
                    row.workbook_name, column="portfolio",
                    change="Portfolio filled in", new=portfolio,
                ),
            )
    return list(filled.values())


@dataclass
class PortfolioGap:
    """Rows that cannot be routed until someone supplies their Portfolio.

    kind "none": no row has a Portfolio and the Batch holds several Courses.
    kind "blank": some rows have a Portfolio and others are blank.
    """

    kind: str
    courses: Dict[str, List[str]]  # workbook -> Courses on its blank rows
    portfolios: List[str]  # Portfolios found elsewhere in the Batch

    def message(self) -> str:
        lines = [
            f"  {name}: {', '.join(names) or '(no Course Name)'}"
            for name, names in self.courses.items()
        ]
        if self.kind == "none":
            return "\n".join(
                [
                    "These workbooks have no Portfolio and hold more than one Course:",
                    *lines,
                    'If they all go into one Portfolio, run again with --portfolio "<Portfolio name>",',
                    "or with --unassigned-file-tabs to give each workbook its own tab.",
                    "Otherwise add a portfolio column to each workbook and run again.",
                ]
            )
        return "\n".join(
            [
                "These workbooks have rows with no Portfolio:",
                *lines,
                "Add their Portfolio to each workbook and run again, or run again with "
                '--portfolio "<Portfolio name>" to fill every blank with one Portfolio, or with '
                "--unassigned-file-tabs to give each of these workbooks its own tab.",
            ]
        )


def write_tabs(
    output_wb,
    tabs: List[OutputTab],
    output_headers: List[str],
    output_header_indices: List[int],
    time_header_indices: set[int],
    date_header_indices: set[int],
    start_time_idx: Optional[int],
    end_time_idx: Optional[int],
    change_log: List[ChangeLogEntry],
) -> None:
    red_fill = PatternFill(fill_type="solid", fgColor="FFCCCC")
    used_titles: set[str] = set()

    for tab in tabs:
        tab.title = make_unique_sheet_title(tab.full_name, used_titles)
        used_titles.add(tab.title.casefold())

        sheet = output_wb.create_sheet(title=tab.title)
        for col_idx, header in enumerate(output_headers, start=1):
            cell = sheet.cell(1, col_idx, value=header)
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(output_headers))}1"

        for out_row, row in enumerate(tab.rows, start=2):
            for entry in row.changes:
                entry.tab, entry.tab_row = tab.title, out_row
                change_log.append(entry)
            for col_idx, canonical_idx in enumerate(output_header_indices, start=1):
                value = row.values[canonical_idx]
                cell = sheet.cell(out_row, col_idx, value=value)
                if canonical_idx in date_header_indices and isinstance(value, date):
                    cell.number_format = "yyyymmdd"
                if canonical_idx in time_header_indices and isinstance(value, time):
                    cell.number_format = "hh:mm"
                if row.bad_time and canonical_idx in (start_time_idx, end_time_idx):
                    cell.fill = red_fill


def write_change_log(output_wb, entries: List[ChangeLogEntry], used_titles: set[str]) -> str:
    """Append the Change Log tab: what the Wrangler did between the Partner
    Workbooks and the Batch Import. Never imported."""
    title = make_unique_sheet_title(CHANGE_LOG_TAB_TITLE, used_titles)
    sheet = output_wb.create_sheet(title=title)
    for col_idx, header in enumerate(CHANGE_LOG_HEADERS, start=1):
        sheet.cell(1, col_idx, value=header).font = Font(bold=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(CHANGE_LOG_HEADERS))}1"

    for out_row, entry in enumerate(entries, start=2):
        values = [
            entry.source_file,
            entry.source_sheet,
            entry.source_row,
            entry.tab,
            entry.tab_row,
            entry.column,
            entry.change,
            entry.original,
            entry.new,
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = sheet.cell(out_row, col_idx, value=value)
            if isinstance(value, time):
                cell.number_format = "hh:mm"
            elif isinstance(value, date):
                cell.number_format = "yyyymmdd"
    return title


def terms_in(tabs: List[OutputTab]) -> List[str]:
    """Distinct terms (e.g. "Summer 2026") named by Portfolio Tabs."""
    seen: Dict[Tuple[str, str], str] = {}
    for tab in tabs:
        if tab.kind != "Portfolio":
            continue
        match = TERM_PATTERN.search(tab.full_name)
        if match:
            key = (match.group(1).lower(), match.group(2))
            seen.setdefault(key, f"{match.group(1).title()} {match.group(2)}")
    return list(seen.values())


def resolve_input_dir(arg_input_dir: Optional[str]) -> Path:
    """Return the directory to scan for source workbooks."""
    if arg_input_dir:
        p = Path(arg_input_dir).expanduser().resolve()
        if not p.is_dir():
            raise SystemExit(f"--input-dir does not exist or is not a directory: {p}")
        return p

    script_dir = Path(__file__).parent.resolve()
    candidate = script_dir / "schedule-workbooks"
    if candidate.is_dir():
        return candidate

    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return downloads

    raise SystemExit(
        "Could not find a workbook directory. "
        "Create a 'schedule-workbooks' folder next to this script or pass --input-dir."
    )


def resolve_input_paths(input_dir: Path, output_path: Path) -> List[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory is not valid: {input_dir}")

    all_xlsx = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".xlsx"
    )
    lock_files = [path for path in all_xlsx if path.name.startswith("~$")]
    workbook_paths = [path for path in all_xlsx if path not in lock_files]
    print(f"Folder scan: found {len(all_xlsx)} .xlsx file(s) in {input_dir}")
    if lock_files:
        print(f"Folder scan: skipped {len(lock_files)} lock file(s) (~$...)")

    before_output_filter = len(workbook_paths)
    workbook_paths = [path for path in workbook_paths if path != output_path]
    skipped_output = before_output_filter - len(workbook_paths)
    if skipped_output:
        print("Input filter: skipped output workbook path from inputs")

    # Exclude prior runs of this tool so re-running in the same folder does
    # not re-ingest its output: "<folder>-batch-import", plus the older
    # "<folder>-master-schedule" and launcher "<school>_schedule-import" names
    # that may still sit in Partner folders.
    prior_run_markers = ("-batch-import", "-master-schedule", "_schedule-import")
    prior_runs = [
        p for p in workbook_paths if any(marker in p.name for marker in prior_run_markers)
    ]
    if prior_runs:
        workbook_paths = [p for p in workbook_paths if p not in prior_runs]
        print(
            f"Input filter: skipped {len(prior_runs)} earlier output(s): "
            f"{format_sample([p.name for p in prior_runs])}"
        )

    if len(workbook_paths) < 1:
        raise SystemExit(f"No .xlsx workbooks found after filtering in: {input_dir}")

    return workbook_paths


def format_sample(values: List[str], limit: int = 4) -> str:
    if not values:
        return "-"
    shown = values[:limit]
    suffix = " ..." if len(values) > limit else ""
    return ", ".join(shown) + suffix


@dataclass
class Batch:
    """Everything read from a Batch, ready to route and write."""

    input_dir: Path
    workbook_paths: List[Path]
    canonical_headers: List[str]
    portfolio_idx: int
    course_name_idx: Optional[int]
    time_idx: set[int]
    date_idx: set[int]
    start_time_idx: Optional[int]
    end_time_idx: Optional[int]
    rows: List[CollectedRow] = field(default_factory=list)
    change_log: List[ChangeLogEntry] = field(default_factory=list)  # not tied to a row
    unreadable: List[UnreadableValue] = field(default_factory=list)
    unreadable_workbooks: int = 0
    workbooks_with_matching_sheets: int = 0
    processed_schedule_sheets: int = 0
    skipped_for_headers: int = 0
    skipped_for_objective: int = 0
    invalid_time_rows: int = 0
    skipped_hidden_rows: int = 0

    def fill(self, assignments: Dict[str, str]) -> None:
        """Give each workbook's blank-Portfolio rows the Portfolio chosen for it."""
        self.change_log.extend(fill_portfolios(self.rows, self.portfolio_idx, assignments))


@dataclass
class RunResult:
    paths: List[Path]
    tabs: List[OutputTab]
    flagged_rows: int
    unreadable_values: int
    terms: List[str]
    unassigned_tabs: int = 0  # tabs for workbooks with no Portfolio


def portfolio_gap(batch: Batch) -> Optional[PortfolioGap]:
    """What must be answered before the Batch can be written, if anything."""
    idx = batch.portfolio_idx
    blank_rows = [r for r in batch.rows if is_blank(r.values[idx])]
    if not blank_rows:
        return None
    portfolios: Dict[str, str] = {}
    for r in batch.rows:
        if not is_blank(r.values[idx]):
            portfolios.setdefault(routing_key(r.values[idx]), display_name(r.values[idx]))
    if portfolios:
        return PortfolioGap(
            "blank", courses_by_workbook(blank_rows, batch.course_name_idx), list(portfolios.values())
        )
    courses = courses_by_workbook(batch.rows, batch.course_name_idx)
    if len({routing_key(c) for names in courses.values() for c in names}) > 1:
        return PortfolioGap("none", courses, [])
    return None


def read_batch(input_dir: Path, output_path: Path, args: argparse.Namespace) -> Batch:
    """Read and normalize every Partner Workbook in input_dir."""
    match_token = args.tab_contains.strip().lower()
    workbook_paths = resolve_input_paths(input_dir, output_path)

    canonical_headers = CANONICAL_HEADERS.copy()
    alias_lookup = build_alias_lookup(canonical_headers)

    def index_of(name: str) -> Optional[int]:
        return next(
            (i for i, h in enumerate(canonical_headers) if normalize_header(h) == name), None
        )

    portfolio_header_idx = index_of("portfolio")
    if portfolio_header_idx is None:
        raise SystemExit(
            "Canonical headers must include 'portfolio' to split into per-portfolio sheets."
        )
    batch = Batch(
        input_dir=input_dir,
        workbook_paths=workbook_paths,
        canonical_headers=canonical_headers,
        portfolio_idx=portfolio_header_idx,
        course_name_idx=index_of("course name"),
        time_idx={i for i in (index_of("start time"), index_of("end time")) if i is not None},
        date_idx={i for i in (index_of("section date"),) if i is not None},
        start_time_idx=index_of("start time"),
        end_time_idx=index_of("end time"),
    )
    change_log = batch.change_log

    print(f"Loaded hardcoded canonical headers: {len(canonical_headers)}")
    print(f"Portfolio header detected at column {portfolio_header_idx + 1}")
    print("Output will exclude the portfolio column from sheet headers/data")
    if args.skip_formula_materialization:
        print("Step 0 formula materialization: disabled")
    else:
        print("Step 0 formula materialization: enabled")
    if batch.time_idx:
        time_cols = [canonical_headers[idx] for idx in sorted(batch.time_idx)]
        print(f"Time normalization enabled for: {', '.join(time_cols)}")
    if batch.date_idx:
        date_cols = [canonical_headers[idx] for idx in sorted(batch.date_idx)]
        print(f"Date normalization enabled for: {', '.join(date_cols)}")

    for workbook_path in workbook_paths:
        try:
            input_wb = load_workbook(filename=workbook_path, data_only=False)
            input_wb_values = load_workbook(filename=workbook_path, data_only=True)
        except (BadZipFile, InvalidFileException, OSError) as exc:
            batch.unreadable_workbooks += 1
            print(f"Skipped file (unreadable workbook): {workbook_path.name} ({exc})")
            change_log.append(
                ChangeLogEntry(workbook_path.name, change="Workbook skipped (could not open)")
            )
            continue

        values_sheets_by_title = {
            sheet.title: sheet for sheet in input_wb_values.worksheets
        }

        # Order sheets so tab-name hints (if given) are tried first, but all
        # sheets remain candidates — the header fuzzy-check is the real gate.
        if match_token:
            preferred = [
                s for s in input_wb.worksheets if match_token in s.title.lower()
            ]
            remainder = [
                s for s in input_wb.worksheets if match_token not in s.title.lower()
            ]
            candidate_sheets = preferred + remainder
        else:
            candidate_sheets = list(input_wb.worksheets)

        workbook_contributed = False

        for source_sheet in candidate_sheets:

            def log_sheet(change: str, **details) -> None:
                change_log.append(
                    ChangeLogEntry(workbook_path.name, source_sheet.title, change=change, **details)
                )

            values_sheet = values_sheets_by_title.get(source_sheet.title)
            if values_sheet is None:
                print(
                    f"Skipped sheet (missing data-only pair): "
                    f"{workbook_path.name} :: {source_sheet.title}"
                )
                batch.skipped_for_headers += 1
                log_sheet("Sheet skipped (could not read values)")
                continue

            converted_formulas = unresolved_formulas = 0
            if not args.skip_formula_materialization:
                converted_formulas, unresolved_formulas = materialize_formula_cells(
                    source_sheet=source_sheet,
                    values_sheet=values_sheet,
                )
                if converted_formulas or unresolved_formulas:
                    print(
                        f"Step 0 formula materialization: {workbook_path.name} :: "
                        f"{source_sheet.title} (converted {converted_formulas}, "
                        f"unresolved {unresolved_formulas})"
                    )

            header_info = detect_header_row(
                worksheet=source_sheet,
                canonical_headers=canonical_headers,
                threshold=args.fuzzy_threshold,
                alias_lookup=alias_lookup,
                scan_rows=args.header_scan_rows,
                min_header_matches=args.min_header_matches,
            )
            # The header and any title rows above it mark a Mapping Sheet; data rows
            # don't, so a Session Name such as "Objectives Review" never drops a
            # Schedule Sheet. With no header the sheet is skipped either way.
            scan_to = header_info[0] if header_info else args.header_scan_rows
            if sheet_has_objective_header(source_sheet, scan_to):
                batch.skipped_for_objective += 1
                print(
                    f"Skipped sheet (objective header detected): "
                    f"{workbook_path.name} :: {source_sheet.title}"
                )
                log_sheet("Sheet skipped (mapping sheet)")
                continue
            if not header_info:
                batch.skipped_for_headers += 1
                log_sheet("Sheet skipped (no matching headers)")
                continue

            (
                header_row_idx,
                source_headers,
                header_map,
                _match_scores,
                unmatched_source,
                missing_canonical,
            ) = header_info

            # Routing guard: a real schedule sheet must map at least one routing
            # key (portfolio or Course Name). A sheet that maps neither is the
            # signature of a non-schedule sheet (e.g. a pivot/report tab) that
            # passed header detection on a few weak fuzzy matches.
            maps_portfolio = portfolio_header_idx in header_map
            maps_course_name = (
                batch.course_name_idx is not None and batch.course_name_idx in header_map
            )
            if not maps_portfolio and not maps_course_name:
                batch.skipped_for_headers += 1
                print(
                    f"Skipped sheet (no portfolio/Course Name routing key): "
                    f"{workbook_path.name} :: {source_sheet.title}"
                )
                log_sheet("Sheet skipped (no Portfolio or Course Name column)")
                continue

            if not workbook_contributed:
                batch.workbooks_with_matching_sheets += 1
                workbook_contributed = True

            batch.processed_schedule_sheets += 1
            print(
                f"Header match: {workbook_path.name} :: {source_sheet.title} "
                f"(row {header_row_idx}, matched {len(header_map)}/{len(canonical_headers)})"
            )

            if unmatched_source:
                unmatched_headers = [
                    str(source_headers[idx]).strip()
                    for idx in unmatched_source
                    if not is_blank(source_headers[idx])
                ]
                print(f"  Unmapped source headers: {format_sample(unmatched_headers)}")

            if missing_canonical:
                missing_headers = [canonical_headers[idx] for idx in missing_canonical]
                print(f"  Missing canonical headers: {format_sample(missing_headers)}")

            if converted_formulas:
                log_sheet("Formulas replaced with computed values", new=converted_formulas)
            if unresolved_formulas:
                log_sheet("Formulas left as-is (no computed value)", new=unresolved_formulas)
            for canonical_idx, source_idx in sorted(header_map.items()):
                source_header = str(source_headers[source_idx]).strip()
                canonical_header = canonical_headers[canonical_idx].strip()
                if canonical_idx == portfolio_header_idx:
                    log_sheet(
                        "Portfolio column removed",
                        source_row=header_row_idx,
                        original=source_header,
                    )
                elif source_header != canonical_header:
                    log_sheet(
                        "Header renamed",
                        source_row=header_row_idx,
                        column=canonical_header,
                        original=source_header,
                        new=canonical_header,
                    )
            for source_idx in unmatched_source:
                log_sheet(
                    "Column dropped (no matching import header)",
                    source_row=header_row_idx,
                    original=str(source_headers[source_idx]).strip(),
                )
            for canonical_idx in missing_canonical:
                if canonical_idx != portfolio_header_idx:
                    canonical_header = canonical_headers[canonical_idx].strip()
                    log_sheet(
                        "Column added (blank)", column=canonical_header, new=canonical_header
                    )

            sheet_rows, invalid_time, skipped_hidden = collect_rows(
                source_sheet=source_sheet,
                workbook_name=workbook_path.name,
                header_row_idx=header_row_idx,
                header_map=header_map,
                canonical_headers=canonical_headers,
                skip_hidden_rows=args.skip_hidden_rows,
                time_header_indices=batch.time_idx,
                date_header_indices=batch.date_idx,
                start_time_idx=batch.start_time_idx,
                end_time_idx=batch.end_time_idx,
                unreadable=batch.unreadable,
                change_log=change_log,
            )
            batch.rows.extend(sheet_rows)
            batch.invalid_time_rows += invalid_time
            batch.skipped_hidden_rows += skipped_hidden
            print(f"  Rows read: {len(sheet_rows)}")
            if invalid_time:
                print(f"  Rows with invalid time range: {invalid_time}")
            if skipped_hidden:
                print(f"  Rows skipped (hidden in source): {skipped_hidden}")

        input_wb.close()
        input_wb_values.close()

    if not batch.rows:
        raise SystemExit("No schedule rows were written to output.")
    return batch


def change_log_for(batch: Batch, tabs: List[OutputTab]) -> List[ChangeLogEntry]:
    """The Batch-level entries that belong in a workbook holding these tabs:
    entries for the workbooks and sheets that fed its rows, plus skipped
    workbooks and sheets, which fed no workbook and so appear in every one."""
    fed_all = {(r.workbook_name, r.source_sheet) for r in batch.rows}
    fed_here = {(r.workbook_name, r.source_sheet) for tab in tabs for r in tab.rows}

    def belongs(entry: ChangeLogEntry) -> bool:
        if entry.source_sheet:
            key = (entry.source_file, entry.source_sheet)
            return key in fed_here or key not in fed_all
        return entry.source_file in {f for f, _ in fed_here} or entry.source_file not in {
            f for f, _ in fed_all
        }

    return [entry for entry in batch.change_log if belongs(entry)]


def save_workbook(batch: Batch, tabs: List[OutputTab], path: Path) -> int:
    """Write tabs plus their Change Log to path. Returns the Change Log length."""
    output_header_indices = [
        idx for idx in range(len(batch.canonical_headers)) if idx != batch.portfolio_idx
    ]
    change_log = change_log_for(batch, tabs)
    output_wb = Workbook()
    output_wb.remove(output_wb.active)
    write_tabs(
        output_wb,
        tabs,
        output_headers=[batch.canonical_headers[idx] for idx in output_header_indices],
        output_header_indices=output_header_indices,
        time_header_indices=batch.time_idx,
        date_header_indices=batch.date_idx,
        start_time_idx=batch.start_time_idx,
        end_time_idx=batch.end_time_idx,
        change_log=change_log,
    )
    write_change_log(output_wb, change_log, used_titles={tab.title.casefold() for tab in tabs})
    path.parent.mkdir(parents=True, exist_ok=True)
    output_wb.save(path)
    return len(change_log)


def write_batch_import(
    batch: Batch, output_path: Path, file_per_tab: bool = False, unassigned_file_tabs: bool = False
) -> RunResult:
    """Route every row to a tab and write the Batch Import: one workbook at
    output_path, or with file_per_tab one workbook per tab in the output_path
    folder. Every row must have a Portfolio unless the Batch holds a single
    Course (see portfolio_gap) or unassigned_file_tabs is set."""
    run_type, tabs = plan_tabs(
        batch.rows, batch.portfolio_idx, batch.course_name_idx, unassigned_file_tabs
    )
    if file_per_tab:
        used_names: set[str] = set()
        groups = [
            ([tab], output_path / make_unique_file_name(tab.full_name, used_names))
            for tab in tabs
        ]
    else:
        groups = [(tabs, output_path)]
    paths: List[Path] = []
    change_log_entries = 0
    for group_tabs, path in groups:
        change_log_entries += save_workbook(batch, group_tabs, path)
        paths.append(path)

    print("")
    for path in paths:
        print(f"Saved Batch Import:  {path}")
    print(f"Input directory:        {batch.input_dir}")
    print(f"Run type: {run_type}")
    print(f"Input workbooks considered: {len(batch.workbook_paths)}")
    print(f"Unreadable workbooks skipped: {batch.unreadable_workbooks}")
    print(f"Workbooks with matching sheets: {batch.workbooks_with_matching_sheets}")
    print(f"Schedule sheets processed: {batch.processed_schedule_sheets}")
    print(f"Mapping sheets skipped (objective header):  {batch.skipped_for_objective}")
    print(f"Schedule sheets skipped (header detection):  {batch.skipped_for_headers}")
    print(f"Tabs created: {len(tabs)}")
    for tab in tabs:
        print(f"  {tab.title}  <-  {tab.kind}: {tab.full_name}  ({len(tab.rows)} rows)")
    print(f"Rows with invalid time range:  {batch.invalid_time_rows}")
    print(f"Rows skipped (hidden in source): {batch.skipped_hidden_rows}")
    print(f"Total rows written: {len(batch.rows)}")
    print(f"Change Log entries: {change_log_entries} (tab '{CHANGE_LOG_TAB_TITLE}', never imported)")

    terms = terms_in(tabs)
    if len(terms) > 1:
        print(f"WARNING: Portfolios span more than one term: {', '.join(terms)}")

    unreadable_values = batch.unreadable
    if unreadable_values:
        print(f"Values left unchanged (could not be read): {len(unreadable_values)}")
        for item in unreadable_values[:MAX_UNREADABLE_LISTED]:
            print(f"  {item.location}, {item.header}: {item.value!r}")
        if len(unreadable_values) > MAX_UNREADABLE_LISTED:
            print(f"  ... and {len(unreadable_values) - MAX_UNREADABLE_LISTED} more")

    return RunResult(
        paths=paths,
        tabs=tabs,
        flagged_rows=batch.invalid_time_rows,
        unreadable_values=len(unreadable_values),
        terms=terms,
        unassigned_tabs=sum(1 for tab in tabs if tab.kind == "Unassigned"),
    )


def default_output(input_dir: Path, file_per_tab: bool = False) -> Path:
    """<input-dir>/<input-dir-name>-batch-import[.xlsx]"""
    name = f"{input_dir.name}-batch-import"
    return input_dir / (name if file_per_tab else f"{name}.xlsx")


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    input_dir = resolve_input_dir(args.input_dir)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = default_output(input_dir, args.file_per_tab)

    batch = read_batch(input_dir, output_path, args)
    if args.portfolio and args.portfolio.strip():
        portfolio = display_name(args.portfolio)
        batch.fill(
            {name: portfolio for name in workbooks_missing_portfolio(batch.rows, batch.portfolio_idx)}
        )
    gap = portfolio_gap(batch)
    if gap and not args.unassigned_file_tabs:
        raise SystemExit(gap.message())
    write_batch_import(batch, output_path, args.file_per_tab, args.unassigned_file_tabs)


if __name__ == "__main__":
    main()
