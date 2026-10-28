#!/usr/bin/env python3
"""
One45 Schedule Wrangler window: choose a Batch folder, make the Batch Import,
open it. A front end for create-master-schedule-workbook.py; see GLOSSARY.md.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wrangler", HERE / "create-master-schedule-workbook.py")
wrangler = importlib.util.module_from_spec(_spec)
sys.modules["wrangler"] = wrangler  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(wrangler)

APP_NAME = "One45 Schedule Wrangler"
DOWNLOADS = Path.home() / "Downloads"

# Answer meaning "give each workbook without a Portfolio its own tab".
OWN_TABS = "own-tabs"

# Given a PortfolioGap, return {workbook name: Portfolio}, OWN_TABS, or None to cancel.
AskPortfolios = Callable[["wrangler.PortfolioGap"], object]


class _LineWriter(io.TextIOBase):
    """Passes each printed line to a callback as it is written."""

    def __init__(self, on_line: Callable[[str], None]):
        self._on_line = on_line
        self._pending = ""

    def write(self, text: str) -> int:
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            self._on_line(line)
        return len(text)


def make_batch_import(
    folder: Path,
    file_per_tab: bool,
    ask: AskPortfolios,
    on_line: Callable[[str], None],
    replace: bool = False,
) -> Optional["wrangler.RunResult"]:
    """Read the Batch in folder, ask for any missing Portfolios, then write the
    Batch Import next to it. Returns None when the question is cancelled.
    Raises SystemExit with a readable message when the Batch can't be used.

    replace removes an earlier folder of files, but only once there is
    something to write in its place."""
    output = wrangler.default_output(folder, file_per_tab)
    options = wrangler.parse_args(["--input-dir", str(folder)])
    with contextlib.redirect_stdout(_LineWriter(on_line)):
        batch = wrangler.read_batch(folder, output, options)
        gap = wrangler.portfolio_gap(batch)
        own_tabs = False
        if gap:
            answers = ask(gap)
            if answers == OWN_TABS:
                own_tabs = True
            elif not answers:
                return None
            else:
                batch.fill(answers)
                if wrangler.portfolio_gap(batch):
                    return None
        if replace and output.is_dir():
            shutil.rmtree(output)
        return wrangler.write_batch_import(batch, output, file_per_tab, own_tabs)


def support_dir() -> Path:
    """Per-person app data: settings and the instructions-seen marker."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def first_open(marker: Path) -> bool:
    """True the first time it is called for marker, False after that."""
    if marker.exists():
        return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    return True


@dataclass
class Settings:
    folder: Path
    file_per_tab: bool


def load_settings(path: Path) -> Settings:
    """The last folder and output choice, falling back to ~/Downloads and one file."""
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = {}
    folder = Path(saved.get("folder") or DOWNLOADS)
    return Settings(
        folder=folder if folder.is_dir() else DOWNLOADS,
        file_per_tab=bool(saved.get("file_per_tab", False)),
    )


def save_settings(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"folder": str(settings.folder), "file_per_tab": settings.file_per_tab}))


def existing_output(folder: Path, file_per_tab: bool) -> Optional[Path]:
    """The Batch Import (file or folder) this run would replace, if any."""
    output = wrangler.default_output(folder, file_per_tab)
    return output if output.exists() else None


def keep_old(path: Path, now: datetime) -> Path:
    """Rename an earlier Batch Import out of the way. The new name keeps
    "-batch-import" so the next run never reads it as a Partner Workbook."""
    suffix = "" if path.is_dir() else path.suffix
    stem = path.name[: len(path.name) - len(suffix)]
    base = f"{stem} (previous {now:%Y-%m-%d %H%M})"
    kept, counter = path.with_name(f"{base}{suffix}"), 2
    while kept.exists():
        kept = path.with_name(f"{base} {counter}{suffix}")
        counter += 1
    path.rename(kept)
    return kept


