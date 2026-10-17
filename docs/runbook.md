# Runbook

## Protection check

Run this after setting up the repo, after any change to `.claude/`, and after upgrading Claude Code.

### Archive and `inputs/bank/`

1. Outside Claude Code, create `archive/canary.md` containing a unique marker, for example `CANARY-7f3e2a`. Do the same in `inputs/bank/canary.md`.
2. Start Claude Code from the repo root and run `/permissions`. Check that the deny rules from `.claude/settings.json` are listed.
3. Ask Claude Code to try each of the following and report what happened:
   - read `archive/canary.md`;
   - search the whole repo for the marker with the Grep tool;
   - list `archive/` with the Glob tool;
   - run `cat archive/canary.md` and `rg <marker>` from the repo root in Bash;
   - run `Get-Content archive\canary.md` in PowerShell;
   - run `git log -p` (once the repo is in git);
   - ask a subagent to read the file.
4. Every attempt must be blocked or return nothing. If the marker appears anywhere in Claude's output, the protection has a gap. Fix it before putting anything real in `archive/`.
5. Delete the canary files.

### Locked folders

Ask Claude Code to add a line to `docs/spec/README.md`, a file under `inputs/<hash>/` and a file under `runs/<run_id>/`. Each Edit or Write must be denied.
