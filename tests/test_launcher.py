"""The double-click launcher: the .app bundle, the script inside it, and build.sh.

The script is driven with a temp folder in place of the bundle's Resources, a
temp HOME for the support dir and a fake Python.framework, with stand-ins for
osascript, curl, pkgutil and open on PATH, so no dialog, download or installer
runs here.
"""

import os
import plistlib
import re
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "One45 Schedule Wrangler.app"
LAUNCHER = APP / "Contents" / "MacOS" / "One45 Schedule Wrangler"
BUILD = ROOT / "build.sh"
RUNTIME_FILES = ("wrangler.py", "wrangler_gui.py", "setup-venv.sh", "requirements.txt")
SUPPORT = Path("Library") / "Application Support" / "One45 Schedule Wrangler"
FALLBACK_VERSION = re.search(r'^PYTHON_FALLBACK_VERSION="([0-9.]+)"', LAUNCHER.read_text(), re.M).group(1)
SIGNER = re.search(r'^PYTHON_SIGNER="([^"]+)"', LAUNCHER.read_text(), re.M).group(1)
SIGNED_STATUS = re.search(r'^PYTHON_SIGNED_STATUS="([^"]+)"', LAUNCHER.read_text(), re.M).group(1)
INVALID_STATUS = "Status: package is invalid (checksum did not verify)"
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def executable(path):
    return bool(path.stat().st_mode & stat.S_IXUSR)


def world_readable(path):
    return bool(path.stat().st_mode & stat.S_IROTH)


def build(dist):
    return subprocess.run(["/bin/bash", str(BUILD)], env={**os.environ, "DIST": str(dist)},
                          cwd=ROOT, capture_output=True, text=True)


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
        self.assertEqual(self.info()["CFBundleShortVersionString"], VERSION)
        self.assertEqual(self.info()["CFBundleVersion"], VERSION)

    def test_launcher_and_build_are_executable_in_the_working_tree_and_in_git(self):
        # GitHub's source zip is `git archive`, which uses the mode git has.
        for script in (LAUNCHER, BUILD):
            self.assertTrue(executable(script), script)
            mode = subprocess.run(
                ["git", "ls-files", "-s", "--", str(script.relative_to(ROOT))],
                cwd=ROOT, capture_output=True, text=True, check=True,
            ).stdout.split(" ")[0]
            self.assertEqual(mode, "100755", f"git add {script.name} with its executable bit")

    def test_old_command_launcher_is_gone(self):
        self.assertFalse((ROOT / "One45 Schedule Wrangler.command").exists())


