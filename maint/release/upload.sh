#!/usr/bin/env bash
# 上传 v3.28.0–v3.32.2 七个 release 到 asktai/doc-compliance-review
# 用法：export GH_TOKEN=... ; bash /workspace/dev/maint/release/upload.sh
# 幂等：已存在的 release 会报错并跳过，不重复创建
set -u
REPO="asktai/doc-compliance-review"
DIST="/workspace/dist"
NOTES="/workspace/dev/maint/release"

if [ -z "${GH_TOKEN:-}" ] && [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "缺少 GH_TOKEN（或 GITHUB_TOKEN），中止" >&2
  exit 2
fi

ok=0; fail=0
mk() {
  v="$1"; title="$2"; shift 2
  if gh release view "$v" -R "$REPO" >/dev/null 2>&1; then
    echo "[skip] $v 已存在"
    return 0
  fi
  args=()
  for f in "$@"; do args+=("$DIST/$f"); done
  if gh release create "$v" -R "$REPO" --title "$title" --notes-file "$NOTES/$v.md" "${args[@]}" >/dev/null; then
    echo "[ok]   $v"
    ok=$((ok+1))
  else
    echo "[fail] $v"
    fail=$((fail+1))
  fi
}

mk v3.28.0 "v3.28.0 交付物格式 5→7 种：PPT 讲解版＋思维导图＋HTML 离线/在线双模" \
  "文档合规审查助手AI合同_v3.28.0_20261105_(doc-compliance-review).skill" \
  "文档合规审查助手AI合同_v3.28.0_20261105_(doc-compliance-review).zip"

mk v3.29.0 "v3.29.0 思维导图默认形态改 SVG（零依赖），HTML/PNG 改开关追加" \
  "文档合规审查助手AI合同_v3.29.0_20261105_(doc-compliance-review).skill" \
  "文档合规审查助手AI合同_v3.29.0_20261105_(doc-compliance-review).zip"

mk v3.30.0 "v3.30.0 精要总结入口与交付物导图收口：产物隔离＋同源断言＋口径统一" \
  "文档合规审查助手AI合同_v3.30.0_20261105_(doc-compliance-review).skill" \
  "文档合规审查助手AI合同_v3.30.0_20261105_(doc-compliance-review).zip"

# v3.31.0 不出包：内部准备步，改动随 v3.32.0 交付
gh release create v3.31.0 -R "$REPO" \
  --title "v3.31.0 重构准备：字节级黄金基线＋两档项数守恒（本版未单独出包）" \
  --notes-file "$NOTES/v3.31.0.md" >/dev/null 2>&1 \
  && echo "[ok]   v3.31.0（无附件）" || echo "[skip/fail] v3.31.0"

mk v3.32.0 "v3.32.0 三引擎架构落地：格式/风格/去AI味三引擎＋image 家族＋导图六态" \
  "文档合规审查助手AI合同_v3.32.0_20261105_(doc-compliance-review).skill" \
  "文档合规审查助手AI合同_v3.32.0_20261105_(doc-compliance-review).zip"

mk v3.32.1 "v3.32.1 交付物类型编号冲突修复＋三清单编号咬合守卫" \
  "文档合规审查助手AI合同_v3.32.1_20261105_(doc-compliance-review).skill" \
  "文档合规审查助手AI合同_v3.32.1_20261105_(doc-compliance-review).zip"

mk v3.32.2 "v3.32.2 行业库清单口径分家修复＋行业清单四处咬合守卫" \
  "文档合规审查助手AI合同_v3.32.2_20261106_(doc-compliance-review).skill" \
  "文档合规审查助手AI合同_v3.32.2_20261106_(doc-compliance-review).zip"

echo "----"
echo "上传完成：成功 $ok 个有附件版本，失败 $fail 个"