def short_path(path: Path, limit: int = 60) -> str:
    """path for display: ~ for home, and the middle dropped when too long,
    keeping the start and the folder name."""
    text = str(path)
    home = str(Path.home())
    if text == home or text.startswith(home + os.sep):
        text = "~" + text[len(home):]
    if len(text) <= limit:
        return text
    segments = text.split(os.sep)
    head, tail = os.sep.join(segments[:2]), [segments[-1]]
    for segment in reversed(segments[2:-1]):
        if len(os.sep.join([head, "...", segment, *tail])) > limit:
            break
        tail.insert(0, segment)
    return os.sep.join([head, "...", *tail])


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def callout(result: "wrangler.RunResult") -> str:
    """Plain-language list of what to fix before importing; empty when nothing."""
    notes = []
    if result.flagged_rows:
        notes.append(
            f"{_count(result.flagged_rows, 'row', 'rows')} flagged red: End Time is not after "
            "Start Time. Fix the times before importing."
        )
    if result.unreadable_values:
        notes.append(
            f"{_count(result.unreadable_values, 'date or time', 'dates or times')} could not be "
            "read and were left as they were. The Change Log lists them."
        )
    if result.unassigned_tabs:
        notes.append(
            f"{_count(result.unassigned_tabs, 'file', 'files')} had no Portfolio and "
            f"{'got its' if result.unassigned_tabs == 1 else 'each got their'} own tab, named after "
            "the file. Choose the right Portfolio when you import those tabs."
        )
    if len(result.terms) > 1:
        notes.append(
            f"The Portfolios span more than one term ({' and '.join(result.terms)}). "
            "Check that this is the right Batch."
        )
    return "\n".join(notes)


# (heading, [(marker, text, [sub-items])]) sections for the How to use popup.
INSTRUCTIONS = [
    (
        "Prerequisites",
        [
            ("\u2022", "Place all partner curriculum import files into a single folder.", []),
            ("\u2022", "Do not use subfolders.", []),
            (
                "\u2022",
                "Workbooks may contain mapping tabs or other non-schedule sheets alongside schedule "
                "data. The Wrangler automatically evaluates each tab and skips non-qualifying sheets.",
                [],
            ),
        ],
    ),
    (
        "Steps to Generate the Batch Import",
        [
            (
                "1.",
                "Select output format and destination:",
                [
                    "One file, a tab per Portfolio: Saves <folder>-batch-import.xlsx directly in "
                    "the source folder.",
                    "A separate file per Portfolio: Saves individual files in a new "
                    "<folder>-batch-import subfolder.",
                ],
            ),
            (
                "2.",
                'Click "Make Batch Import."',
                [
                    "If an input workbook lacks a portfolio designation, a prompt lets you assign "
                    "one, or give each such workbook its own tab named after the file.",
                ],
            ),
            ("3.", 'Click "Open Batch Import" (or "Open folder") to inspect the output.', []),
        ],
    ),
    (
        "Output Validation & Pre-Import Checks",
        [
            ("", "Before importing into One45:", []),
            (
                "\u2022",
                "Resolve red cells: Any row highlighted in red contains an invalid time range (End "
                "Time is earlier than or equal to Start Time). Correct these values in the sheet.",
                [],
            ),
            (
                "\u2022",
                "Review the Change Log tab: Audit automated adjustments row-by-row. Do not import "
                "the Change Log tab into One45.",
                [],
            ),
            (
                "\u2022",
                "Import target: Upload each portfolio tab or file into its matching target portfolio.",
                [],
            ),
        ],
    ),
]

# (heading, column headings, rows) for the reference table under the sections.
PROCESSING_TABLE = (
    "Tool Processing & Filtering Logic (Reference)",
    ("Condition / Content", "System Behavior"),
    [
        ("Temporary Excel lock files (~$*)", "Skipped automatically."),
        ("Previous Batch Import exports", "Skipped automatically."),
        (
            "Non-schedule sheets (e.g., Mapping/objectives tabs)",
            "Skipped. The tool runs a fuzzy match across column headers in each file and tab. If the "
            "headers do not meet the minimum qualification threshold for a schedule import, the tab "
            "is excluded.",
        ),
        ("Portfolio column", "Stripped from processed sheets."),
        ("Qualifying schedule headers", "Normalized to match One45 importer specifications."),
        ("Formulas", "Converted to static values."),
        ("Dates and times", "Standardized to importer format."),
    ],
)


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        import subprocess

        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)


def workbook_label(name: str, courses: list, shown: int = 3) -> str:
    """"file.xlsx (Course A, Course B, Course C and 12 more)" for dialogs."""
    if not courses:
        return f"{name} (no Course Name)"
    listed = ", ".join(courses[:shown])
    more = f" and {len(courses) - shown} more" if len(courses) > shown else ""
    return f"{name} ({listed}{more})"


def course_list(gap: "wrangler.PortfolioGap", shown: int = 12) -> str:
    """One line per workbook, at most shown lines, for messages and the log."""
    items = list(gap.courses.items())
    lines = [f"   {workbook_label(name, courses)}" for name, courses in items[:shown]]
    if len(items) > shown:
        lines.append(f"   ... and {len(items) - shown} more workbooks")
    return "\n".join(lines)


