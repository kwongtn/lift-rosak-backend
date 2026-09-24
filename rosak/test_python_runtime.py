import re
import sys
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent


class PythonRuntimeTests(SimpleTestCase):
    def test_running_interpreter_is_python_313_or_newer(self):
        self.assertGreaterEqual(
            sys.version_info[:2],
            (3, 13),
            f"expected Python >= 3.13, running {sys.version.split()[0]}",
        )

    def test_version_pins_all_say_313(self):
        dockerfile = (REPO_ROOT / "Dockerfile").read_text()
        base_image = next(
            line for line in dockerfile.splitlines() if line.startswith("FROM ")
        )
        self.assertRegex(base_image, r"\bpython:3\.13\b")

        version_file = REPO_ROOT / ".python-version"
        if version_file.exists():
            self.assertEqual(version_file.read_text().strip(), "3.13")

        pyproject = (REPO_ROOT / "pyproject.toml").read_text()
        requires = re.search(r'^requires-python\s*=\s*"([^"]+)"', pyproject, re.M)
        self.assertIsNotNone(requires)
        self.assertIn("3.13", requires.group(1))
