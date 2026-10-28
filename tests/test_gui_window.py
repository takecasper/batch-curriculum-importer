"""Drives the real window: clicks buttons, answers dialogs, checks what is written.

Opens windows on screen, so it only runs when asked:

    GUI_TESTS=1 .venv/bin/python -m unittest discover -s tests -p test_gui_window.py

Set GUI_SHOTS=<folder> as well to save a screenshot of each dialog (macOS; the
terminal needs Screen Recording permission, or the images come out blank).
"""

import os
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from datetime import time
from pathlib import Path
from tkinter import ttk
from unittest import mock

from test_gui import gui
from test_wrangler import HEADERS, row, write_partner_workbook

STEP_TIMEOUT_MS = 15000
TICK_MS = 50


def widgets(w):
    yield w
    for child in w.winfo_children():
        yield from widgets(child)


def root():
    return tk._default_root


def dialog(title):
    """The open dialog with this title, or None."""
    for w in root().winfo_children():
        if isinstance(w, tk.Toplevel) and w.winfo_exists() and w.title() == title:
            return w
    return None


def button(text):
    """The enabled button with this text, or None."""
    for w in widgets(root()):
        if isinstance(w, ttk.Button) and w.cget("text") == text and "disabled" not in w.state():
            return w
    return None


def log_text():
    return next(w for w in widgets(root()) if isinstance(w, tk.Text)).get("1.0", "end")


class WindowTestCase(unittest.TestCase):
    """Runs gui.main() with HOME in a temp folder and plays a list of steps.

    Each step is (wait_for, action): once wait_for() is truthy, action() runs.
    Actions that open a dialog block until it closes, so the next tick is
    scheduled before each action runs."""

    def setUp(self):
        if not os.environ.get("GUI_TESTS"):
            self.skipTest("set GUI_TESTS=1 to drive the real window")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(home), "APPDATA": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.batch = home / "Downloads" / "spring-batch"
        self.batch.mkdir(parents=True)
        self.shots = os.environ.get("GUI_SHOTS")

    def save_settings(self, file_per_tab=False, seen_instructions=True):
        gui.save_settings(gui.support_dir() / "settings.json", gui.Settings(self.batch, file_per_tab))
        if seen_instructions:
            (gui.support_dir() / "instructions-seen").touch()

    def shot(self, title):
        """Screenshot the dialog with this title (or the main window) when GUI_SHOTS is set."""
        if not self.shots or sys.platform != "darwin":
            return
        w = dialog(title) or root()
        w.update()
        region = f"{w.winfo_rootx()},{w.winfo_rooty()},{w.winfo_width()},{w.winfo_height()}"
        Path(self.shots).mkdir(parents=True, exist_ok=True)
        name = f"{self.id().rsplit('.', 1)[-1]}-{title}.png".replace(" ", "-")
        subprocess.run(["screencapture", "-x", "-R", region, str(Path(self.shots) / name)], check=False)

    def play(self, steps):
        steps = list(steps)
        state = {"next": 0, "waited": 0, "error": None}

        def stop(error=None):
            state["error"] = state["error"] or error
            if root():
                root().destroy()

        def tick():
            if not root():  # the window closed under us; play() reports what is left
                return
            if state["next"] == len(steps):
                return stop()
            wait_for, action = steps[state["next"]]
            try:
                ready = wait_for()
            except tk.TclError:
                ready = False
            if not ready:
                state["waited"] += TICK_MS
                if state["waited"] > STEP_TIMEOUT_MS:
                    return stop(f"step {state['next'] + 1} never became ready ({wait_for.__name__})")
                root().after(TICK_MS, tick)
                return
            state["next"] += 1
            state["waited"] = 0
            root().after(TICK_MS, tick)
            try:
                action()
            except Exception as error:  # Tk would print and swallow it
                stop(f"step {state['next']} failed: {error!r}")

        real_mainloop = tk.Tk.mainloop

        def mainloop(window, n=0):
            window.after(TICK_MS, tick)
            real_mainloop(window, n)

        # No probe Tk() first: on macOS a root destroyed before its mainloop
        # ever runs makes the next root segfault.
        with mock.patch.object(tk.Tk, "mainloop", mainloop):
            try:
                gui.main()
            except tk.TclError as error:
                if "display" not in str(error):
                    raise
                self.skipTest(f"no display: {error}")
        if state["error"]:
            self.fail(state["error"])
        if state["next"] < len(steps):
            self.fail(f"window closed before step {state['next'] + 1} of {len(steps)}")


def showing(title):
    def wait_for():
        return dialog(title)

    wait_for.__name__ = f"dialog {title!r}"
    return wait_for


