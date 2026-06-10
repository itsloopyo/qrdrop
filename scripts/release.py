import re
import subprocess
import sys
from pathlib import Path

VERSION_RE = re.compile(r'^(version|__version__) = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)

VERSION_FILES = (Path("pyproject.toml"), Path("pixi.toml"), Path("src/qrdrop/__init__.py"))

EXCLUDE_NEWER_RE = re.compile(r'^exclude-newer = "(.+)"$', re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("major", "minor", "patch"):
        sys.exit("usage: release.py major|minor|patch")
    part = sys.argv[1]

    if git("branch", "--show-current") != "main":
        sys.exit("releases must be cut from main")
    if git("status", "--porcelain"):
        sys.exit("working tree is dirty; commit or stash first")
    git("pull", "--ff-only")

    major, minor, patch = map(
        int, VERSION_RE.search(VERSION_FILES[0].read_text()).groups()[1:]
    )
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    version = f"{major}.{minor}.{patch}"

    for path in VERSION_FILES:
        path.write_text(VERSION_RE.sub(rf'\1 = "{version}"', path.read_text(), count=1))

    # uv.lock records qrdrop's own version. Re-lock against the snapshot
    # cutoff already in the lockfile so only that version entry changes,
    # never the dependency resolution (pixi run lock owns that).
    cutoff = EXCLUDE_NEWER_RE.search(Path("uv.lock").read_text()).group(1)
    subprocess.run(["uv", "lock", "--exclude-newer", cutoff], check=True)

    git("add", "uv.lock", *(str(p) for p in VERSION_FILES))
    git("commit", "-m", f"Release v{version}")
    git("tag", f"v{version}")
    git("push", "origin", "main", f"v{version}")
    print(
        f"v{version} pushed; the Release workflow will test, build, "
        "and publish to PyPI and Docker Hub"
    )


if __name__ == "__main__":
    main()
