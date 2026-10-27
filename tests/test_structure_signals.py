"""Structure signals count real duplication, size and Python complexity, and nothing else."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "structure_signals", Path(__file__).resolve().parents[1] / "scripts/structure_signals.py",
)
SIGNALS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIGNALS)

BLOCK = "\n".join(f"value_{i} = compute({i}, total)" for i in range(8)) + "\n"
BRANCHY = "def branchy(x):\n" + "".join(f"    if x == {i} and x > -1:\n        return {i}\n" for i in range(13)) + "    return None\n"


def checkout(git=False, **files):
    root = Path(tempfile.mkdtemp())
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if git:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


class MeasureTests(unittest.TestCase):
    def test_unique_code_has_no_duplication(self):
        result = SIGNALS.measure(checkout(**{"a.py": BLOCK}))
        self.assertEqual(result["duplicated_lines_pct"], 0.0)
        self.assertEqual(result["significant_lines"], 8)

    def test_a_block_copied_into_two_files_is_duplicated(self):
        result = SIGNALS.measure(checkout(**{"a.py": BLOCK, "b.py": BLOCK + "other = 1\n"}))
        self.assertEqual(result["duplicated_lines_pct"], round(100 * 16 / 17, 2))

    def test_blank_lines_whitespace_and_lone_braces_do_not_count(self):
        spaced = "\n\n".join("  " + line + "   " for line in BLOCK.splitlines()) + "\n}\n);\n"
        result = SIGNALS.measure(checkout(**{"a.ts": BLOCK, "b.ts": spaced}))
        self.assertEqual(result["significant_lines"], 16)
        self.assertEqual(result["duplicated_lines_pct"], 100.0)

    def test_large_files_are_counted_and_listed(self):
        big = "".join(f"line_{i} = {i}\n" for i in range(SIGNALS.LARGE_FILE_LINES + 1))
        result = SIGNALS.measure(checkout(**{"big.py": big, "small.py": BLOCK}))
        self.assertEqual(result["large_files"], 1)
        self.assertEqual(result["largest"], [f"big.py ({SIGNALS.LARGE_FILE_LINES + 1})"])

    def test_python_complexity_counts_branches_and_boolean_operators(self):
        result = SIGNALS.measure(checkout(**{"m.py": BRANCHY}))
        self.assertEqual(result["python_complex_functions"], 1)
        self.assertEqual(result["most_complex"], ["m.py:1 branchy (cc 27)"])

    def test_nested_functions_are_scored_separately(self):
        nested = "def outer():\n    " + BRANCHY.replace("\n", "\n    ") + "\n    return branchy\n"
        result = SIGNALS.measure(checkout(**{"m.py": nested}))
        self.assertEqual(result["most_complex"], ["m.py:2 branchy (cc 27)"])

    def test_complexity_is_null_without_python(self):
        self.assertIsNone(SIGNALS.measure(checkout(**{"a.ts": BLOCK}))["python_complex_functions"])

    def test_generated_vendored_and_untracked_files_are_ignored(self):
        root = checkout(git=True, **{
            "src/a.py": BLOCK, "node_modules/x/a.js": BLOCK, "dist/a.js": BLOCK, "a.min.js": BLOCK, "notes.md": BLOCK,
        })
        (root / "untracked.py").write_text(BLOCK)
        result = SIGNALS.measure(root)
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["duplicated_lines_pct"], 0.0)

    def test_unparseable_python_still_measures_lines(self):
        result = SIGNALS.measure(checkout(**{"bad.py": "def broken(:\n" + BLOCK}))
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["python_complex_functions"], 0)


if __name__ == "__main__":
    unittest.main()
