#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键发版：校验版本 -> 检查工作区 -> 打包 -> 打 tag 推送 -> 建 Release。

用法：
    python scripts/release.py 1.1.0
    python scripts/release.py 1.1.0 --bump-only    # 只改 metadata 的版本号

不用 git hook：这台机器上 git for Windows 起不了 sh（signal pipe 报错），
钩子机制整个不工作，所以校验放在这里做，发版必经此路。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_NAME = "astrbot_plugin_link_preview.zip"
SKIP_PARTS = {"__pycache__", "data", ".git", "scripts", ".githooks"}


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True,
                          capture_output=capture)


def git(*args: str, check: bool = True, capture: bool = False):
    return run(["git", *args], check=check, capture=capture)


def check_version(tag: str) -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_version.py"), tag],
        cwd=ROOT,
    ).returncode


def build_zip() -> Path:
    out = ROOT.parent / ZIP_NAME
    if out.exists():
        out.unlink()
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(ROOT.rglob("*")):
            if any(p in SKIP_PARTS for p in f.parts):
                continue
            if not f.is_file():
                continue
            arc = Path("astrbot_plugin_link_preview") / f.relative_to(ROOT)
            z.write(f, arc.as_posix())
            count += 1
    print(f"    打包 {count} 个文件，{out.stat().st_size} 字节")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="发版")
    ap.add_argument("version", help="版本号，比如 1.1.0")
    ap.add_argument("--bump-only", action="store_true", help="只改 metadata 的版本号，不做别的")
    ap.add_argument("--no-push", action="store_true", help="打包打 tag，但不推送")
    args = ap.parse_args()

    tag = f"v{args.version}"
    print(f"== 1/5 校验版本（{tag}）")
    if check_version(tag) != 0:
        print("\n版本对不上。改 metadata.yaml 的 version，或者换个版本号。")
        return 1

    if args.bump_only:
        print("只改版本号，完成。")
        return 0

    print("== 2/5 检查工作区")
    dirty = git("status", "--porcelain", capture=True).stdout.strip()
    if dirty:
        print("工作区有未提交的改动，先提交再发版：")
        print(dirty)
        return 1

    print("== 3/5 打包")
    zip_path = build_zip()

    print(f"== 4/5 打 tag {tag}")
    existing = git("tag", "--list", tag, capture=True).stdout.strip()
    if existing:
        print(f"    标签 {tag} 已存在，跳过打标签")
    else:
        git("tag", tag)
        print(f"    已创建 {tag}")

    if args.no_push:
        print("== 5/5 跳过推送（--no-push）")
        return 0

    print("== 5/5 推送并建 Release")
    check = run(["gh", "auth", "status"], check=False, capture=True)
    if check.returncode != 0:
        print("    gh 没登录或不在 PATH，跳过 Release 创建。")
        print(f"    手动推送：git push origin {tag}")
        return 0
    try:
        git("push", "origin", tag)
    except subprocess.CalledProcessError:
        print("    git push 失败。这台机器的 git 传输层有 schannel 问题，")
        print("    用 PortableGit 加 openssl 后端再试：")
        print("    C:/Users/<你>/PortableGit/cmd/git.exe "
              "-c http.sslBackend=openssl -c http.sslVerify=false push origin " + tag)
        return 1

    r = run(["gh", "release", "create", tag, str(zip_path),
             "--title", f"链接解析 {tag}", "--generate-notes"], check=False)
    if r.returncode != 0:
        print("    Release 创建失败，检查 gh 登录状态。")
        return 1

    print(f"\n完成：{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
