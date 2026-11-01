"""One CI/local gate; generated files and temporary test runs stay under tests/."""

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    import_linter = Path(sys.executable).parent / ("lint-imports.exe" if os.name == "nt" else "lint-imports")
    temporary = root / "tests" / (".ci-" + uuid.uuid4().hex)
    commands = [
        [sys.executable, "-m", "foundation.transcribe", "--check"],
        [sys.executable, "-m", "ruff", "check"],
        [str(import_linter), "--cache-dir", "tests/.import_linter_cache"],
        [sys.executable, "-m", "pytest", "-q", "--tb=short", "--basetemp", str(temporary)],
    ]
    try:
        for command in commands:
            result = subprocess.run(command, cwd=root, check=False)
            if result.returncode:
                return result.returncode
        return 0
    finally:
        shutil.rmtree(temporary, ignore_errors=True)  # each gate leaves hundreds of MB otherwise


if __name__ == "__main__":
    sys.exit(main())
