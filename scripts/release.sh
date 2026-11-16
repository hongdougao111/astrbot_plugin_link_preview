#!/bin/sh
# 一键发版：校验版本 -> 打包 -> 打 tag -> 推送 -> 建 Release
# 用法：sh scripts/release.sh 1.1.0
set -e

VERSION="$1"
if [ -z "$VERSION" ]; then
    echo "用法：sh scripts/release.sh 1.1.0"
    exit 1
fi

cd "$(dirname "$0")/.."

echo "== 1/5 校验版本"
python scripts/check_version.py "v$VERSION"

echo "== 2/5 确认工作区干净"
if [ -n "$(git status --porcelain)" ]; then
    echo "工作区有未提交的改动，先提交再发版。"
    git status --short
    exit 1
fi

echo "== 3/5 打包"
python - <<'PY'
import zipfile, pathlib
root = pathlib.Path(".")
skip = {"__pycache__", "data", ".git", "scripts", ".githooks"}
out = pathlib.Path("../astrbot_plugin_link_preview.zip")
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(root.rglob("*")):
        if any(p in skip for p in f.parts):
            continue
        if f.is_file():
            z.write(f, (pathlib.Path("astrbot_plugin_link_preview") / f.relative_to(root)).as_posix())
print("zip", out.stat().st_size, "bytes")
PY

echo "== 4/5 打 tag 并推送"
git tag "v$VERSION"
git push origin "v$VERSION"

echo "== 5/5 建 Release"
gh release create "v$VERSION" ../astrbot_plugin_link_preview.zip \
    --title "v$VERSION" \
    --generate-notes

echo ""
echo "完成：v$VERSION"
