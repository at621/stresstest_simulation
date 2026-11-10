"""The guard hook keeps Claude Code out of the protected folders (docs/architecture.md section 4).

The hook is loaded by its path and tried on text only: no test runs a command against a
protected folder. Only tool inputs are guarded, so this file may hold the names.
"""

import importlib.util
import json
import subprocess
import sys

import pytest

from tests.support import ROOT

HOOK = ROOT / ".claude" / "hooks" / "guard_paths.py"

ARCHIVE = "archive/"
BANK = "inputs/bank/"

# Each text names a protected folder as a word of its own, so a call holding it is blocked.
NAMED = {
    ARCHIVE: [
        "archive", "archive/", "archive/notes.md", "./archive/notes.md", "/archive/**",
        r"C:\projects\stresstest_repo\archive\notes.md", "cat archive/notes.md", "ls ARCHIVE",
        r"Get-Content Archive\notes.md", "rg marker archive", "git show HEAD:archive/notes.md",
        "git log -p -- 'archive/*'", "cat <archive/notes.md", "x=archive; ls $x",
        # Forms the hook let through until 9 November 2026:
        "ls {archive,docs}/", "ls {docs,archive}/", "{archive,docs}/**", "{docs,archive}/**/*.md",
        "@archive/notes.md", "git ls-files ':!archive'", "git ls-files ':(exclude)archive'",
        "rg marker --glob '!archive/**'", "cat archive?", "ls [archive]", "ls archive.", "ls archive~",
        # Windows drops a dot at the end of a name, so this is the folder:
        "cat archive./notes.md", "ls -la archive", "tar --exclude=archive -cf out.tar .",
    ],
    BANK: [
        "inputs/bank", "inputs/bank/", "inputs/bank/loans.parquet", r"inputs\bank\loans.parquet",
        r"C:\projects\stresstest_repo\inputs\bank", "cat inputs/bank/loans.parquet", "ls INPUTS/Bank",
        "git show HEAD:inputs/bank/loans.parquet", "inputs/bank/**",
        # Forms the hook let through until 9 November 2026:
        "inputs//bank/loans.parquet", r"inputs\\bank", "inputs/./bank/loans.parquet",
        "ls inputs/{bank,0123456789abcdef}/", "ls inputs/{0123456789abcdef,bank}/", "inputs/{bank}/**",
        "ls {inputs,docs}/bank/", "{docs,inputs}/bank/**", "@inputs/bank/loans.parquet",
        "git ls-files ':!inputs/bank'", "ls inputs/bank.", "cat inputs/bank?", "cat inputs/bank./loans.parquet",
    ],
}

# A longer name, or a neighbouring folder, names no protected folder: a longer word, a name joined
# by a hyphen (the PowerShell cmdlets, a command's option) or a file name with an extension.
NOT_NAMED = [
    "docs/archived-notes.md", "archives/2026.md", "tests/unit/test_archiver.py", "unarchive.py",
    "python -c \"import shutil; shutil.make_archive('out', 'zip', 'docs')\"", "archive_2026/notes.md",
    "Expand-Archive -Path docs.zip -DestinationPath out", "Compress-Archive -Path docs -DestinationPath docs.zip",
    "rsync --archive docs/ backup/", "tar -xf site-archive.tar.gz", "docs/archive.md", "archive-2026/notes.md",
    "curl https://web.archive.org/web/2026/page",
    "inputs/0123456789abcdef/facilities.parquet", "inputs/README.md", "inputs/banking.md", "inputs/banks/x",
    "inputs/{0123456789abcdef,fedcba9876543210}/manifest.json", "inputs/{x,piggybank}/y", "ls inputs docs",
    "docs/bank/notes.md", "myinputs/bank/x", "my-inputs/bank/x", "inputs/bank-notes.md", "inputs/bank.md",
    "uv run pytest -q", "git status --short",
]


# git grep searches every tracked and untracked file without naming a folder.
GIT_GREP = ["git grep marker", "git  grep -n marker", "git --no-pager grep marker", "GIT GREP marker",
            "cd docs && git grep marker",
            # A git option with a value hid the subcommand until 9 November 2026:
            "git -C . grep marker", "git -c core.pager=cat grep -n marker", "git --git-dir .git grep marker"]
