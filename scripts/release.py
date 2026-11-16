#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键发版：校验版本 -> 检查工作区 -> 打包 -> 打 tag 推送 -> 建 Release。

用法：
    python scripts/release.py 1.1.0
    python scripts/release.py 1.1.0 --no-push     # 只打包打 tag，不推

不用 git hook：这台机器的 git for Windows 起不了 sh（couldn't create signal
pipe, Win32 error 5），钩子机制整个不工作，所以校验放在这里做。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_NAME = "astrbot_plugin_link_preview.zip"
SKIP_PARTS = {"__pycache__", "data", ".git", "scripts", ".githooks"}

# 这台机器上 gh 不在 PATH 里，几个常见位置都试一下
GH_CANDIDATES = [
    "gh",
    r"E:/Apps/GitHub CLI/bin/gh.exe",
    r"D:/dsh-tools/gh/gh.exe",
    r"C:/Program Files/GitHub CLI/gh.exe",
]

# 默认 git 的 schannel 后端报 SEC_E_NO_CREDENTIALS，PortableGit 的 openssl 后端能用
GIT_CANDIDATES = [
    "git",
    r"C:/Users/Public/PortableGit/cmd/git.exe",
]

SSH_BYPASS = ["-c", "http.sslBackend=openssl", "-c", "http.sslVerify=false"]


def find_gh() -> str | None:
    for cand in GH_CANDIDATES:
        if Path(cand).exists():
            return str(Path(cand))
        hit = shutil.which(cand)
        if hit:
            return hit
    return None


def find_git() -> str | None:
    """优先用能正常推的 git：PortableGit 的 openssl 后端。"""
    import glob

    for pat in (r"C:/Users/*/PortableGit/cmd/git.exe",):
        for hit in glob.glob(pat):
            return hit
    return shutil.which("git")


def run(cmd: list[str], check: bool = True, capture: bool = False, cwd: Path | None = None):
    return subprocess.run(cmd, cwd=cwd or ROOT, check=check, text=True, capture_output=capture)


def main() -> int:
    ap = argparse.ArgumentParser(description="发版")
    ap.add_argument("version", help="版本号，比如 1.1.0")
    ap.add_argument("--bump-only", action="store_true", help="只改 metadata 的版本号")
    ap.add_argument("--no-push", action="store_true", help="打包打 tag，但不推送")
    args = ap.parse_args()

    tag = f"v{args.version}"

    print(f"== 1/5 校验版本（{tag}）")
    rc = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_version.py"), tag],
                        cwd=ROOT).returncode
    if rc != 0:
        print("\n版本对不上。改 metadata.yaml 的 version，或者换个版本号。")
        return 1
    if args.bump_only:
        print("只改版本号，完成。")
        return 0

    git = find_git()
    if not git:
        print("找不到 git。")
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
            if any(p in SKIP_PARTS for p in f.parts):
                continue
            if not f.is_file():
                continue
            arc = Path("astrbot_plugin_link_preview") / f.relative_to(ROOT)
            z.write(f, arc.as_posix())
            n += 1
    print(f"    {n} 个文件，{out.stat().st_size} 字节")

    print(f"== 4/5 打 tag {tag}")
    exists = run([git, "tag", "--list", tag], capture=True).stdout.strip()
    if exists:
        print(f"    标签 {tag} 已存在，跳过")
    else:
        run([git, "tag", tag])
        print(f"    已创建 {tag}")

    if args.no_push:
        print("== 5/5 跳过推送（--no-push）")
        return 0

    print("== 5/5 推送并建 Release")
    gh = find_gh()
    # origin 里没有凭据，push 会去敲门要密码。有 gh 就把它的 token 拼进 URL。
    remote_url = None
    if gh:
        tok = run([gh, "auth", "token"], check=False, capture=True)
        if tok.returncode == 0 and tok.stdout.strip():
            remote_url = (
                "https://x-access-token:"
                f"{tok.stdout.strip()}@github.com/"
                "hongdougao111/astrbot_plugin_link_preview.git"
            )

    push_cmd = [git, *SSH_BYPASS, "push", remote_url or "origin", tag]
    r = run(push_cmd, check=False, capture=True)
    out_text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        if "already exists" in out_text:
            print("    远程已有这个标签，跳过推送")
        else:
            print(f"    推送失败，重试一次\n    {out_text.strip().splitlines()[-1] if out_text.strip() else ''}")
            r = run(push_cmd, check=False, capture=True)
            out_text = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0 and "already exists" not in out_text:
                print(f"    还是没推上去。手动：{git} {' '.join(SSH_BYPASS)} push origin {tag}")
                return 1
    if not gh:
        print("    找不到 gh，跳过 Release 创建。标签已经推上去了。")
        return 0
    print(f"    gh: {gh}")

    # 已经存在就补资产，不重复建
    chk = run([gh, "release", "view", tag, "--repo-from-origin"], check=False, capture=True)
    if chk.returncode == 0:
        print(f"    Release {tag} 已存在，上传附件")
        run([gh, "release", "upload", tag, str(out), "--clobber"], check=False)
    else:
        r = run([gh, "release", "create", tag, str(out),
                 "--title", f"链接解析 {tag}", "--generate-notes"], check=False)
        if r.returncode != 0:
            print("    Release 创建失败，检查 gh 登录状态。")
            return 1

    print(f"\n完成：{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())