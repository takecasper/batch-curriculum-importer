"""The double-click launcher: the .app bundle and the script inside it.

The script is driven with a temp folder in place of the repo and a fake
Python.framework, with stand-ins for osascript, curl, shasum and open on
PATH, so no dialog, download or installer runs here.
"""

import os
import plistlib
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "One45 Schedule Wrangler.app"
LAUNCHER = APP / "Contents" / "MacOS" / "One45 Schedule Wrangler"
PINNED_SHA256 = re.search(r'^PYTHON_PKG_SHA256="([0-9a-f]{64})"', LAUNCHER.read_text(), re.M).group(1)


def executable(path):
    return bool(path.stat().st_mode & stat.S_IXUSR)


class BundleTests(unittest.TestCase):
    def info(self):
        return plistlib.loads((APP / "Contents" / "Info.plist").read_bytes())

    def test_info_plist_points_at_files_that_exist(self):
        info = self.info()
        self.assertEqual(info["CFBundlePackageType"], "APPL")
        self.assertEqual(LAUNCHER.name, info["CFBundleExecutable"])
        self.assertTrue(LAUNCHER.is_file(), LAUNCHER)
        icon = APP / "Contents" / "Resources" / (info["CFBundleIconFile"] + ".icns")
        self.assertTrue(icon.is_file(), icon)

    def test_bundle_version_matches_pyproject(self):
        version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        self.assertEqual(self.info()["CFBundleShortVersionString"], version)
        self.assertEqual(self.info()["CFBundleVersion"], version)

    def test_launcher_is_executable_in_the_working_tree_and_in_git(self):
        # GitHub's source zip is `git archive`, which uses the mode git has.
        self.assertTrue(executable(LAUNCHER))
        mode = subprocess.run(
            ["git", "ls-files", "-s", "--", str(LAUNCHER.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split(" ")[0]
        self.assertEqual(mode, "100755", "git add the launcher with its executable bit")

    def test_old_command_launcher_is_gone(self):
        self.assertFalse((ROOT / "One45 Schedule Wrangler.command").exists())


class LauncherRunTests(unittest.TestCase):
    """Runs the launcher script against a fake world and reads back what it did."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.root = tmp / "repo"
        self.frameworks = tmp / "Versions"
        self.bin = tmp / "bin"
        self.log = tmp / "calls.log"
        for d in (self.root, self.frameworks, self.bin):
            d.mkdir()
        (self.root / "wrangler_gui.py").write_text("")
        # Dialogs answer $DIALOG_ANSWER; OK-only dialogs exit $DIALOG_EXIT (a dismissed dialog).
        self.fake("osascript", 'echo "osascript $*" >> "$CALLS"\n'
                  'if [[ "$*" == *"display dialog"* ]]; then echo "${DIALOG_ANSWER:-OK}"; '
                  '[[ "$*" == *\'buttons {"OK"}\'* ]] && exit "${DIALOG_EXIT:-0}"; fi; exit 0')
        self.fake("curl", 'echo "curl $*" >> "$CALLS"; while [[ $# -gt 0 ]]; do [[ $1 == -o ]] && out=$2; shift; done; cp "$FAKE_PKG" "$out"')
        self.fake("shasum", 'echo "${FAKE_SHA:-not-the-hash}  $3"')
        self.fake("open", 'echo "open $*" >> "$CALLS"')
        self.stub = tmp / "venv-python"
        self.stub_python(exit_code=0)
        self.fake_setup('mkdir -p "$(dirname "$0")/.venv/bin"; cp "$STUB" "$(dirname "$0")/.venv/bin/python"; echo "setup PYTHON=$PYTHON" >> "$CALLS"')
        self.pkg = tmp / "python.pkg"
        self.pkg.write_bytes(b"not really an installer")

    def tearDown(self):
        self._tmp.cleanup()

    def fake(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def fake_setup(self, body):
        path = self.root / "setup-venv.sh"
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def stub_python(self, exit_code):
        """The venv's python: logs its arguments; exits `exit_code` when running the window."""
        self.stub.write_text(
            '#!/bin/bash\necho "venv-python $*" >> "$CALLS"\n'
            f'[[ "$*" == *wrangler_gui.py ]] && exit {exit_code}\nexit 0\n'
        )
        self.stub.chmod(0o755)

    def install_python(self, version, tkinter=True):
        """A fake python.org Python: answers the version/tkinter probe, logs when run."""
        bin_dir = self.frameworks / version / "bin"
        bin_dir.mkdir(parents=True)
        py = bin_dir / "python3"
        py.write_text(f'#!/bin/bash\necho "python3[{version}] $*" >> "$CALLS"\n[[ "$*" == *tkinter* ]] && exit {0 if tkinter else 1}\nexit 0\n')
        py.chmod(0o755)
        return py

    def run_launcher(self, answer="OK", sha=None, dialog_exit=0):
        env = {
            **os.environ,
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "CALLS": str(self.log),
            "DIALOG_ANSWER": answer,
            "DIALOG_EXIT": str(dialog_exit),
            "FAKE_PKG": str(self.pkg),
            "FAKE_SHA": sha or "not-the-hash",
            "STUB": str(self.stub),
            "WRANGLER_ROOT": str(self.root),
            "WRANGLER_FRAMEWORKS": str(self.frameworks),
            "TMPDIR": self._tmp.name,
            "HOME": self._tmp.name,  # the logs go under ~/Library/Logs
        }
        result = subprocess.run(["/bin/bash", str(LAUNCHER)], env=env, capture_output=True, text=True)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result, calls

    def dialogs(self, calls):
        return [c for c in calls if c.startswith("osascript") and "display dialog" in c]

    def test_uses_the_newest_python_org_python_with_tkinter(self):
        self.install_python("3.12")
        self.install_python("3.13")
        self.install_python("3.9", tkinter=False)
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"setup PYTHON={self.frameworks}/3.13/bin/python3", calls)
        self.assertTrue(any(c.startswith("venv-python ") and c.endswith("wrangler_gui.py") for c in calls), calls)
        self.assertFalse(any(c.startswith("curl") for c in calls))
        self.assertFalse((self.root / ".venv-setup.lock").exists())

    def test_skips_a_python_without_tkinter(self):
        self.install_python("3.13", tkinter=False)
        self.install_python("3.12")
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"setup PYTHON={self.frameworks}/3.12/bin/python3", calls)

    def test_no_python_offers_the_download_and_opens_the_installer(self):
        result, calls = self.run_launcher(answer="Download", sha=PINNED_SHA256)
        self.assertEqual(result.returncode, 0, result.stderr)
        curl = next(c for c in calls if c.startswith("curl "))
        self.assertIn("https://www.python.org/ftp/python/3.13.17/python-3.13.17-macos11.pkg", curl)
        self.assertTrue(any(c.startswith("open ") and c.endswith(".pkg") for c in calls), calls)
        self.assertTrue(any("open One45 Schedule Wrangler again" in c for c in calls), calls)
        self.assertFalse(any(c.startswith("setup") for c in calls))

    def test_dismissing_the_installer_dialog_still_opens_the_installer(self):
        result, calls = self.run_launcher(answer="Download", sha=PINNED_SHA256, dialog_exit=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("open ") and c.endswith(".pkg") for c in calls), calls)

    def test_cancelling_the_download_does_nothing(self):
        result, calls = self.run_launcher(answer="Cancel")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(c.startswith(("curl", "open", "setup")) for c in calls), calls)

    def test_a_download_with_the_wrong_hash_is_never_opened(self):
        result, calls = self.run_launcher(answer="Download", sha="0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(c.startswith("curl ") for c in calls))
        self.assertFalse(any(c.startswith("open ") for c in calls), calls)
        self.assertTrue(any("did not match" in c for c in self.dialogs(calls)), calls)

    def test_setup_failure_shows_a_dialog_naming_the_log(self):
        self.install_python("3.13")
        self.fake_setup('echo "boom" >&2; exit 1')
        result, calls = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("setup.log" in c for c in self.dialogs(calls)), calls)
        self.assertFalse(any(c.startswith("venv-python") for c in calls))
        self.assertFalse((self.root / ".venv-setup.lock").exists())

    def test_a_second_open_during_setup_waits_instead_of_installing_twice(self):
        self.install_python("3.13")
        lock = self.root / ".venv-setup.lock"
        lock.mkdir()
        (lock / "pid").write_text(str(os.getpid()))  # this test process: alive
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("still setting up" in c for c in self.dialogs(calls)), calls)
        self.assertFalse(any(c.startswith("setup") for c in calls))
        self.assertTrue(lock.is_dir())

    def test_a_lock_left_by_a_dead_process_is_taken_over(self):
        self.install_python("3.13")
        lock = self.root / ".venv-setup.lock"
        lock.mkdir()
        (lock / "pid").write_text("2147483646")
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("setup") for c in calls), calls)
        self.assertFalse(lock.exists())

    def test_a_lock_without_a_pid_is_taken_over(self):
        self.install_python("3.13")
        (self.root / ".venv-setup.lock").mkdir()
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("setup") for c in calls), calls)

    def test_a_working_venv_is_reused_without_setup(self):
        self.install_python("3.13")
        venv_bin = self.root / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_bytes(self.stub.read_bytes())
        (venv_bin / "python").chmod(0o755)
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c.startswith("setup") for c in calls), calls)
        self.assertTrue(any(c.startswith("venv-python") and c.endswith("wrangler_gui.py") for c in calls), calls)

    def test_a_window_that_crashes_shows_a_dialog_naming_the_log(self):
        self.install_python("3.13")
        self.stub_python(exit_code=1)
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("window.log" in c for c in self.dialogs(calls)), calls)

    def test_an_app_moved_out_of_its_folder_says_so(self):
        self.install_python("3.13")
        (self.root / "wrangler_gui.py").unlink()
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("folder" in c for c in self.dialogs(calls)), calls)
        self.assertFalse(any(c.startswith(("setup", "venv-python")) for c in calls), calls)


if __name__ == "__main__":
    unittest.main()
