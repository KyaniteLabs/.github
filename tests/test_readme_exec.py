"""Tagged README blocks must really run, and untagged ones must never run."""

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "readme_exec", Path(__file__).resolve().parents[1] / "scripts/readme_exec.py",
)
EXEC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXEC)


def repo(readme=None, **files):
    root = Path(tempfile.mkdtemp())
    if readme is not None:
        (root / "README.md").write_text(readme)
    for name, content in files.items():
        path = root / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)
    return root


def main(root):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = EXEC.main([str(root)])
    return code, out.getvalue(), err.getvalue()


class ParsingTests(unittest.TestCase):
    def test_only_tagged_shell_blocks_are_selected(self):
        text = "\n".join([
            "```bash readme-test", "echo one", "```",
            "```bash", "rm -rf /", "```",
            "```python readme-test", "print(1)", "```",
            "```sh readme-test", "echo two", "```",
        ])
        self.assertEqual(EXEC.tagged_blocks(text), [(1, "echo one"), (10, "echo two")])

    def test_tag_must_be_a_whole_word_after_the_language(self):
        text = "```bash readme-tests\necho x\n```\n```readme-test\necho y\n```\n"
        self.assertEqual(EXEC.tagged_blocks(text), [])

    def test_a_shorter_or_different_fence_does_not_close_the_block(self):
        text = "````bash readme-test\necho a\n```\n~~~\necho b\n````\n"
        self.assertEqual(EXEC.tagged_blocks(text), [(1, "echo a\n```\n~~~\necho b")])

    def test_unclosed_block_is_ignored(self):
        self.assertEqual(EXEC.tagged_blocks("```bash readme-test\necho a\n"), [])


class RunTests(unittest.TestCase):
    def test_not_applicable_without_readme_or_tags(self):
        self.assertEqual(main(repo())[0], 2)
        self.assertEqual(main(repo("```bash\necho hi\n```\n"))[0], 2)

    def test_passing_block_with_expectations(self):
        code, out, _ = main(repo("```bash readme-test\necho 'version 1.2.3'\n# expect: 1.2.3\n```\n"))
        self.assertEqual(code, 0)
        self.assertIn("README.md:1 block passed (1 expectation(s) met)", out)

    def test_nonzero_exit_fails(self):
        code, _, err = main(repo("```bash readme-test\necho ok\nfalse\necho never\n```\n"))
        self.assertEqual(code, 1)
        self.assertIn("README.md:1 exit 1", err)

    def test_pipefail_catches_a_failing_producer(self):
        self.assertEqual(main(repo("```bash readme-test\nfalse | cat\n```\n"))[0], 1)

    def test_missing_expectation_fails(self):
        code, _, err = main(repo("```bash readme-test\necho 'version 1.2.4'\n# expect: 1.2.3\n```\n"))
        self.assertEqual(code, 1)
        self.assertIn("expected output not found: '1.2.3'", err)

    def test_expectations_match_stdout_not_stderr(self):
        self.assertEqual(main(repo("```bash readme-test\necho 1.2.3 >&2\n# expect: 1.2.3\n```\n"))[0], 1)

    def test_one_failure_among_several_fails_the_run(self):
        code, out, _ = main(repo("```bash readme-test\ntrue\n```\n```bash readme-test\nfalse\n```\n"))
        self.assertEqual(code, 1)
        self.assertIn("1/2 block(s) passed", out)

    def test_checkout_tools_come_first_on_path(self):
        root = repo("```bash readme-test\nlocaltool\n# expect: from-venv\n```\n",
                    **{".venv__bin__localtool": "#!/bin/sh\necho from-venv\n"})
        self.assertEqual(main(root)[0], 0)

    def test_blocks_run_from_the_repository_root(self):
        root = repo("```bash readme-test\ncat marker.txt\n# expect: here\n```\n", **{"marker.txt": "here\n"})
        self.assertEqual(main(root)[0], 0)

    def test_timeout_fails(self):
        root = repo("```bash readme-test\nsleep 5\n```\n")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = EXEC.main([str(root), "--timeout", "1"])
        self.assertEqual(code, 1)
        self.assertIn("timed out after 1s", err.getvalue())


if __name__ == "__main__":
    unittest.main()
