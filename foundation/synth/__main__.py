"""Run O2-O4: ``python -m foundation.synth [build|approve]``."""

import argparse
import sys
from datetime import date
from pathlib import Path

from foundation.synth import build
from foundation.synth.config import SEED
from foundation.synth.inputset import approve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m foundation.synth")
    sub = parser.add_subparsers(dest="command")
    b = sub.add_parser("build", help="build one hashed input set (default)")
    b.add_argument("--spec-dir", type=Path, default=Path("docs/spec"))
    b.add_argument("--params", type=Path, default=Path("foundation/parameter_set.yaml"))
    b.add_argument("--out", type=Path, default=Path("inputs"))
    b.add_argument("--seed", type=int, default=SEED)
    a = sub.add_parser("approve", help="record the owner's approval of an input set")
    a.add_argument("folder", type=Path)
    a.add_argument("--approver", required=True)
    argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(argv or ["build"])
    if args.command == "approve":
        approve(args.folder, args.approver, date.today().isoformat())
        print(f"approved {args.folder.as_posix()} by {args.approver}")
        return 0
    path = build(args.spec_dir, args.params, args.out, args.seed)
    print(f"input set {path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
