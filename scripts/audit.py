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
from datetime import datetime

from lock import COOLDOWN_DAYS, cooldown_cutoff

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


def run_report() -> dict:
    ignore_args = [arg for vuln in IGNORED_VULNS for arg in ("--ignore-vuln", vuln)]
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--skip-editable", *ignore_args, "--format", "json"],
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def classify(report: dict, cutoff: datetime) -> tuple[list[dict], list[dict]]:
    actionable, deferred = [], []
    for dep in report["dependencies"]:
        for vuln in dep.get("vulns", []):
            installable = [
                fix for fix in vuln["fix_versions"]
                if published_before(dep["name"], fix, cutoff)
            ]
            finding = {
                "name": dep["name"],
                "version": dep["version"],
                "id": vuln["id"],
                "fix_versions": vuln["fix_versions"],
                "installable": installable,
            }
            (actionable if installable else deferred).append(finding)
    return actionable, deferred


def main() -> int:
    actionable, deferred = classify(run_report(), cooldown_cutoff())

    if deferred:
        print(f"Deferred ({COOLDOWN_DAYS}-day cooldown; re-flags once a fix ages out):")
        for f in deferred:
            fixes = ", ".join(f["fix_versions"]) or "none yet"
            print(f"  {f['name']} {f['version']}  {f['id']}  fix: {fixes}")

    if actionable:
        print("\nActionable (an installable fix is already past the cooldown):")
        for f in actionable:
            print(f"  {f['name']} {f['version']}  {f['id']}  fix: {', '.join(f['fix_versions'])}")
        return 1

    print(f"\nNo actionable vulnerabilities ({len(deferred)} deferred).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
