import argparse
import re
import subprocess
from pathlib import Path

IMAGE = "itsloopyo/qrdrop"

VERSION_RE = re.compile(r'^version = "(\d+\.\d+\.\d+)"$', re.MULTILINE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--push",
        action="store_true",
        help="multi-platform release build pushed to Docker Hub",
    )
    args = parser.parse_args()

    if args.push:
        version = VERSION_RE.search(Path("pyproject.toml").read_text()).group(1)
        cmd = [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/amd64,linux/arm64",
            "--push",
            "-t",
            f"{IMAGE}:latest",
            "-t",
            f"{IMAGE}:{version}",
            ".",
        ]
    else:
        cmd = ["docker", "build", "-t", f"{IMAGE}:dev", "."]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
