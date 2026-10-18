"""Run O1: ``python -m foundation.transcribe [--spec-dir docs/spec] [--check]``."""

import argparse
import sys
from pathlib import Path

from foundation.transcribe import check, write


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m foundation.transcribe", description=__doc__)
    parser.add_argument("--spec-dir", type=Path, default=Path("docs/spec"))
    parser.add_argument("--check", action="store_true", help="compare with the files; write nothing")
    args = parser.parse_args(argv)
    if args.check:
        stale = check(args.spec_dir)
        for name in stale:
            print(f"stale: {name}")
        print("O1 files are current" if not stale else f"{len(stale)} O1 file(s) differ")
        return 1 if stale else 0
    for path in write(args.spec_dir):
        print(f"wrote {path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
