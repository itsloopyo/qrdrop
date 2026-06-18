"""Regenerate uv.lock and requirements-dev.lock with the release cooldown.

Resolves against an index snapshot from COOLDOWN_DAYS ago, so a freshly
published (potentially hijacked) release cannot enter the lock until it has
survived in the wild long enough to be caught and yanked.
"""

import subprocess
import sys
from datetime import UTC, datetime, timedelta

COOLDOWN_DAYS = 14


def cooldown_cutoff() -> datetime:
    """The exclude-newer boundary, truncated to midnight UTC.

    uv's --exclude-newer takes an instant, and the audit must judge a fix
    installable against the *same* instant the lock will use - otherwise a fix
    published on the cutoff day is "actionable" to the audit yet rejected by the
    lock, and the release wedges. Truncating to midnight is what makes both
    sides agree.
    """
    return (datetime.now(UTC) - timedelta(days=COOLDOWN_DAYS)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def main() -> None:
    cutoff = cooldown_cutoff().strftime("%Y-%m-%dT%H:%M:%SZ")
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