class BuildTests(unittest.TestCase):
    """build.sh assembles the shareable app: the committed bundle plus the runtime files."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dist = Path(cls._tmp.name) / "dist"
        result = build(cls.dist)
        assert result.returncode == 0, result.stderr
        cls.app = cls.dist / APP.name
        cls.zip_path = cls.dist / f"One45-Schedule-Wrangler-{VERSION}.zip"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_built_app_carries_everything_the_launcher_needs(self):
        resources = self.app / "Contents" / "Resources"
        for name in RUNTIME_FILES:
            self.assertEqual((resources / name).read_bytes(), (ROOT / name).read_bytes(), name)
            # Installed by one account, opened by another: pip must be able to read these.
            self.assertTrue(world_readable(resources / name), name)
        self.assertTrue(executable(resources / "setup-venv.sh"))
        self.assertTrue(executable(self.app / "Contents" / "MacOS" / LAUNCHER.name))
        self.assertTrue((resources / "AppIcon.icns").is_file())

    def test_the_zip_unpacks_to_the_app_itself(self):
        self.assertTrue(self.zip_path.is_file(), list(self.dist.iterdir()))
        with zipfile.ZipFile(self.zip_path) as z:
            names = z.namelist()
        self.assertTrue(all(n.startswith(APP.name + "/") for n in names), names[:5])
        self.assertIn(f"{APP.name}/Contents/Resources/wrangler_gui.py", names)
        # No ._ sidecars from this machine's extended attributes.
        self.assertEqual([n for n in names if Path(n).name.startswith("._")], [])

    def test_building_twice_replaces_the_previous_build(self):
        stale = self.app / "Contents" / "Resources" / "stale.txt"
        stale.write_text("left over")
        try:
            result = build(self.dist)
        finally:
            stale.unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stale.exists())


class LauncherRunTests(unittest.TestCase):
    """Runs the launcher script against a fake world and reads back what it did."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.resources = tmp / "Resources"
        self.support = tmp / SUPPORT
        self.venv = self.support / "venv"
        self.lock = self.support / "setup.lock"
        self.frameworks = tmp / "Versions"
        self.bin = tmp / "bin"
        self.log = tmp / "calls.log"
        for d in (self.resources, self.frameworks, self.bin):
            d.mkdir()
        (self.resources / "wrangler_gui.py").write_text("")
        (self.resources / "requirements.txt").write_text("openpyxl\n")
        self.installed = self.support / "installed-requirements.txt"
        # Dialogs answer $DIALOG_ANSWER; OK-only dialogs exit $DIALOG_EXIT (a dismissed dialog).
        self.fake("osascript", 'echo "osascript $*" >> "$CALLS"\n'
                  'if [[ "$*" == *"display dialog"* ]]; then echo "${DIALOG_ANSWER:-OK}"; '
                  '[[ "$*" == *\'buttons {"OK"}\'* ]] && exit "${DIALOG_EXIT:-0}"; fi; exit 0')
        # curl: a HEAD (-I) succeeds for the installers in $FAKE_PKG_VERSIONS; a GET
        # without -o is python.org's folder listing, built from $FAKE_LISTING (empty:
        # the listing can't be read); a GET with -o downloads $FAKE_PKG.
        self.fake("curl", 'echo "curl $*" >> "$CALLS"; out=""; head=0; url=""\n'
                  'while [[ $# -gt 0 ]]; do case $1 in -o) out=$2; shift;; -*) [[ $1 == *I* ]] && head=1;; *) url=$1;; esac; shift; done\n'
                  'if (( head )); then for v in $FAKE_PKG_VERSIONS; do [[ $url == */$v/python-$v-*.pkg ]] && exit 0; done; exit 22; fi\n'
                  'if [[ -z $out ]]; then [[ -n $FAKE_LISTING ]] || exit 6; for v in $FAKE_LISTING; do echo "<a href=\\"$v/\\">$v/</a>"; done; exit 0; fi\n'
                  'cp "$FAKE_PKG" "$out"')
        # pkgutil: the launcher runs it by path ($WRANGLER_PKGUTIL here), not from PATH.
        self.fake("pkgutil", 'echo "pkgutil $*" >> "$CALLS"; echo "   ${FAKE_STATUS}"; echo "   Certificate Chain:"; echo "    1. ${FAKE_SIGNER}"')
        self.fake("open", 'echo "open $*" >> "$CALLS"')
        self.stub = tmp / "venv-python"
        self.stub_python(exit_code=0)
        self.fake_setup('mkdir -p "$VENV_DIR/bin"; cp "$STUB" "$VENV_DIR/bin/python"; echo "setup PYTHON=$PYTHON VENV_DIR=$VENV_DIR" >> "$CALLS"')
        self.pkg = tmp / "python.pkg"
        self.pkg.write_bytes(b"not really an installer")

    def tearDown(self):
        self._tmp.cleanup()

    def fake(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def fake_setup(self, body):
        path = self.resources / "setup-venv.sh"
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
        # The probe is `sys.version_info >= (3, N)`: fail it when this version is older.
        py.write_text(
            f'#!/bin/bash\necho "python3[{version}] $*" >> "$CALLS"\n'
            f'floor="$(grep -o "(3, [0-9]*)" <<<"$*" | tr -dc "0-9 " | tr " " .)"\n'
            f'[[ -n "$floor" && "$(printf "%s\\n" "$floor" {version} | sort -V | head -1)" != "$floor" ]] && exit 1\n'
            f'[[ "$*" == *tkinter* ]] && exit {0 if tkinter else 1}\nexit 0\n'
        )
        py.chmod(0o755)
        return py

    def run_launcher(self, answer="OK", signed=False, dialog_exit=0, listing="", pkg_versions="",
                     status=None, signer=None):
        env = {
            **os.environ,
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "CALLS": str(self.log),
            "DIALOG_ANSWER": answer,
            "DIALOG_EXIT": str(dialog_exit),
            "FAKE_PKG": str(self.pkg),
            "FAKE_STATUS": status or (SIGNED_STATUS + " for distribution" if signed else INVALID_STATUS),
            "FAKE_SIGNER": signer or (SIGNER if signed else "Developer ID Installer: Somebody Else (ZZZZZZZZZZ)"),
            "FAKE_LISTING": listing,
            "FAKE_PKG_VERSIONS": pkg_versions,
            "STUB": str(self.stub),
            "WRANGLER_RESOURCES": str(self.resources),
            "WRANGLER_FRAMEWORKS": str(self.frameworks),
            "WRANGLER_PKGUTIL": str(self.bin / "pkgutil"),
            "TMPDIR": self._tmp.name,
            "HOME": self._tmp.name,  # the venv goes under ~/Library/Application Support, the logs under ~/Library/Logs
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
        self.assertIn(f"setup PYTHON={self.frameworks}/3.13/bin/python3 VENV_DIR={self.venv}", calls)
        # -B: no __pycache__ inside the bundle.
        self.assertIn(f"venv-python -B {self.resources}/wrangler_gui.py", calls)
        self.assertFalse(any(c.startswith("curl") for c in calls))
        self.assertFalse(self.lock.exists())
        self.assertEqual(self.installed.read_text(), "openpyxl\n")

    def test_skips_a_python_older_than_3_10(self):
        self.install_python("3.9")
        self.install_python("3.10")
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"setup PYTHON={self.frameworks}/3.10/bin/python3 VENV_DIR={self.venv}", calls)

    def test_only_an_old_python_offers_the_download(self):
        self.install_python("3.9")
        result, calls = self.run_launcher(answer="Download", signed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("curl -fsSL -o ") for c in calls), calls)
        self.assertFalse(any(c.startswith("setup") for c in calls))

    def test_skips_a_python_without_tkinter(self):
        self.install_python("3.13", tkinter=False)
        self.install_python("3.12")
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"setup PYTHON={self.frameworks}/3.12/bin/python3 VENV_DIR={self.venv}", calls)

    def probes(self, calls):
        return [c for c in calls if c.startswith("curl -fsI ")]

    def download(self, calls):
        return next(c for c in calls if c.startswith("curl -fsSL -o "))

    def test_no_python_offers_the_newest_release_with_an_installer(self):
        # 3.16.0 has only pre-releases, so no final installer yet; 2.7.18 is not Python 3.
        result, calls = self.run_launcher(answer="Download", signed=True,
                                          listing="3.14.10 3.16.0 2.7.18 3.15.1 3.15.2",
                                          pkg_versions="3.15.2 3.15.1 3.14.10")
        self.assertEqual(result.returncode, 0, result.stderr)
        # The question comes before any network call.
        first_dialog = next(i for i, c in enumerate(calls) if "display dialog" in c)
        self.assertFalse(any(c.startswith("curl") for c in calls[:first_dialog]), calls)
        self.assertEqual(len(self.probes(calls)), 2, calls)  # 3.16.0 had none, 3.15.2 did; nothing older was asked
        self.assertIn("https://www.python.org/ftp/python/3.15.2/python-3.15.2-macos11.pkg", self.download(calls))
        self.assertTrue(any("Downloading Python 3.15.2..." in c for c in calls), calls)
        self.assertTrue(any(c.startswith("pkgutil --check-signature ") and c.endswith("/python-3.15.2-macos11.pkg") for c in calls), calls)

    def test_a_listing_without_a_final_installer_falls_back(self):
        result, calls = self.run_launcher(answer="Download", signed=True,
                                          listing=" ".join(f"3.{m}.0" for m in range(10, 30)), pkg_versions="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.probes(calls)), 8, calls)  # newest eight only
        self.assertIn(f"/{FALLBACK_VERSION}/", self.download(calls))

    def test_releases_older_than_the_floor_are_never_offered(self):
        # A 3.9 would install, then be skipped by find_python on every open.
        result, calls = self.run_launcher(answer="Download", signed=True,
                                          listing="3.9.13 3.8.20", pkg_versions="3.9.13 3.8.20")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.probes(calls), [], calls)
        self.assertIn(f"/{FALLBACK_VERSION}/", self.download(calls))
        self.assertTrue(any(c.startswith("open ") and c.endswith(".pkg") for c in calls), calls)
        self.assertTrue(any("open One45 Schedule Wrangler again" in c for c in calls), calls)
        self.assertFalse(any(c.startswith("setup") for c in calls))

    def test_when_the_listing_cannot_be_read_the_fallback_version_is_offered(self):
        result, calls = self.run_launcher(answer="Download", signed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"/{FALLBACK_VERSION}/python-{FALLBACK_VERSION}-macos11.pkg", self.download(calls))
        self.assertTrue(any(f"Downloading Python {FALLBACK_VERSION}..." in c for c in calls), calls)

    def test_dismissing_the_installer_dialog_still_opens_the_installer(self):
        result, calls = self.run_launcher(answer="Download", signed=True, dialog_exit=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("open ") and c.endswith(".pkg") for c in calls), calls)

    def test_cancelling_the_download_does_nothing(self):
        result, calls = self.run_launcher(answer="Cancel")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(c.startswith(("curl", "open", "setup")) for c in calls), calls)

    def assert_not_opened(self, result, calls):
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(c.startswith("curl -fsSL -o ") for c in calls), calls)
        self.assertFalse(any(c.startswith("open ") for c in calls), calls)
        self.assertTrue(any("not signed" in c for c in self.dialogs(calls)), calls)

    def test_a_download_signed_by_someone_else_is_never_opened(self):
        result, calls = self.run_launcher(answer="Download", status=SIGNED_STATUS + " for distribution",
                                          signer="Developer ID Installer: Somebody Else (ZZZZZZZZZZ)")
        self.assert_not_opened(result, calls)

    def test_a_tampered_download_is_never_opened(self):
        # pkgutil reports an invalid package without a certificate chain; a chain
        # alongside a bad status must not pass either.
        result, calls = self.run_launcher(answer="Download", status=INVALID_STATUS, signer=SIGNER)
        self.assert_not_opened(result, calls)

    def test_setup_failure_shows_a_dialog_naming_the_log(self):
        self.install_python("3.13")
        self.fake_setup('echo "boom" >&2; exit 1')
        result, calls = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("setup.log" in c for c in self.dialogs(calls)), calls)
        self.assertFalse(any(c.startswith("venv-python") for c in calls))
        self.assertFalse(self.lock.exists())

    def test_a_second_open_during_setup_waits_instead_of_installing_twice(self):
        self.install_python("3.13")
        lock = self.lock
        lock.mkdir(parents=True)
        (lock / "pid").write_text(str(os.getpid()))  # this test process: alive
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("still setting up" in c for c in self.dialogs(calls)), calls)
        self.assertFalse(any(c.startswith("setup") for c in calls))
        self.assertTrue(lock.is_dir())

    def test_a_lock_left_by_a_dead_process_is_taken_over(self):
        self.install_python("3.13")
        lock = self.lock
        lock.mkdir(parents=True)
        (lock / "pid").write_text("2147483646")
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("setup") for c in calls), calls)
        self.assertFalse(lock.exists())

    def test_a_lock_without_a_pid_is_taken_over(self):
        self.install_python("3.13")
        self.lock.mkdir(parents=True)
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("setup") for c in calls), calls)

    def working_venv(self, requirements="openpyxl\n"):
        venv_bin = self.venv / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_bytes(self.stub.read_bytes())
        (venv_bin / "python").chmod(0o755)
        self.installed.write_text(requirements)

    def test_a_working_venv_is_reused_without_setup(self):
        self.install_python("3.13")
        self.working_venv()
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c.startswith("setup") for c in calls), calls)
        self.assertTrue(any(c.startswith("venv-python") and c.endswith("wrangler_gui.py") for c in calls), calls)

    def test_a_new_version_with_other_requirements_rebuilds_the_venv(self):
        # The venv outlives the app it was built for, unlike a venv next to the app.
        self.install_python("3.13")
        self.working_venv(requirements="openpyxl<3\n")
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("setup") for c in calls), calls)
        self.assertEqual(self.installed.read_text(), "openpyxl\n")

    def test_a_window_that_crashes_shows_a_dialog_naming_the_log(self):
        self.install_python("3.13")
        self.stub_python(exit_code=1)
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("window.log" in c for c in self.dialogs(calls)), calls)

    def test_an_incomplete_bundle_says_so(self):
        # The committed bundle has no runtime files until build.sh copies them in.
        self.install_python("3.13")
        (self.resources / "wrangler_gui.py").unlink()
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("build.sh" in c for c in self.dialogs(calls)), calls)
        self.assertFalse(any(c.startswith(("setup", "venv-python")) for c in calls), calls)

    def test_runs_from_a_read_only_bundle(self):
        # Gatekeeper's App Translocation runs a quarantined app from a read-only
        # copy, so the launcher must write nothing next to its own files.
        self.install_python("3.13")
        self.resources.chmod(0o555)
        try:
            result, calls = self.run_launcher()
        finally:
            self.resources.chmod(0o755)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c.startswith("setup") for c in calls), calls)
        self.assertTrue((self.venv / "bin" / "python").is_file())
        self.assertEqual(sorted(p.name for p in self.resources.iterdir()), ["requirements.txt", "setup-venv.sh", "wrangler_gui.py"])


if __name__ == "__main__":
    unittest.main()