def enabled(text):
    def wait_for():
        return button(text) and not any(isinstance(w, tk.Toplevel) for w in root().winfo_children())

    wait_for.__name__ = f"button {text!r}"
    return wait_for


def logged(text):
    def wait_for():
        return text in log_text()

    wait_for.__name__ = f"log line {text!r}"
    return wait_for


def press(text):
    return lambda: button(text).invoke()


def outputs(folder):
    return sorted(p.name for p in folder.iterdir() if "batch-import" in p.name)


class WindowTests(WindowTestCase):
    def test_first_open_shows_instructions_then_fills_a_missing_portfolio_and_keeps_the_old_import(self):
        write_partner_workbook(self.batch, "md468.xlsx", [row("Summer 2026, MED 4", "MD468 Pharm", start=time(11), end=time(10))])
        write_partner_workbook(self.batch, "md300.xlsx", [row(None, "MD300 Spanish")])
        self.save_settings(seen_instructions=False)
        seen = {}

        def note_callout():
            seen["callout"] = next(
                w.cget("text") for w in widgets(root()) if w.winfo_name() == "callout" and w.winfo_manager()
            )
            seen["first"] = outputs(self.batch)

        self.play([
            (showing("How to use"), lambda: (self.shot("How to use"), press("Got it")())),
            (enabled("Make Batch Import"), lambda: (self.shot("main"), press("Make Batch Import")())),
            (showing("Missing Portfolios"), lambda: (self.shot("Missing Portfolios"), press("Continue")())),
            (enabled("Open Batch Import"), note_callout),
            (enabled("Make Batch Import"), press("Make Batch Import")),
            (showing("Batch Import already exists"), lambda: (self.shot("Batch Import already exists"), press("Keep the old one")())),
            (showing("Missing Portfolios"), press("Continue")),
            (enabled("Open Batch Import"), lambda: None),
        ])

        self.assertEqual(seen["first"], ["spring-batch-batch-import.xlsx"])
        self.assertIn("End Time", seen["callout"])
        kept = [name for name in outputs(self.batch) if "previous" in name]
        self.assertEqual(len(outputs(self.batch)), 2)
        self.assertEqual(len(kept), 1)

    def test_answering_no_after_replace_leaves_the_old_folder_of_files(self):
        headers = HEADERS[1:]
        write_partner_workbook(self.batch, "md468.xlsx", [row(None, "MD468 Pharm")[1:], row(None, "MD469 Anat")[1:]], headers)
        write_partner_workbook(self.batch, "md300.xlsx", [row(None, "MD300 Spanish")[1:], row(None, "MD301 Ethics")[1:]], headers)
        self.save_settings(file_per_tab=True)
        output = self.batch / "spring-batch-batch-import"
        seen = {}

        self.play([
            (enabled("Make Batch Import"), press("Make Batch Import")),
            (showing("No Portfolio"), lambda: (self.shot("No Portfolio"), press("Give each its own tab")())),
            (enabled("Open folder"), lambda: seen.setdefault("files", sorted(p.name for p in output.iterdir()))),
            (enabled("Make Batch Import"), press("Make Batch Import")),
            (showing("Batch Import already exists"), press("Replace it")),
            (showing("No Portfolio"), press("No")),
            (logged("Stopped. Nothing was written."), lambda: seen.setdefault("log", log_text())),
        ])

        self.assertTrue(seen["files"])
        self.assertEqual(sorted(p.name for p in output.iterdir()), seen["files"])
        self.assertIn("Add a portfolio column", seen["log"])

    def test_missing_portfolios_dialog_fits_on_screen_for_a_large_batch(self):
        write_partner_workbook(self.batch, "assigned.xlsx", [row("Summer 2026, MED 4", "MD100 Intro")])
        for i in range(40):
            courses = [row(None, f"PGME Postgrad Contact List Course {i}-{c}") for c in range(30)]
            write_partner_workbook(self.batch, f"pgme-postgrad-contact-list-{i:02}-with-a-long-name.xlsx", courses)
        self.save_settings()
        size = {}

        def measure():
            w = dialog("Missing Portfolios")
            w.update_idletasks()
            size.update(width=w.winfo_width(), height=w.winfo_height())
            self.shot("Missing Portfolios")
            press("Cancel")()

        self.play([
            (enabled("Make Batch Import"), press("Make Batch Import")),
            (showing("Missing Portfolios"), measure),
            (logged("Stopped. Nothing was written."), lambda: None),
        ])

        self.assertLessEqual(size["width"], 900)
        self.assertLessEqual(size["height"], 700)
        self.assertEqual(outputs(self.batch), [])


if __name__ == "__main__":
    unittest.main()
