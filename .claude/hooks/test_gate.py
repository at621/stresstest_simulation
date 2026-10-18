"""Stop hook: the test gate. When Claude Code stops after changing code, run the tests, the
import rules and the linter; if any fails, block the stop (exit 2) so the failure is fixed.

Runs only when files under src/, foundation/ or tests/ (or pyproject.toml) changed, and only
once per stop: when the hook itself caused the continuation (stop_hook_active), it lets the
stop through. Standard library only, so it works under any interpreter.
"""

import json
import os
import subprocess
import sys

WATCHED = ("src", "foundation", "tests", "pyproject.toml")
CHECKS = (
    ("tests", ["uv", "run", "pytest", "-q", "-x", "-p", "no:cacheprovider"]),
    ("import rules", ["uv", "run", "lint-imports", "--cache-dir", "tests/.import_linter_cache"]),
    ("lint", ["uv", "run", "ruff", "check"]),
)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    if event.get("stop_hook_active"):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        changed = subprocess.run(["git", "status", "--porcelain", "--", *WATCHED], cwd=root,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 0
    if not changed:
        return 0
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    failures = []
    for name, command in CHECKS:
        try:
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, env=env,
                                    encoding="utf-8", errors="replace", timeout=900, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{name}: could not run ({exc})")
            continue
        if result.returncode != 0:
            tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-25:])
            failures.append(f"{name} failed:\n{tail}")
    if failures:
        print("Test gate (.claude/hooks/test_gate.py) failed; fix before stopping:\n\n"
              + "\n\n".join(failures), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
