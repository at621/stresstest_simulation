"""PreToolUse guard: keep Claude Code out of protected paths.

Protected: archive/ (never accessed by Claude Code) and inputs/bank/ (real borrower data, OPS-05).
Works alongside the deny rules in .claude/settings.json and covers what they miss: shell commands
(rg, PowerShell, git show), MCP tools such as IDE diagnostics, and git grep.

Checks only path-like fields, so a file whose *content* mentions a protected path can still be
written. Exit code 2 blocks the tool call; the message on stderr is shown to Claude.
"""

import json
import re
import sys

SEP = r"[\\/]"
START = r"(?:^|[\\/\s\"'`=:;,(|&<>])"
END = r"(?:[\\/\s\"'`;,)|&<>*]|$)"
PROTECTED = {
    "archive/": re.compile(START + r"archive" + END, re.IGNORECASE),
    "inputs/bank/": re.compile(START + r"inputs" + SEP + r"bank" + END, re.IGNORECASE),
}
GIT_GREP = re.compile(r"\bgit\s+(?:-\S+\s+)*grep\b", re.IGNORECASE)

PATH_FIELDS = {
    "Read": ["file_path"],
    "Edit": ["file_path"],
    "Write": ["file_path"],
    "NotebookEdit": ["notebook_path"],
    "Grep": ["path", "glob"],
    "Glob": ["path", "pattern"],
    "Bash": ["command"],
    "PowerShell": ["command"],
}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def block(reason):
    print(f"Blocked by .claude/hooks/guard_paths.py: {reason}", file=sys.stderr)
    sys.exit(2)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError as exc:
        block(f"could not parse hook input ({exc}); failing closed")

    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}

    if tool in PATH_FIELDS:
        values = [str(tool_input.get(field) or "") for field in PATH_FIELDS[tool]]
    elif tool.startswith("mcp__"):
        values = list(strings(tool_input))
    else:
        return

    for value in values:
        for name, pattern in PROTECTED.items():
            if pattern.search(value):
                block(f"{name} is off-limits to Claude Code (see CLAUDE.md). Ask the user instead.")

    if tool in ("Bash", "PowerShell") and GIT_GREP.search(tool_input.get("command") or ""):
        block("git grep can search archive/ without naming it. Use the Grep tool instead.")


if __name__ == "__main__":
    main()
