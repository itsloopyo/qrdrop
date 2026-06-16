"""Cooldown-aware dependency audit.

pip-audit flags every known vulnerability, but a fix we cannot install yet is
not an actionable failure: scripts/lock.py refuses any release younger than the
COOLDOWN_DAYS window, so a CVE whose only fix landed inside that window cannot
enter the lock no matter what we do. This wrapper fails only when a fix exists
that is already old enough to install; vulnerabilities whose every fix is still
inside the cooldown are reported as deferred warnings. Once such a fix ages past
the window the audit fails again and forces the bump.
"""

import json
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime, timedelta

from lock import COOLDOWN_DAYS

# Advisories with no version-pinnable fix here (e.g. disputed or transitive).
IGNORED_VULNS = ("PYSEC-2026-196",)


def published_before(package: str, version: str, cutoff: datetime) -> bool:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    with urllib.request.urlopen(url) as resp:
        uploads = json.load(resp)["urls"]
    if not uploads:
        raise RuntimeError(f"no upload metadata for {package}=={version}")
    published = min(
        datetime.fromisoformat(u["upload_time_iso_8601"].replace("Z", "+00:00"))
        for u in uploads
    )
    return published < cutoff


def main() -> int:
    cutoff = datetime.now(UTC) - timedelta(days=COOLDOWN_DAYS)
    ignore_args = [arg for vuln in IGNORED_VULNS for arg in ("--ignore-vuln", vuln)]
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--skip-editable", *ignore_args, "--format", "json"],
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    actionable, deferred = [], []
    for dep in report["dependencies"]:
        for vuln in dep.get("vulns", []):
            installable = [
                fix for fix in vuln["fix_versions"]
                if published_before(dep["name"], fix, cutoff)
            ]
            row = (dep["name"], dep["version"], vuln["id"], vuln["fix_versions"])
            (actionable if installable else deferred).append(row)

    if deferred:
        print(f"Deferred ({COOLDOWN_DAYS}-day cooldown; re-flags once a fix ages out):")
        for name, version, vid, fixes in deferred:
            print(f"  {name} {version}  {vid}  fix: {', '.join(fixes) or 'none yet'}")

    if actionable:
        print("\nActionable (an installable fix is already past the cooldown):")
        for name, version, vid, fixes in actionable:
            print(f"  {name} {version}  {vid}  fix: {', '.join(fixes)}")
        return 1

    print(f"\nNo actionable vulnerabilities ({len(deferred)} deferred).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