def main() -> None:
    import queue
    import threading
    import tkinter as tk
    from tkinter import filedialog, ttk
    from tkinter import font as tkfont

    settings_path = support_dir() / "settings.json"
    settings = load_settings(settings_path)
    events: "queue.Queue[tuple]" = queue.Queue()

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("760x540")
    root.minsize(640, 460)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(5, weight=1)

    folder_var = tk.StringVar(value=str(settings.folder))
    folder_shown = tk.StringVar(value=short_path(settings.folder))
    file_per_tab_var = tk.BooleanVar(value=settings.file_per_tab)

    ttk.Label(frame, text="Folder:").grid(row=0, column=0, sticky="w")
    ttk.Label(frame, textvariable=folder_shown).grid(row=0, column=1, sticky="w", padx=8)

    def choose_folder() -> None:
        chosen = filedialog.askdirectory(initialdir=folder_var.get(), title="Choose the Batch folder")
        if chosen:
            folder_var.set(chosen)
            folder_shown.set(short_path(Path(chosen)))

    ttk.Button(frame, text="Choose folder...", command=choose_folder).grid(row=0, column=2, sticky="e")

    ttk.Label(frame, text="Output:").grid(row=1, column=0, sticky="w", pady=(12, 0))
    ttk.Radiobutton(
        frame, text="One file, a tab per Portfolio", variable=file_per_tab_var, value=False
    ).grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(12, 0))
    ttk.Radiobutton(
        frame, text="A separate file per Portfolio", variable=file_per_tab_var, value=True
    ).grid(row=2, column=1, columnspan=2, sticky="w", padx=8)

    buttons = ttk.Frame(frame)
    buttons.grid(row=3, column=0, columnspan=3, sticky="ew", pady=12)
    make_button = ttk.Button(buttons, text="Make Batch Import")
    make_button.pack(side="left")

    callout_label = tk.Label(
        frame, name="callout", justify="left", anchor="w", wraplength=680, bg="#FFF4CE", fg="#5C4400", padx=10, pady=8
    )
    log_frame = ttk.Frame(frame)
    log_frame.grid(row=5, column=0, columnspan=3, sticky="nsew")
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    log = tk.Text(log_frame, height=14, wrap="word", state="disabled", borderwidth=0)
    log.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=log.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    log.configure(yscrollcommand=scrollbar.set)
    open_button = ttk.Button(frame, text="Open Batch Import", state="disabled")
    open_button.grid(row=6, column=2, sticky="e", pady=(12, 0))
    last_result: Dict[str, Path] = {}

    def write_log(line: str) -> None:
        log.configure(state="normal")
        log.insert("end", line + "\n")
        log.see("end")
        log.configure(state="disabled")

    def show_callout(text: str) -> None:
        if text:
            callout_label.configure(text=text)
            callout_label.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        else:
            callout_label.grid_remove()

    def dialog(title: str) -> tk.Toplevel:
        window = tk.Toplevel(root)
        window.title(title)
        window.transient(root)
        window.resizable(False, False)
        return window

    def choose(title: str, message: str, choices: list) -> Optional[str]:
        """A message with one button per choice; returns the chosen label."""
        window = dialog(title)
        picked: Dict[str, str] = {}
        body = ttk.Frame(window, padding=16)
        body.pack(fill="both")
        ttk.Label(body, text=message, wraplength=520, justify="left").pack(anchor="w")
        row_ = ttk.Frame(body)
        row_.pack(anchor="e", pady=(16, 0))
        for label in choices:
            def pick(label=label):
                picked["choice"] = label
                window.destroy()
            ttk.Button(row_, text=label, command=pick).pack(side="left", padx=(8, 0))
        window.grab_set()
        root.wait_window(window)
        return picked.get("choice")

    def show_instructions() -> None:
        window = dialog("How to use")
        body = ttk.Frame(window, padding=(20, 16))
        body.pack(fill="both")
        body.columnconfigure(2, weight=1)
        heading_font = tkfont.nametofont("TkDefaultFont").copy()
        heading_font.configure(weight="bold", size=heading_font.cget("size") + 1)
        row_ = 0
        for heading, items in INSTRUCTIONS:
            ttk.Label(body, text=heading, font=heading_font).grid(
                row=row_, column=0, columnspan=3, sticky="w", pady=(0 if row_ == 0 else 14, 4)
            )
            row_ += 1
            for marker, text, subitems in items:
                ttk.Label(body, text=marker).grid(row=row_, column=0, sticky="ne", padx=(0, 6), pady=2)
                ttk.Label(body, text=text, wraplength=540, justify="left").grid(
                    row=row_, column=1, columnspan=2, sticky="w", pady=2
                )
                row_ += 1
                for sub in subitems:
                    ttk.Label(body, text="\u2022").grid(row=row_, column=1, sticky="ne", padx=(8, 6), pady=1)
                    ttk.Label(body, text=sub, wraplength=510, justify="left").grid(
                        row=row_, column=2, sticky="w", pady=1
                    )
                    row_ += 1
        table_heading, columns, table_rows = PROCESSING_TABLE
        ttk.Label(body, text=table_heading, font=heading_font).grid(
            row=row_, column=0, columnspan=3, sticky="w", pady=(14, 4)
        )
        row_ += 1
        table = ttk.Frame(body)
        table.grid(row=row_, column=0, columnspan=3, sticky="w")
        row_ += 1
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        for r, cells in enumerate([columns, *table_rows]):
            for c, cell in enumerate(cells):
                ttk.Label(
                    table, text=cell, wraplength=200 if c == 0 else 360, justify="left",
                    font=bold if r == 0 else None,
                ).grid(row=r, column=c, sticky="nw", padx=(0, 16), pady=2)
        ttk.Button(body, text="Got it", command=window.destroy).grid(
            row=row_, column=0, columnspan=3, sticky="e", pady=(18, 0)
        )
        window.grab_set()
        root.wait_window(window)

    ttk.Button(buttons, text="How to use", command=show_instructions).pack(side="right")

    def ask_portfolio_name() -> Optional[str]:
        window = dialog("Portfolio")
        answer: Dict[str, str] = {}
        body = ttk.Frame(window, padding=16)
        body.pack(fill="both")
        ttk.Label(body, text="Which Portfolio are they in? For example: Summer 2026, MED 4").pack(anchor="w")
        name = tk.StringVar()
        entry = ttk.Entry(body, textvariable=name, width=48)
        entry.pack(fill="x", pady=8)
        entry.focus_set()
        row_ = ttk.Frame(body)
        row_.pack(anchor="e")

        def ok() -> None:
            if name.get().strip():
                answer["name"] = name.get().strip()
                window.destroy()

        ttk.Button(row_, text="Cancel", command=window.destroy).pack(side="left")
        ttk.Button(row_, text="Continue", command=ok).pack(side="left", padx=(8, 0))
        window.bind("<Return>", lambda _e: ok())
        window.grab_set()
        root.wait_window(window)
        return answer.get("name")

    def ask_blank_portfolios(gap: "wrangler.PortfolioGap") -> object:
        window = dialog("Missing Portfolios")
        answer: Dict[str, object] = {}
        body = ttk.Frame(window, padding=16)
        body.pack(fill="both")
        ttk.Label(
            body,
            text="These workbooks have rows with no Portfolio. Pick or type the Portfolio for each, "
            "or give each workbook its own tab and choose the Portfolio when you import it.",
            wraplength=520,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        # Long lists scroll instead of growing past the screen.
        holder = ttk.Frame(body)
        holder.grid(row=1, column=0, columnspan=2, sticky="nsew")
        canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0, bg=root.cget("bg"))
        rows_frame = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=rows_frame, anchor="nw")
        choices: Dict[str, tk.StringVar] = {}
        for i, (name, courses) in enumerate(gap.courses.items()):
            ttk.Label(rows_frame, text=workbook_label(name, courses), wraplength=300, justify="left").grid(
                row=i, column=0, sticky="w", padx=(0, 12), pady=3
            )
            var = tk.StringVar(value=gap.portfolios[0] if len(gap.portfolios) == 1 else "")
            ttk.Combobox(rows_frame, textvariable=var, values=gap.portfolios, width=28).grid(
                row=i, column=1, sticky="w", pady=3
            )
            choices[name] = var
        rows_frame.update_idletasks()
        canvas.configure(
            width=rows_frame.winfo_reqwidth(),
            height=min(rows_frame.winfo_reqheight(), 360),
            scrollregion=(0, 0, rows_frame.winfo_reqwidth(), rows_frame.winfo_reqheight()),
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        if rows_frame.winfo_reqheight() > 360:
            scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            canvas.configure(yscrollcommand=scrollbar.set)
            window.bind(
                "<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
            )
        warning = ttk.Label(body, text="", foreground="#B00020")
        warning.grid(row=2, column=0, columnspan=2, sticky="w")
        row_ = ttk.Frame(body)
        row_.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def ok() -> None:
            picked = {name: var.get().strip() for name, var in choices.items()}
            if not all(picked.values()):
                warning.configure(text="Every workbook needs a Portfolio.")
                return
            answer["picked"] = picked
            window.destroy()

        def own_tabs() -> None:
            answer["picked"] = OWN_TABS
            window.destroy()

        ttk.Button(row_, text="Cancel", command=window.destroy).pack(side="left")
        ttk.Button(row_, text="Give each its own tab", command=own_tabs).pack(side="left", padx=(8, 0))
        ttk.Button(row_, text="Continue", command=ok).pack(side="left", padx=(8, 0))
        window.grab_set()
        root.wait_window(window)
        return answer.get("picked")

    def answer_gap(gap: "wrangler.PortfolioGap") -> object:
        if gap.kind == "blank":
            return ask_blank_portfolios(gap)
        message = (
            "These workbooks have no Portfolio and hold more than one Course:\n\n"
            f"{course_list(gap)}\n\nAre they all in the same Portfolio?"
        )
        choice = choose(
            "No Portfolio", message, ["Cancel", "No", "Give each its own tab", "Yes, the same Portfolio"]
        )
        if choice == "Give each its own tab":
            return OWN_TABS
        if choice == "No":
            write_log("")
            write_log("Add a portfolio column to these workbooks (or ask the Partner to), then run again:")
            write_log(course_list(gap, shown=len(gap.courses)))
            return None
        if choice != "Yes, the same Portfolio":
            return None
        name = ask_portfolio_name()
        return {workbook: name for workbook in gap.courses} if name else None

    def worker(folder: Path, file_per_tab: bool, replace: bool) -> None:
        def ask(gap):
            reply: "queue.Queue" = queue.Queue()
            events.put(("ask", gap, reply))
            return reply.get()

        try:
            result = make_batch_import(
                folder, file_per_tab, ask, lambda line: events.put(("line", line)), replace
            )
            events.put(("done", result, file_per_tab))
        except SystemExit as stop:
            events.put(("stopped", str(stop.code)))
        except Exception as error:  # surfaced in the log rather than lost in a thread
            events.put(("stopped", f"Something went wrong: {error!r}"))

    def poll() -> None:
        try:
            handle_events()
        except tk.TclError:  # window closed while a question was open
            return
        root.after(100, poll)

    def handle_events() -> None:
        try:
            while True:
                event = events.get_nowait()
                kind = event[0]
                if kind == "line":
                    write_log(event[1])
                elif kind == "ask":
                    event[2].put(answer_gap(event[1]))
                elif kind == "done":
                    result, file_per_tab = event[1], event[2]
                    make_button.configure(state="normal")
                    if result is None:
                        write_log("Stopped. Nothing was written.")
                        continue
                    target = result.paths[0].parent if file_per_tab else result.paths[0]
                    last_result["target"] = target
                    open_button.configure(
                        state="normal", text="Open folder" if file_per_tab else "Open Batch Import"
                    )
                    show_callout(callout(result))
                elif kind == "stopped":
                    make_button.configure(state="normal")
                    write_log("")
                    write_log(event[1])
        except queue.Empty:
            pass

    def make() -> None:
        folder = Path(folder_var.get())
        file_per_tab = file_per_tab_var.get()
        save_settings(settings_path, Settings(folder, file_per_tab))
        existing = existing_output(folder, file_per_tab)
        replace = False
        if existing:
            choice = choose(
                "Batch Import already exists",
                f"A Batch Import already exists in this folder:\n\n{existing.name}",
                ["Cancel", "Keep the old one", "Replace it"],
            )
            if choice == "Keep the old one":
                keep_old(existing, datetime.now())
            elif choice == "Replace it":
                replace = True
            else:
                return
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        show_callout("")
        open_button.configure(state="disabled")
        make_button.configure(state="disabled")
        threading.Thread(target=worker, args=(folder, file_per_tab, replace), daemon=True).start()

    make_button.configure(command=make)
    open_button.configure(command=lambda: open_path(last_result["target"]))

    root.after(100, poll)
    if first_open(support_dir() / "instructions-seen"):
        root.after(200, show_instructions)
    root.mainloop()


if __name__ == "__main__":
    main()
