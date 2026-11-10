"""Keeps the code and docs to GLOSSARY.md's vocabulary.

Only multi-word and hyphenated "Do Not Use" terms are checked, case-sensitively:
single words such as "run", "error" or "class" are ordinary English and Python,
so those are left to review.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKED = {".py", ".md", ".sh", ".toml"}


def is_script(path):
    """The app bundle's launcher has no suffix; a shebang marks it as text to check."""
    with path.open("rb") as f:
        return f.read(2) == b"#!"


# The glossary lists the terms; the changelog may name what was renamed.
SKIPPED_FILES = {"GLOSSARY.md", "CHANGELOG.md", "test_glossary.py"}


def banned_terms():
    terms = set()
    for line in (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells[0].startswith("**"):
            continue
        if len(cells) != 3:
            raise ValueError(f"GLOSSARY.md row is not Term | Definition | Do Not Use: {line}")
        for term in cells[2].strip("*").split(","):
            term = term.strip()
            if " " in term or "-" in term:
                terms.add(term)
    return terms


def project_files():
    """Tracked files plus new ones not yet added; ignored local data is left out."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [ROOT / name for name in listed if (ROOT / name).is_file()]


class GlossaryTests(unittest.TestCase):
    def test_glossary_lists_terms_to_check(self):
        self.assertIn("Master Schedule", banned_terms())

    def test_code_and_docs_avoid_do_not_use_terms(self):
        patterns = {t: re.compile(rf"(?<![\w-]){re.escape(t)}(?![\w-])") for t in banned_terms()}
        found = []
        for path in project_files():
            rel = path.relative_to(ROOT)
            found += [f"{rel} (file name): {t}" for t, p in patterns.items() if p.search(path.name)]
            if (path.suffix in CHECKED or (not path.suffix and is_script(path))) and path.name not in SKIPPED_FILES:
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    found += [f"{rel}:{n}: {t}" for t, p in patterns.items() if p.search(line)]
        self.assertEqual(found, [], "GLOSSARY.md says not to use these:\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
