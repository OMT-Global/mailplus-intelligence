#!/usr/bin/env python3
"""Execute every fixture-smoke command block in the operator documentation."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


OPERATOR_DOCS = (
    Path("docs/quickstart.md"),
    Path("docs/ops-runbooks.md"),
)
ALLOWED_CLASSIFICATIONS = frozenset(
    {"fixture-smoke", "setup-prerequisite", "live-manual"}
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:[a-z0-9_-]*(?:token|password|secret|api[_-]?key)[a-z0-9_-]*"
    r"|mailplus_(?:host|user|mailbox))[\"']?)(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)
_AUTHORIZATION_VALUE = re.compile(
    r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)[^\s,}]+"
)
_SENSITIVE_FULL_LINE = re.compile(
    r"(?i)(?:"
    r"\b(?:password|passcode|secret|token|api[ _-]?key|credential)s?\s+"
    r"(?:is|are|was|were|has been|have been|supplied|provided)\b"
    r"|\b(?:with|using|supplied|provided)\s+(?:a\s+|the\s+)?"
    r"(?:password|passcode|secret|token|api[ _-]?key|credential)s?\b"
    r"|\b(?:set[ _-]?)?cookies?\s*(?::|=|\b(?:is|are|was|were)\b)"
    r"|https?://[^\s/:]+:[^@\s/]+@"
    r"|https?://[^\s?#]+[^\s#]*[?&](?:access[_-]?token|token|password|passcode|"
    r"secret|api[_-]?key|signature|credential)="
    r")"
)
_FENCE_OPENING = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_CONTAINER_FENCE_OPENING = re.compile(
    r"^(?: {4,}| {0,3}(?:> ?)+| {0,3}(?:[-+*]|\d+[.)])\s+)"
    r"(`{3,}|~{3,})(.*)$"
)
_SHELL_INFO = re.compile(r"(?i)(?:^|[.{\s])(bash|sh|shell|zsh)(?:$|[}\s.])")
_SHELL_ATTRIBUTE_CLASS = re.compile(
    r"(?i)\.(?:bash|sh|shell|zsh)(?![a-z0-9_-])"
)
_LIST_ITEM = re.compile(r"^( {0,3})([-+*]|\d+[.)])([ \t]+)")
_MAX_FAILURE_OUTPUT_CHARS = 4_000
_SMOKE_TIMEOUT_SECONDS = 120


class DocsContractError(RuntimeError):
    """Raised when operator documentation cannot be executed safely."""


@dataclass(frozen=True)
class CommandBlock:
    """One classified bash block from an operator document."""

    source: Path
    index: int
    classification: str
    body: str

    @property
    def identifier(self) -> str:
        return f"{self.source}:{self.index}"


def _is_list_continuation(lines: list[str], line_index: int) -> bool:
    """Return whether an indented fence belongs to a preceding list item."""

    opening = lines[line_index]
    indentation = len(opening) - len(opening.lstrip(" "))
    if indentation == 0 or indentation > 3:
        return False

    for previous_index in range(line_index - 1, -1, -1):
        previous = lines[previous_index]
        if not previous.strip():
            continue
        item_match = _LIST_ITEM.match(previous)
        if item_match is not None:
            # Fail closed for every 1-3 space fence below a less-indented list
            # marker. CommonMark's precise content column depends on marker
            # width, but accepting a shell fence based on that distinction
            # would let visually nested commands evade the smoke contract.
            return indentation > len(item_match.group(1))
        previous_indentation = len(previous) - len(previous.lstrip(" "))
        if previous_indentation < indentation:
            return False
    return False


def parse_command_blocks(source: Path, text: str) -> list[CommandBlock]:
    """Parse every fence and fail closed on malformed shell command blocks."""

    blocks: list[CommandBlock] = []
    lines = text.splitlines()
    line_index = 0
    shell_index = 0
    while line_index < len(lines):
        opening = lines[line_index]
        opening_match = _FENCE_OPENING.fullmatch(opening)
        if opening_match is None:
            container_match = _CONTAINER_FENCE_OPENING.fullmatch(opening)
            if container_match and _SHELL_INFO.search(container_match.group(2)):
                raise DocsContractError(
                    f"{source} has a shell fence in an unsupported CommonMark "
                    f"container at line {line_index + 1}. Move it to the document "
                    "root and label it `bash fixture-smoke`, `bash setup-prerequisite`, "
                    "or `bash live-manual`."
                )
            line_index += 1
            continue

        marker = opening_match.group(1)
        info = opening_match.group(2).strip()
        if _SHELL_INFO.search(info) and _is_list_continuation(lines, line_index):
            raise DocsContractError(
                f"{source} has a shell fence in an unsupported CommonMark "
                f"list container at line {line_index + 1}. Move it to the document "
                "root and label it `bash fixture-smoke`, `bash setup-prerequisite`, "
                "or `bash live-manual`."
            )
        if marker.startswith("`") and "`" in info:
            raise DocsContractError(
                f"{source} has an invalid backtick fence at line {line_index + 1}"
            )
        closing = re.compile(
            rf"^ {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$"
        )
        closing_index = line_index + 1
        while closing_index < len(lines) and closing.fullmatch(lines[closing_index]) is None:
            closing_index += 1
        if closing_index >= len(lines):
            raise DocsContractError(
                f"{source} has an unterminated code fence at line {line_index + 1}"
            )

        tokens = info.split()
        language = tokens[0].lower() if tokens else ""
        if info.startswith("{") and _SHELL_ATTRIBUTE_CLASS.search(info):
            raise DocsContractError(
                f"{source} shell block at line {line_index + 1} uses unsupported "
                "attribute-form language syntax. Use `bash` with an explicit "
                "classification."
            )
        if language in {"sh", "shell", "zsh"}:
            raise DocsContractError(
                f"{source} shell block at line {line_index + 1} must use `bash` "
                "with an explicit classification"
            )
        if language != "bash":
            line_index = closing_index + 1
            continue

        shell_index += 1
        if len(tokens) != 2:
            raise DocsContractError(
                f"{source} bash block {shell_index} must have exactly one classification. "
                "Label fixture commands `bash fixture-smoke` so CI executes them."
            )
        classification = tokens[1]
        if classification not in ALLOWED_CLASSIFICATIONS:
            allowed = ", ".join(sorted(ALLOWED_CLASSIFICATIONS))
            raise DocsContractError(
                f"{source} bash block {shell_index} must be classified as one of: {allowed}. "
                "Label fixture commands `bash fixture-smoke` so CI executes them."
            )
        body = "\n".join(lines[line_index + 1:closing_index]).strip()
        if not body:
            raise DocsContractError(f"{source} bash block {shell_index} must not be empty")
        blocks.append(
            CommandBlock(
                source=source,
                index=shell_index,
                classification=classification,
                body=body,
            )
        )
        line_index = closing_index + 1
    return blocks


def load_command_blocks(repo_root: Path) -> list[CommandBlock]:
    """Load classified commands from all operator-contract documents."""

    blocks: list[CommandBlock] = []
    for relative_path in OPERATOR_DOCS:
        path = repo_root / relative_path
        blocks.extend(
            parse_command_blocks(
                relative_path,
                path.read_text(encoding="utf-8"),
            )
        )
    fixture_blocks = [block for block in blocks if block.classification == "fixture-smoke"]
    if not fixture_blocks:
        raise DocsContractError(
            "operator docs contain no fixture-smoke blocks. "
            "Mark executable fixture commands with `bash fixture-smoke`."
        )
    return blocks


def _redact(output: str) -> str:
    """Redact credential-shaped assignments from actionable failure output."""

    redacted_lines: list[str] = []
    for line in output.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        content = line[:-1] if ending else line
        if _SENSITIVE_FULL_LINE.search(content):
            redacted_lines.append(f"<redacted sensitive line>{ending}")
            continue
        redacted = _SENSITIVE_ASSIGNMENT.sub(r"\1\2<redacted>", content)
        redacted_lines.append(
            _AUTHORIZATION_VALUE.sub(r"\1<redacted>", redacted) + ending
        )
    return "".join(redacted_lines)


def _bounded_failure_output(output: str) -> str:
    redacted = _redact(output)
    if len(redacted) <= _MAX_FAILURE_OUTPUT_CHARS:
        return redacted
    return "<earlier output omitted>\n" + redacted[-_MAX_FAILURE_OUTPUT_CHARS:]


def _write_wrapper(path: Path, command: list[str]) -> None:
    rendered = " ".join(shlex.quote(part) for part in command)
    path.write_text(f"#!/bin/sh\nexec {rendered} \"$@\"\n", encoding="utf-8")
    path.chmod(0o755)


def _smoke_environment(repo_root: Path, workspace: Path) -> dict[str, str]:
    bin_dir = workspace / "bin"
    home_dir = workspace / "home"
    temp_dir = workspace / "tmp"
    bin_dir.mkdir()
    home_dir.mkdir()
    temp_dir.mkdir()
    _write_wrapper(bin_dir / "python", [sys.executable])
    _write_wrapper(
        bin_dir / "mpi",
        [sys.executable, "-m", "mailplus_intelligence.cli"],
    )

    for name in ("fixtures", "scripts", "project.bootstrap.yaml"):
        (workspace / name).symlink_to(repo_root / name)

    return {
        "HOME": str(home_dir),
        "LANG": "C.UTF-8",
        "PATH": f"{bin_dir}{os.pathsep}{os.defpath}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(repo_root / "src"),
        "TMPDIR": str(temp_dir),
    }


def run_fixture_smoke(repo_root: Path) -> int:
    """Run each fixture block verbatim in one shared isolated workspace."""

    blocks = load_command_blocks(repo_root)
    fixture_blocks = [block for block in blocks if block.classification == "fixture-smoke"]

    with tempfile.TemporaryDirectory(prefix="mailplus-docs-smoke-") as temporary:
        workspace = Path(temporary)
        environment = _smoke_environment(repo_root, workspace)
        deadline = time.monotonic() + _SMOKE_TIMEOUT_SECONDS
        for block in fixture_blocks:
            marker = f"docs-smoke: {block.identifier}"
            print(marker)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(
                    "Documentation smoke exceeded its 120-second total timeout. "
                    f"Next step: rerun and inspect {block.identifier}.",
                    file=sys.stderr,
                )
                return 124
            try:
                completed = subprocess.run(
                    ["/bin/bash", "-c", f"set -euo pipefail\n{block.body}"],
                    cwd=workspace,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=remaining,
                )
            except subprocess.TimeoutExpired as exc:
                if exc.stdout:
                    print(_bounded_failure_output(str(exc.stdout)).rstrip())
                if exc.stderr:
                    print(_bounded_failure_output(str(exc.stderr)).rstrip(), file=sys.stderr)
                print(
                    f"Documentation smoke timed out in {block.identifier}. Next step: run "
                    "`PYTHONPATH=src python3.12 scripts/ci/docs_smoke.py` and inspect "
                    "that block.",
                    file=sys.stderr,
                )
                return 124
            if completed.returncode != 0:
                if completed.stdout:
                    print(_bounded_failure_output(completed.stdout).rstrip())
                if completed.stderr:
                    print(_bounded_failure_output(completed.stderr).rstrip(), file=sys.stderr)
                print(
                    f"Documentation smoke failed in {block.identifier}. Next step: run "
                    "`PYTHONPATH=src python3.12 scripts/ci/docs_smoke.py` and fix that block.",
                    file=sys.stderr,
                )
                return completed.returncode

    print(f"Documentation smoke passed: {len(fixture_blocks)} fixture command blocks.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate command-block classifications without executing commands.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        blocks = load_command_blocks(repo_root)
    except (DocsContractError, OSError) as exc:
        print(f"Documentation contract failed: {exc}", file=sys.stderr)
        return 1
    if args.check_only:
        fixture_count = sum(block.classification == "fixture-smoke" for block in blocks)
        print(f"Documentation contract classified {fixture_count} fixture command blocks.")
        return 0
    try:
        return run_fixture_smoke(repo_root)
    except (DocsContractError, OSError) as exc:
        print(
            f"Documentation smoke could not start: {_redact(str(exc))}. "
            "Next step: verify the repository fixtures, scripts, and temporary "
            "directory are readable, then rerun the smoke command.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
