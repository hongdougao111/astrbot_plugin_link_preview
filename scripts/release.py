#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键发版：校验版本 -> 检查工作区 -> 打包 -> 打 tag 推送 -> 建 Release。

用法：
    python scripts/release.py 1.1.0
    python scripts/release.py 1.1.0 --no-push        # 只打包打 tag，不推
    python scripts/release.py 1.1.0 --gh /path/gh    # 手动指定 gh
    python scripts/release.py 1.1.0 --git /path/git  # 手动指定 git

工具查找顺序：命令行参数 > 环境变量 GH_PATH / GIT_PATH > PATH。
三个都没有就报错，不猜路径。

不用 git hook：这台机器的 git for Windows 起不了 sh（couldn't create signal
pipe, Win32 error 5），钩子机制整个不工作，所以校验放在这里做。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_NAME = "astrbot_plugin_link_preview.zip"
SKIP_PARTS = {"__pycache__", "data", ".git", "scripts", ".githooks"}
# git 传输层参数：某些 Windows 环境的 schannel 后端报 SEC_E_NO_CREDENTIALS
GIT_TLS_ARGS = ["-c", "http.sslBackend=openssl", "-c", "http.sslVerify=false"]


def find_tool(name: str, env_var: str, explicit: str | None) -> str | None:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return str(p)
        return shutil.which(explicit)
    env = os.environ.get(env_var)
    if env:
        p = Path(env)
        if p.exists():
            return str(p)
        print(f"    警告：{env_var}={env} 不存在，改用 PATH 查找")
    return shutil.which(name)


def repo_slug(git: str) -> tuple[str, str] | None:
    """从 origin 的 URL 推 owner/repo，支持 https 和 ssh。"""
    r = run([git, "remote", "get-url", "origin"], check=False, capture=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    url = r.stdout.strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    if not m:
        return None
    return m.group(1), m.group(2)


def run(cmd: list[str], check: bool = True, capture: bool = False):
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True, capture_output=capture)


def main() -> int:
    ap = argparse.ArgumentParser(description="发版")
    ap.add_argument("version", help="版本号，比如 1.1.0")
    ap.add_argument("--bump-only", action="store_true", help="只改 metadata 的版本号")
    ap.add_argument("--no-push", action="store_true", help="打包打 tag，但不推送")
    ap.add_argument("--gh", help="gh 可执行文件路径")
    ap.add_argument("--git", help="git 可执行文件路径")
    args = ap.parse_args()

    tag = f"v{args.version}"

    print(f"== 1/5 校验版本（{tag}）")
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_version.py"), tag], cwd=ROOT
    ).returncode
    if rc != 0:
        print("\n版本对不上。改 metadata.yaml 的 version，或者换个版本号。")
        return 1
    if args.bump_only:
        print("只改版本号，完成。")
        return 0

    git = find_tool("git", "GIT_PATH", args.git)
    if not git:
        print("找不到 git。用 --git 指定，或者设环境变量 GIT_PATH。")
        return 1
    print(f"    git: {git}")

    print("== 2/5 检查工作区")
    dirty = run([git, "status", "--porcelain"], capture=True).stdout.strip()
    if dirty:
        print("工作区有未提交的改动，先提交再发版：")
        print(dirty)
        return 1

    print("== 3/5 打包")
    out = ROOT.parent / ZIP_NAME
    if out.exists():
        out.unlink()
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(ROOT.rglob("*")):
            if any(p in SKIP_PARTS for p in f.parts) or not f.is_file():
                continue
            arc = Path("astrbot_plugin_link_preview") / f.relative_to(ROOT)
            z.write(f, arc.as_posix())
            n += 1
    print(f"    {n} 个文件，{out.stat().st_size} 字节")

    print(f"== 4/5 打 tag {tag}")
    if run([git, "tag", "--list", tag], capture=True).stdout.strip():
        print(f"    标签 {tag} 已存在，跳过")
    else:
        run([git, "tag", tag])
        print(f"    已创建 {tag}")

    if args.no_push:
        print("== 5/5 跳过推送（--no-push）")
        return 0

    print("== 5/5 推送并建 Release")
    gh = find_tool("gh", "GH_PATH", args.gh)
    slug = repo_slug(git)

    # origin 里通常没凭据，push 会去敲门要密码。有 gh 就用它的 token 拼 URL。
    remote = "origin"
    if gh and slug:
        tok = run([gh, "auth", "token"], check=False, capture=True)
        if tok.returncode == 0 and tok.stdout.strip():
            remote = (
                f"https://x-access-token:{tok.stdout.strip()}"
                f"@github.com/{slug[0]}/{slug[1]}.git"
            )

    push_cmd = [git, *GIT_TLS_ARGS, "push", remote, tag]
    r = run(push_cmd, check=False, capture=True)
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and "already exists" not in text:
        print("    推送失败，重试一次")
        r = run(push_cmd, check=False, capture=True)
        text = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 and "already exists" not in text:
            last = text.strip().splitlines()[-1] if text.strip() else "(无输出)"
            print(f"    没推上去：{last}")
            print(f"    手动：{git} {' '.join(GIT_TLS_ARGS)} push origin {tag}")
            return 1
    if "already exists" in text:
        print("    远程已有这个标签，跳过推送")

    if not gh:
        print("    找不到 gh，跳过 Release。用 --gh 指定，或者设环境变量 GH_PATH。")
        return 0
    print(f"    gh: {gh}")

    view = [gh, "release", "view", tag]
    if slug:
        view += ["--repo", f"{slug[0]}/{slug[1]}"]
    chk = run(view, check=False, capture=True)

    base = [gh, "release"]
    if chk.returncode == 0:
        r = run([*base, "upload", tag, str(out), "--clobber", *(["--repo", f"{slug[0]}/{slug[1]}"] if slug else [])], check=False)
        print("    Release 已存在，附件已更新")
    else:
        r = run([*base, "create", tag, str(out), "--title", f"链接解析 {tag}", "--generate-notes",
                 *(["--repo", f"{slug[0]}/{slug[1]}"] if slug else [])], check=False)
        print("    Release 已创建")
    if r.returncode != 0:
        print("    Release 操作失败，检查 gh 登录状态（gh auth status）。")
        return 1

    print(f"\n完成：{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
