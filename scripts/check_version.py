#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本号一致性检查。

三个地方必须对齐：
  1. metadata.yaml 的 version
  2. git tag（v 前缀可有可无）
  3. 传进去的目标 tag（打 tag / 发 release 时用）

用法：
  python scripts/check_version.py                  # 只查 metadata 自己是否合法
  python scripts/check_version.py v1.2.0           # 查 metadata 和这个 tag 是否一致
  python scripts/check_version.py --git            # 查 metadata 和最近的 git tag
  python scripts/check_version.py --bump minor     # 直接把 version 往上推一档
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META = ROOT / "metadata.yaml"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version() -> str:
    if not META.exists():
        sys.exit(f"找不到 {META}")
    for line in META.read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    sys.exit("metadata.yaml 里没有 version 字段")


def write_version(v: str) -> None:
    text = META.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^version:\s*.*$", f"version: {v}", text)
    if n != 1:
        sys.exit(f"写 version 失败，匹配到 {n} 处")
    META.write_text(new, encoding="utf-8")


def last_tag() -> str:
    """拿最近的 v* 标签；仓库里没有就退回 HEAD 里 metadata 的版本。"""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out
    except Exception:
        return ""


def normalize(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def bump(v: str, part: str) -> str:
    m = SEMVER.match(v)
    if not m:
        sys.exit(f"当前 version 不是语义化版本: {v}")
    major, minor, patch = (int(x) for x in m.groups())
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def main() -> int:
    ap = argparse.ArgumentParser(description="检查 metadata.yaml 的版本号")
    ap.add_argument("target", nargs="?", help="要对比的 tag，比如 v1.2.0")
    ap.add_argument("--git", action="store_true", help="和最近的 git tag 对比")
    ap.add_argument("--bump", choices=["major", "minor", "patch"], help="升一档版本号")
    args = ap.parse_args()

    current = read_version()

    if args.bump:
        nv = bump(current, args.bump)
        write_version(nv)
        print(f"version: {current} -> {nv}")
        print(f"记得提交，然后 git tag v{nv} && git push --tags")
        return 0

    if not SEMVER.match(current):
        print(f"FAIL  metadata 的 version 不是语义化版本: {current}")
        return 1

    print(f"metadata version: {current}")

    target = args.target or (last_tag() if args.git else "")
    if not target:
        print("OK    没有可对比的 tag，只看 metadata 本身")
        return 0

    want = normalize(target)
    if want != current:
        print(f"FAIL  tag {target} 和 metadata 的 {current} 对不上")
        print(f"      要么改 metadata 到 {want}，要么换个 tag")
        return 1

    print(f"OK    tag {target} 和 metadata 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
