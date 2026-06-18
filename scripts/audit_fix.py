"""Apply the dependency bumps the cooldown-aware audit considers actionable.

scripts/audit.py fails a release when a vulnerable dependency has a fix already
past the supply-chain cooldown. Rather than hand-editing the pin, this rewrites
the matching == pin in pyproject.toml to the lowest installable fix that clears
every actionable advisory for that dependency, re-locks through scripts/lock.py,
reinstalls so the environment matches the lock, verifies the advisories are
gone, and commits the result. release.py runs it before the audit gate so a
release never stalls on a bump a machine could have made.
"""

import re
import subprocess
import sys
from pathlib import Path

from packaging.version import Version

from audit import classify, run_report
from lock import cooldown_cutoff

PYPROJECT = Path("pyproject.toml")

# "name==version" with an optional environment marker we must preserve.
PIN_RE = re.compile(r'"([A-Za-z0-9_.-]+)==([^"\s;]+)([^"]*)"')


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def chosen_fix(findings: list[dict]) -> str:
    # Lowest installable fix per advisory; the max across advisories clears all.
    per_advisory_floor = [min(map(Version, f["installable"])) for f in findings]
    return str(max(per_advisory_floor))


def bump_pin(text: str, name: str, version: str) -> tuple[str, bool]:
    target = normalize(name)
    found = False

    def repl(m: re.Match) -> str:
        nonlocal found
        if normalize(m.group(1)) != target:
            return m.group(0)
        found = True
        return f'"{m.group(1)}=={version}{m.group(3)}"'

    return PIN_RE.sub(repl, text), found


def main() -> int:
    cutoff = cooldown_cutoff()
    actionable, _ = classify(run_report(), cutoff)
    if not actionable:
        print("No actionable vulnerabilities; nothing to bump.")
        return 0

    by_dep: dict[str, list[dict]] = {}
    for f in actionable:
        by_dep.setdefault(f["name"], []).append(f)

    text = PYPROJECT.read_text()
    bumps = []
    for name, findings in by_dep.items():
        version = chosen_fix(findings)
        text, found = bump_pin(text, name, version)
        if not found:
            sys.exit(
                f"{name} is flagged but not a == pin in pyproject.toml; fix by hand"
            )
        ids = ", ".join(sorted({f["id"] for f in findings}))
        bumps.append((name, findings[0]["version"], version, ids))

    PYPROJECT.write_text(text)
    subprocess.run([sys.executable, "scripts/lock.py"], check=True)
    # Sync the environment to the new lock so the re-audit (and the release
    # gate that follows) sees the bumped versions, not the stale install.
    subprocess.run(["pixi", "run", "build"], check=True)

    remaining, _ = classify(run_report(), cutoff)
    if remaining:
        leftover = ", ".join(f"{f['name']} {f['id']}" for f in remaining)
        sys.exit(f"bumps did not clear all actionable advisories: {leftover}")

    subprocess.run(
        ["git", "add", "pyproject.toml", "uv.lock", "requirements-dev.lock"],
        check=True,
    )
    body = "\n".join(f"- {n} {old} -> {new} ({ids})" for n, old, new, ids in bumps)
    subprocess.run(
        ["git", "commit", "-m", f"Bump dependencies for security advisories\n\n{body}"],
        check=True,
    )
    print("Bumped:\n" + body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
