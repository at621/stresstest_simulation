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

# A protected name counts wherever it stands as a name of its own, whatever is around it: a slash,
# a quote, a brace or comma ("{archive,docs}/**"), "@", "!" or nothing. Only a longer name does not
# count: a longer word ("archived", "make_archive"), a name joined by a hyphen ("Expand-Archive",
# "--archive") or a file name with an extension ("archive.md"). A dot with nothing after it still
# counts, because Windows drops it: "archive./notes.md" is the folder.
START = r"(?<![\w.-])"
END = r"(?![\w-]|\.\w)"
SEP = r"[\\/]+(?:\.[\\/]+)*"  # one or more slashes of either kind, and "/./"
IN_BRACES_BEFORE = r"(?:[^{}\s]*\})?"  # "{inputs,docs}/bank"
IN_BRACES_AFTER = r"(?:\{[^{}]*?" + START + r")?"  # "inputs/{x,bank}"
PROTECTED = {
    "archive/": re.compile(START + r"archive" + END, re.IGNORECASE),
    "inputs/bank/": re.compile(START + r"inputs" + END + IN_BRACES_BEFORE + SEP + IN_BRACES_AFTER
                               + r"bank" + END, re.IGNORECASE),
}
# "git grep" after any of git's own options, with or without a value: "git -C . grep".
GIT_GREP = re.compile(r"\bgit(?:\s+-\S+(?:\s+[^-\s|;&]\S*)?)*\s+grep\b", re.IGNORECASE)

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
