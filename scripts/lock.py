"""Regenerate uv.lock and requirements-dev.lock with the release cooldown.

Resolves against an index snapshot from COOLDOWN_DAYS ago, so a freshly
published (potentially hijacked) release cannot enter the lock until it has
survived in the wild long enough to be caught and yanked.
"""

import subprocess
import sys
from datetime import UTC, datetime, timedelta

COOLDOWN_DAYS = 14


def main() -> None:
    cutoff = (datetime.now(UTC) - timedelta(days=COOLDOWN_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    print(f"Locking with --exclude-newer {cutoff} ({COOLDOWN_DAYS}-day cooldown)")
    subprocess.run(["uv", "lock", "--exclude-newer", cutoff], check=True)
    subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--extra",
            "dev",
            "--no-emit-project",
            "-o",
            "requirements-dev.lock",
        ],
        check=True,
    )


if __name__ == "__main__":
    sys.exit(main())
