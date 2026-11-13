#!/usr/bin/env bash
# QASkillKit A/B prompt 回归演示（一键脚本）
#
# 干什么：同一套评测集、同一个模型，分别用两份被测 prompt 现场生成用例并打分——
#   A = prompts/testcase-generator.public.md（正式版）
#   B = prompts/variant-b-weakened.md（故意弱化版，反面教材）
# 然后用 --diff 对比两份报告，看评测器能不能自动抓出 B 的退步。
#
# 用法：
#   export GLM_API_KEY=sk-xxx     # 或 EVAL_LLM_API_KEY / OPENAI_API_KEY，只走环境变量
#   bash evals/ab-demo.sh         # 已有报告的变体自动跳过（断点续跑）
#   FORCE=1 bash evals/ab-demo.sh # 强制重跑两个变体
#
# 产物（全部落仓库目录，方便事后阅读/入库）：
#   evals/ab-demo/a/  A 变体报告 json+md，a/cases-HHMMSS/ 是那一轮 A 现场生成的用例快照
#   evals/ab-demo/b/  B 变体报告 json+md，b/cases-HHMMSS/ 同上（按运行时间戳分目录，重跑不覆盖旧证据）
#   evals/ab-demo/diff-*.md  回归对比报告（预期：B 退步若干项，对比退出码 1 属正常）
#
# 注意：key 只从环境读，脚本不写盘、不打印；每个变体 = 3 次生成 + 12 次 Judge 调用，
#       单个变体约 2-5 分钟，期间终端无输出属正常，别 Ctrl-C。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

OUT="evals/ab-demo"
VARIANT_B="evals/prompts/variant-b-weakened.md"

if [ -z "${EVAL_LLM_API_KEY:-}" ] && [ -z "${GLM_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "❌ 没检测到 API key：--live 需要真实调用模型。"
  echo "   请先在你自己的终端里 export（脚本不会把 key 写进任何文件）："
  echo "     export GLM_API_KEY=sk-xxx"
  echo "   然后重跑：bash evals/ab-demo.sh"
  exit 1
fi

mkdir -p "$OUT/a" "$OUT/b"

latest_json () { ls -t "$OUT/$1"/*.json 2>/dev/null | head -1; }

run_variant () {  # $1=目录名（a/b） $2...=传给 evaluate.py 的额外参数
  local dir="$1"; shift
  local extra="$*"
  echo ""
  echo "==================== 变体 $dir ===================="
  local exist; exist="$(latest_json "$dir")"
  if [ -n "$exist" ] && [ "${FORCE:-0}" != "1" ]; then
    echo "↷ 已有报告，跳过生成（要重跑用 FORCE=1）：$exist"
    ls -d "$OUT/$dir"/cases-* 2>/dev/null | sed 's/^/  历史快照: /'
    return 0
  fi
  echo "→ 现场生成 3 条正样本用例 + 12 条 Judge 打分，约 2-5 分钟，期间无输出属正常"
  rm -f _tmp/eval-live/*.md 2>/dev/null
  # shellcheck disable=SC2086
  python3 evals/evaluate.py --live --out "$OUT/$dir" $extra
  echo "（评测器退出码 $?；B 变体预期非 0，因为它就是故意写坏的）"

  # 现场生成的用例快照：_tmp 会被下次运行覆盖，按报告时分秒留档（每次运行一个目录，
  # 历史快照不覆盖——它们是对应那次报告的证据，测试与文档会引用）
  local stem snap
  stem="$(basename "$(latest_json "$dir")" .json 2>/dev/null)"
  if [ -z "$stem" ]; then
    echo "⚠️ 变体 $dir 没产出报告 json，--live 可能失败了"
    return 0
  fi
  snap="$OUT/$dir/cases-${stem##*-}"
  mkdir -p "$snap"
  cp _tmp/eval-live/*.md "$snap/" 2>/dev/null
  if [ -z "$(ls -A "$snap" 2>/dev/null)" ]; then
    rmdir "$snap" 2>/dev/null
    echo "⚠️ 没拿到变体 $dir 的用例快照（_tmp/eval-live 为空），报告仍可用于对比"
  else
    echo "  快照目录: $snap"
    ls "$snap" | sed 's/^/    /'
  fi
}

run_variant a ""
run_variant b "--sut-prompt $VARIANT_B"

A_JSON="$(latest_json a)"
B_JSON="$(latest_json b)"
if [ -z "$A_JSON" ] || [ -z "$B_JSON" ]; then
  echo ""
  echo "❌ A/B 报告不齐（A=${A_JSON:-无}，B=${B_JSON:-无}），--live 可能中途失败了。"
  echo "   看上面的报错；修好后直接重跑 bash evals/ab-demo.sh，已完成的那个变体会自动跳过。"
  exit 1
fi

echo ""
echo "==================== 回归对比 A → B ===================="
python3 evals/evaluate.py --diff "$A_JSON" "$B_JSON" --out "$OUT"
DIFF_RC=$?
echo ""
echo "对比退出码：$DIFF_RC（1 = 检出退步，正是本演示想看到的结果）"
echo "产物目录：$OUT/"
echo "  A 报告: $A_JSON"
echo "  B 报告: $B_JSON"
ls -t "$OUT"/diff-*.md 2>/dev/null | head -1 | sed 's/^/  对比报告: /'