NOT_GIT_GREP = ["git log --grep=marker", "git log --oneline | grep marker", "git -C . log | grep marker",
                "git commit -m \"use the Grep tool, not grep\"", "git status --short", "grep -rn marker docs"]


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("guard_paths", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def named(hook, text: str) -> set[str]:
    return {name for name, pattern in hook.PROTECTED.items() if pattern.search(text)}


def call(tool: str, tool_input) -> subprocess.CompletedProcess:
    """One tool call put to the hook as Claude Code does: the event as JSON on standard input."""
    event = tool_input if isinstance(tool_input, str) else json.dumps({"tool_name": tool, "tool_input": tool_input})
    return subprocess.run([sys.executable, "-I", str(HOOK)], input=event, capture_output=True, text=True,
                          encoding="utf-8", check=False)


@pytest.mark.control("Repository rules")
def test_the_hook_guards_the_two_protected_folders(hook):
    assert set(hook.PROTECTED) == {ARCHIVE, BANK}


@pytest.mark.control("Repository rules")
@pytest.mark.parametrize("folder", [ARCHIVE, BANK])
def test_a_text_that_names_a_protected_folder_is_recognised(hook, folder):
    missed = [text for text in NAMED[folder] if folder not in named(hook, text)]
    assert not missed, f"{folder} is named but not recognised in: {missed}"
    shouted = [text.upper() for text in NAMED[folder] if folder not in named(hook, text.upper())]
    assert not shouted, f"case must not matter: {shouted}"


@pytest.mark.control("Repository rules")
def test_a_longer_word_or_another_folder_is_let_through(hook):
    caught = {text: sorted(named(hook, text)) for text in NOT_NAMED if named(hook, text)}
    assert not caught


@pytest.mark.control("Repository rules")
def test_git_grep_is_recognised_behind_any_git_option(hook):
    missed = [command for command in GIT_GREP if not hook.GIT_GREP.search(command)]
    caught = [command for command in NOT_GIT_GREP if hook.GIT_GREP.search(command)]
    assert not missed and not caught, (missed, caught)


@pytest.mark.control("Repository rules")
@pytest.mark.parametrize("tool, tool_input", [
    ("Read", {"file_path": "archive/notes.md"}),
    ("Edit", {"file_path": r"inputs\bank\loans.parquet", "old_string": "a", "new_string": "b"}),
    ("Glob", {"pattern": "{archive,docs}/**"}),
    ("Glob", {"pattern": "**/*.md", "path": "inputs/bank"}),
    ("Grep", {"pattern": "marker", "glob": "{docs,archive}/**"}),
    ("Bash", {"command": "ls {archive,docs}/"}),
    ("Bash", {"command": "git ls-files ':!archive'"}),
    ("PowerShell", {"command": r"Get-ChildItem inputs\{bank,x}"}),
    ("NotebookEdit", {"notebook_path": "archive/old.ipynb"}),
    ("mcp__ide__getDiagnostics", {"uri": "file:///c:/projects/stresstest_repo/archive/notes.md"}),
    ("mcp__any__tool", {"items": [{"path": "@inputs/bank/loans.parquet"}]}),
    ("Bash", {"command": "git grep marker"}),
    ("Bash", {"command": "git -C . grep marker"}),
])
def test_a_call_into_a_protected_folder_is_blocked(tool, tool_input):
    result = call(tool, tool_input)
    assert result.returncode == 2 and "guard_paths.py" in result.stderr, (tool, tool_input, result.stderr)


@pytest.mark.control("Repository rules")
@pytest.mark.parametrize("tool, tool_input", [
    ("Read", {"file_path": "docs/architecture.md"}),
    ("Glob", {"pattern": "inputs/0123456789abcdef/*.parquet"}),
    ("Bash", {"command": "uv run pytest -q"}),
    ("PowerShell", {"command": "Expand-Archive -Path docs.zip -DestinationPath out"}),
    # Content is not a path: a file or a search may mention a protected folder.
    ("Write", {"file_path": "docs/notes.md", "content": "archive/ and inputs/bank/ are off-limits"}),
    ("Grep", {"pattern": "archive", "path": "docs"}),
    ("TodoWrite", {"todos": [{"content": "ask about archive/"}]}),
])
def test_another_call_is_let_through(tool, tool_input):
    result = call(tool, tool_input)
    assert result.returncode == 0, (tool, tool_input, result.stderr)


@pytest.mark.control("Repository rules")
def test_an_unreadable_event_fails_closed():
    assert call("", "not json").returncode == 2
