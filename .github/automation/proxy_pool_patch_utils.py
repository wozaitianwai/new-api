from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def repo_path(relative: str) -> Path:
    return ROOT / relative


def read(relative: str) -> str:
    return repo_path(relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = repo_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> None:
    content = read(relative)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(
            f"{relative}: expected exactly one anchor, found {count}\nANCHOR:\n{old[:500]}"
        )
    write(relative, content.replace(old, new, 1))


def replace_regex_once(relative: str, pattern: str, replacement: str) -> None:
    content = read(relative)
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(
            f"{relative}: regex anchor did not match exactly once: {pattern}"
        )
    write(relative, updated)


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    expect_failure: bool = False,
    env: dict[str, str] | None = None,
) -> None:
    print(f"\n$ {' '.join(command)}")
    process = subprocess.run(
        command,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(process.stdout)
    if expect_failure:
        if process.returncode == 0:
            raise RuntimeError(f"expected command to fail: {' '.join(command)}")
        print("Observed expected failing test.")
        return
    if process.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {process.returncode}: {' '.join(command)}"
        )


def gofmt(*relative_paths: str) -> None:
    run(["gofmt", "-w", *relative_paths])
