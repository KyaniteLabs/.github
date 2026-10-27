"""Layer 6 structure signals: measure the code shape a refactor should move.

`measure(root)` reads the tracked source files (git ls-files, falling back to a
walk) and returns:

  * files and significant lines (non-blank, not lone punctuation);
  * duplicated_lines_pct: the share of significant lines inside a run of
    WINDOW consecutive significant lines that appears in two or more places
    (a stdlib stand-in for jscpd, so it needs no install or network);
  * large_files: how many files exceed LARGE_FILE_LINES significant lines,
    with the largest few listed;
  * python_complex_functions: how many Python functions exceed
    COMPLEXITY_LIMIT cyclomatic complexity, with the worst few listed.
    Complexity is Python-only; other languages report null rather than a guess.
    Each def is its own unit: nested defs and lambdas do not add to the
    enclosing function (lambdas are not scored), while a nested class body
    does. A file Python cannot parse is still counted for lines.

ci_evidence.py stores the result under `structure` and compares it between a
pull request and main. Like all evidence, it is advisory.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".swift"}
SKIP_PARTS = {"node_modules", "dist", "build", "vendor", "third_party", ".venv", "venv", "__pycache__", "coverage", ".ci-results", ".ci-contract"}
MAX_FILE_BYTES = 1_000_000
WINDOW = 6
LARGE_FILE_LINES = 800
COMPLEXITY_LIMIT = 25
TOP = 5
TRIVIAL = re.compile(r"^[\s{}()\[\];,:]*$")
SPACE = re.compile(r"\s+")


def source_files(root: Path) -> list[Path]:
    try:
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
        names = [n for n in listed.decode("utf-8", "replace").split("\0") if n]
    except (OSError, subprocess.CalledProcessError):
        names = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
    files = []
    for name in sorted(names):
        rel = Path(name)
        if rel.suffix not in SOURCE_SUFFIXES or ".min." in rel.name or SKIP_PARTS.intersection(rel.parts):
            continue
        path = root / rel
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE_BYTES:
            files.append(rel)
    return files


def significant(text: str) -> list[str]:
    return [SPACE.sub(" ", line.strip()) for line in text.splitlines() if not TRIVIAL.match(line)]


def complexity(node: ast.AST) -> int:
    # Nested defs are scored on their own; lambdas are too small to score.
    score, stack = 1, list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(child))
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.Assert)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            score += 1 + len(child.ifs)
        elif isinstance(child, ast.match_case):
            score += 1
    return score


def python_functions(rel: Path, text: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        # Pathological or generated sources can exhaust the parser; skip that file only.
        return []
    return [(complexity(node), f"{rel}:{node.lineno} {node.name}")
            for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def measure(root: Path) -> dict:
    root = root.resolve()
    lines_by_file: dict[Path, list[str]] = {}
    scores: list[tuple[int, str]] = []
    saw_python = False
    for rel in source_files(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        lines_by_file[rel] = significant(text)
        if rel.suffix == ".py":
            saw_python = True
            scores += python_functions(rel, text)
    windows: dict[bytes, int] = {}
    for lines in lines_by_file.values():
        for start in range(len(lines) - WINDOW + 1):
            key = hashlib.blake2b("\n".join(lines[start:start + WINDOW]).encode(), digest_size=12).digest()
            windows[key] = windows.get(key, 0) + 1
    total = duplicated = 0
    for lines in lines_by_file.values():
        marked = [False] * len(lines)
        for start in range(len(lines) - WINDOW + 1):
            key = hashlib.blake2b("\n".join(lines[start:start + WINDOW]).encode(), digest_size=12).digest()
            if windows[key] > 1:
                marked[start:start + WINDOW] = [True] * WINDOW
        total += len(lines)
        duplicated += sum(marked)
    sizes = sorted(((len(v), str(k)) for k, v in lines_by_file.items()), reverse=True)
    large = [s for s in sizes if s[0] > LARGE_FILE_LINES]
    complex_fns = sorted((s for s in scores if s[0] > COMPLEXITY_LIMIT), reverse=True)
    return {
        "files": len(lines_by_file),
        "significant_lines": total,
        "duplicated_lines_pct": round(100 * duplicated / total, 2) if total else 0.0,
        "large_files": len(large),
        "largest": [f"{path} ({n})" for n, path in large[:TOP]],
        "python_complex_functions": len(complex_fns) if saw_python else None,
        "most_complex": [f"{where} (cc {cc})" for cc, where in complex_fns[:TOP]],
    }


if __name__ == "__main__":
    print(json.dumps(measure(Path(sys.argv[1] if len(sys.argv) > 1 else os.curdir)), indent=2))
