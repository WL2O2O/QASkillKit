#!/usr/bin/env bash
# 重渲染 README 配图：HTML 源 → PNG（Chrome headless，2x 分辨率保证 Retina 清晰）。
# 用法：bash docs/assets/src/render.sh            # 渲染全部
#       bash docs/assets/src/render.sh hero eval-gate   # 只渲染指定几张
# 依赖：macOS + Google Chrome（可用 CHROME 环境变量覆盖浏览器路径）。
set -euo pipefail
cd "$(dirname "$0")/../../.."
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
SPECS="hero:1400:400 architecture:1400:770 eval-gate:1400:840 demo-zero-key:1240:640 demo-blocked:1240:540 demo-judge:1240:660 hero-en:1400:400 architecture-en:1400:800 eval-gate-en:1400:840 demo-judge-en:1240:660"
render() {
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --window-size="$2,$3" \
    --screenshot="docs/assets/$1.png" \
    "file://$PWD/docs/assets/src/$1.html" 2>&1 | tail -1
}
for spec in $SPECS; do
  name="${spec%%:*}"; rest="${spec#*:}"; w="${rest%%:*}"; h="${rest##*:}"
  if [ $# -eq 0 ]; then render "$name" "$w" "$h"; else
    for want in "$@"; do
      if [ "$want" = "$name" ]; then render "$name" "$w" "$h"; fi
    done
  fi
done