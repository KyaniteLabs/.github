"""Layer 3 executable docs: run the README's tagged shell blocks so they cannot rot.

A block opts in through its info string, which renders as an ordinary shell
block everywhere:

    ```bash readme-test
    mytool --version
    # expect: 1.2.3
    ```

Each tagged block runs with `bash -euo pipefail` from the repository root,
with the checkout's own tools first on PATH (`node_modules/.bin`, `.venv/bin`)
as a developer's activated shell would have them. A block passes when it exits
0 and every `# expect: <text>` line inside it appears in its standard output.
The expectation lines are shell comments, so a person copying the block runs
exactly what CI ran.

Exit codes: 0 every tagged block passed, 1 a block failed (or the README is
unreadable), 2 not applicable (no README or no tagged block). Evidence lines
name every block, so a pass is visible in CI logs.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

TAG = "readme-test"
SHELLS = {"bash", "sh", "shell", "console"}
EXPECT = re.compile(r"^\s*#\s*expect:\s?(.*)$")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")


def tagged_blocks(text: str) -> list[tuple[int, str]]:
    """(first line number, body) for each fenced shell block tagged readme-test."""
    blocks, fence, info, start, body = [], None, "", 0, []
    for number, line in enumerate(text.splitlines(), 1):
        marker = FENCE.match(line)
        if fence is None:
            if marker:
                fence, info, start, body = marker.group(1), marker.group(2).strip(), number, []
            continue
        if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
            words = info.split()
            if words and words[0].lower() in SHELLS and TAG in words[1:]:
                blocks.append((start, "\n".join(body)))
            fence = None
            continue
        body.append(line)
    return blocks


def environment(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    local = [str(path) for path in (root / "node_modules/.bin", root / ".venv/bin") if path.is_dir()]
    env["PATH"] = os.pathsep.join(local + [env.get("PATH", "")])
    return env


def run_block(root: Path, body: str, timeout: int) -> tuple[bool, str]:
    expectations = [match.group(1).strip() for line in body.splitlines() if (match := EXPECT.match(line))]
    try:
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", body], cwd=root, env=environment(root),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        return False, f"exit {result.returncode}: " + " | ".join(detail)
    missing = [text for text in expectations if text not in result.stdout]
    if missing:
        return False, "expected output not found: " + "; ".join(repr(text) for text in missing)
    return True, f"{len(expectations)} expectation(s) met"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=".", help="repository root (default: .)")
    parser.add_argument("--timeout", type=int, default=120, help="seconds per block (default 120)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    readme = root / "README.md"
    if not readme.is_file():
        print("readme-exec: not applicable (no README.md)")
        return 2
    try:
        text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"readme-exec failure: README.md unreadable ({exc.__class__.__name__})", file=sys.stderr)
        return 1
    blocks = tagged_blocks(text)
    if not blocks:
        print(f"readme-exec: not applicable (no ```bash {TAG} blocks in README.md)")
        return 2
    failures = 0
    for line, body in blocks:
        ok, detail = run_block(root, body, args.timeout)
        if ok:
            print(f"gate evidence: README.md:{line} block passed ({detail})")
        else:
            failures += 1
            print(f"readme-exec failure: README.md:{line} {detail}", file=sys.stderr)
    print(f"readme-exec: {'FAIL' if failures else 'OK'} ({len(blocks) - failures}/{len(blocks)} block(s) passed)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
