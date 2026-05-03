#!/usr/bin/env python3
"""
check_agent_parity.py — Verify CLAUDE.md and AGENTS.md parity across KyaniteLabs repos.

Usage:
    python check_agent_parity.py [--repos-dir /tmp/repos] [--json] [--ci]

Exit codes:
    0 — All repos pass parity check
    1 — One or more repos fail parity check
    2 — Configuration error
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


# Sections that must be identical in both CLAUDE.md and AGENTS.md
CANONICAL_SECTIONS = [
    "Organization Principles",
    "Issue-Driven Development",
    "Label System",
    "Pipeline Awareness",
    "CI Standards",
    "Branch Protection",
    "Repository Standards",
    "Agent Coordination",
    "Code Quality Rules",
    "Dependency Discipline",
    "Error Handling",
    "Security Non-Negotiables",
    "Testing",
    "Documentation",
    "Git and PR Hygiene",
    "Performance",
    "Configuration",
    "Local-First Inference",
    "Loading Rules",
    "Inference Sampling Profiles",
]

# Sections that are agent-specific and excluded from parity
EXCLUDED_SECTIONS = [
    "oh-my-claudecode",        # OMC orchestration (Claude-specific)
    "MCP Server Requirements",  # MCP config (Claude-specific)
    "GLM Model Configuration",  # GLM routing (Claude-specific)
    "delegation_rules",         # OMC rules (Claude-specific)
    "model_routing",           # OMC rules (Claude-specific)
    "skills",                  # OMC rules (Claude-specific)
    "hooks_and_context",       # OMC rules (Claude-specific)
]


@dataclass
class ParityResult:
    repo: str
    has_claude_md: bool
    has_agents_md: bool
    has_copilot_instructions: bool
    has_cursorrules: bool
    has_windsurfrules: bool
    parity_score: float  # 0.0 to 1.0
    missing_sections_claude: list[str]
    missing_sections_agents: list[str]
    content_differences: list[str]
    status: str  # "pass", "warn", "fail"


def strip_agent_specific(content: str) -> str:
    """Remove agent-specific syntax to enable fair comparison."""
    # Remove HTML comments (OMC markers)
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    # Remove XML tags
    content = re.sub(r'<[^>]+>', '', content)
    # Remove frontmatter
    content = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL)
    # Normalize whitespace
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = content.strip()
    return content


def extract_sections(content: str) -> dict[str, str]:
    """Extract markdown sections by header."""
    sections = {}
    current_header = None
    current_content = []

    for line in content.split('\n'):
        header_match = re.match(r'^#{1,3}\s+(.+)$', line)
        if header_match:
            if current_header:
                sections[current_header] = '\n'.join(current_content).strip()
            current_header = header_match.group(1).strip()
            current_content = []
        else:
            current_content.append(line)

    if current_header:
        sections[current_header] = '\n'.join(current_content).strip()

    return sections


def check_section_parity(claude_content: str, agents_content: str) -> tuple[float, list[str]]:
    """Check parity between CLAUDE.md and AGENTS.md canonical sections."""
    claude_sections = extract_sections(strip_agent_specific(claude_content))
    agents_sections = extract_sections(strip_agent_specific(agents_content))

    differences = []
    matched = 0
    total = 0

    for section_name in CANONICAL_SECTIONS:
        # Find the section (may have slightly different naming)
        claude_match = None
        agents_match = None

        for key in claude_sections:
            if section_name.lower() in key.lower():
                claude_match = claude_sections[key]
                break

        for key in agents_sections:
            if section_name.lower() in key.lower():
                agents_match = agents_sections[key]
                break

        # Skip if section is in excluded list
        if any(ex.lower() in section_name.lower() for ex in EXCLUDED_SECTIONS):
            continue

        total += 1

        if claude_match and agents_match:
            # Compare content (normalized)
            claude_norm = normalize_for_comparison(claude_match)
            agents_norm = normalize_for_comparison(agents_match)

            if claude_norm == agents_norm:
                matched += 1
            else:
                # Check if content is semantically similar (>80% word overlap)
                similarity = calculate_similarity(claude_norm, agents_norm)
                if similarity >= 0.8:
                    matched += 1
                else:
                    differences.append(
                        f"Section '{section_name}' differs (similarity: {similarity:.0%})"
                    )
        elif claude_match and not agents_match:
            differences.append(f"Section '{section_name}' missing from AGENTS.md")
        elif agents_match and not claude_match:
            differences.append(f"Section '{section_name}' missing from CLAUDE.md")

    score = matched / total if total > 0 else 0.0
    return score, differences


def normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison."""
    # Lowercase
    text = text.lower()
    # Remove markdown formatting
    text = re.sub(r'[`*#|>-]', '', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate word-level similarity between two texts."""
    words1 = set(text1.split())
    words2 = set(text2.split())

    if not words1 and not words2:
        return 1.0
    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


def check_repo(repo_path: Path) -> ParityResult:
    """Check a single repo for parity."""
    repo_name = repo_path.name

    claude_md = repo_path / "CLAUDE.md"
    agents_md = repo_path / "AGENTS.md"
    copilot = repo_path / ".github" / "copilot-instructions.md"
    cursorrules = repo_path / ".cursorrules"
    windsurfrules = repo_path / ".windsurfrules"

    has_claude = claude_md.exists()
    has_agents = agents_md.exists()

    parity_score = 0.0
    missing_claude = []
    missing_agents = []
    differences = []

    if has_claude and has_agents:
        claude_content = claude_md.read_text()
        agents_content = agents_md.read_text()

        parity_score, differences = check_section_parity(claude_content, agents_content)

        # Check for missing canonical sections
        claude_sections = extract_sections(strip_agent_specific(claude_content))
        agents_sections = extract_sections(strip_agent_specific(agents_content))

        for section in CANONICAL_SECTIONS:
            found_in_claude = any(section.lower() in k.lower() for k in claude_sections)
            found_in_agents = any(section.lower() in k.lower() for k in agents_sections)

            if not found_in_claude:
                missing_claude.append(section)
            if not found_in_agents:
                missing_agents.append(section)

    elif has_claude and not has_agents:
        parity_score = 0.0
        missing_agents = ["ALL — AGENTS.md does not exist"]
        differences = ["AGENTS.md file is missing"]
    elif has_agents and not has_claude:
        parity_score = 0.0
        missing_claude = ["ALL — CLAUDE.md does not exist"]
        differences = ["CLAUDE.md file is missing"]
    else:
        parity_score = 0.0
        differences = ["Neither CLAUDE.md nor AGENTS.md exists"]

    # Determine status
    if parity_score >= 0.9 and has_claude and has_agents:
        status = "pass"
    elif parity_score >= 0.7:
        status = "warn"
    else:
        status = "fail"

    return ParityResult(
        repo=repo_name,
        has_claude_md=has_claude,
        has_agents_md=has_agents,
        has_copilot_instructions=copilot.exists(),
        has_cursorrules=cursorrules.exists(),
        has_windsurfrules=windsurfrules.exists(),
        parity_score=parity_score,
        missing_sections_claude=missing_claude,
        missing_sections_agents=missing_agents,
        content_differences=differences,
        status=status,
    )


def main():
    parser = argparse.ArgumentParser(description="Check CLAUDE.md/AGENTS.md parity")
    parser.add_argument("--repos-dir", help="Directory containing cloned repos")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--ci", action="store_true", help="CI mode (exit 1 on any failure)")
    args = parser.parse_args()

    # Discover repos
    repos = []
    if args.repos_dir:
        repos_dir = Path(args.repos_dir)
        repos = sorted(repos_dir.iterdir())
    else:
        # Check current directory
        repos = [Path.cwd()]

    results = []
    for repo in repos:
        if repo.is_dir() and not repo.name.startswith('.'):
            results.append(check_repo(repo))

    # Output
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print("\n# Cross-Agent Parity Report\n")
        print(f"{'Repo':<25} {'CLAUDE.md':>10} {'AGENTS.md':>10} {'Parity':>8} {'Status':>8}")
        print("-" * 65)

        for r in results:
            claude_mark = "YES" if r.has_claude_md else "NO"
            agents_mark = "YES" if r.has_agents_md else "NO"
            print(
                f"{r.repo:<25} {claude_mark:>10} {agents_mark:>10} "
                f"{r.parity_score:>7.0%} {r.status:>8}"
            )

        # Summary
        total = len(results)
        passing = sum(1 for r in results if r.status == "pass")
        failing = sum(1 for r in results if r.status == "fail")
        warnings = sum(1 for r in results if r.status == "warn")

        print(f"\nTotal: {total} | Pass: {passing} | Warn: {warnings} | Fail: {failing}")

        # Details for failures/warnings
        for r in results:
            if r.status != "pass":
                print(f"\n## {r.repo} (status: {r.status})")
                if r.content_differences:
                    for diff in r.content_differences:
                        print(f"  - {diff}")

    # Exit code
    if args.ci:
        failures = sum(1 for r in results if r.status == "fail")
        if failures > 0:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
