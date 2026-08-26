# -*- coding: utf-8 -*-
"""
提测统计脚本（单清单口径，与 acceptance-report SKILL.md 判定模型一致）
输入：story_changes JSON（fetch_changes.py 输出）+ 需求列表 JSON（MCP get_stories_or_tasks 输出）
输出：未按时提测需求清单（含首次进入"测试中"时间、提测日当天最晚流转、判定与备注）

用法（PowerShell）：
  python analyze_testing.py --changes s91_story_changes.json --stories s91_stories.json --tt-date 2026-07-07
  python analyze_testing.py --changes s91_story_changes.json --stories s91_stories.json --tt-date 2026-07-07 --out result.txt

参数：
  --changes    story_changes JSON（fetch_changes.py --type stories 的输出）
  --stories    需求列表 JSON：MCP get_stories_or_tasks 原始输出（自动兼容 {"data":[...]} / {"Story":[...]} / 纯数组），
               字段需含 id、name、owner、status、parent_id（拉取时 fields 至少包含这些）
  --tt-date    提测日，格式 YYYY-MM-DD（如 2026-07-07）
  --out        可选，结果写入 UTF-8 文件（控制台中文可能因 GBK 乱码，建议指定 --out 后用编辑器查看）

判定模型（用户确认）：
  1. 先排除父需求（存在其他需求 parent_id 指向它），父需求无提测要求
  2. 提测时间 = 需求状态流转历史中首次进入"测试中"的 created（story_changes 的 field_changes[].value_after_parsed 为中文状态名）
  3. 未按时提测 = 满足任一：
     ① 首次进入"测试中"时间 > 提测日（超期提测）
     ② 提测日当天有状态流转但最晚一条未到"测试中"（含误提测后转回实现中/其他且当天未再转回）
     ③ 整个迭代从未进入"测试中"（备注"从未提测"）
  4. "测试中→验收中"属正常前进，不算误提测
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True  # 禁止生成 __pycache__

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

STATUS_TESTING = "测试中"


def load_json(path):
    p = Path(path)
    if not p.exists():
        print(f"[error] {path} not found", file=sys.stderr)
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def load_story_list(data):
    """兼容 MCP 输出的多种结构：{"data": [...]} / {"Story": [...]} / {"data": {"Story": [...]}} / 纯数组"""
    if isinstance(data, dict):
        for key in ("data", "Story"):
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    return val
                if isinstance(val, dict):
                    for k2 in ("Story", "stories", "data"):
                        if k2 in val and isinstance(val[k2], list):
                            return val[k2]
        return []
    if isinstance(data, list):
        return data
    return []


def norm_story(story):
    """兼容 Story 包装结构"""
    return story.get("Story", story) if isinstance(story, dict) else story


def parse_created(ts):
    """story_changes 的 created 形如 2026-07-13 18:58:09 或带时区，返回 datetime"""
    if not ts:
        return None
    ts = str(ts).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[:19].replace("T", " "), fmt)
        except ValueError:
            continue
    return None


def status_changes(change):
    """从一条变更记录中提取 (时间, 变更前状态, 变更后状态)；兼容嵌套 field_changes 与扁平结构"""
    created = change.get("created")
    fields = change.get("field_changes")
    if isinstance(fields, list):
        for fc in fields:
            if fc.get("field") == "status" or fc.get("value_after_parsed") is not None:
                before = fc.get("value_before_parsed")
                after = fc.get("value_after_parsed")
                if after is not None:
                    return created, before, after
    else:
        field = change.get("field")
        if field == "status" or change.get("new_value") is not None:
            return created, change.get("old_value"), change.get("new_value")
    return None


def main():
    ap = argparse.ArgumentParser(description="未按时提测需求统计（单清单口径）")
    ap.add_argument("--changes", required=True, help="story_changes JSON")
    ap.add_argument("--stories", required=True, help="需求列表 JSON（MCP get_stories_or_tasks 输出）")
    ap.add_argument("--tt-date", required=True, help="提测日，格式 YYYY-MM-DD")
    ap.add_argument("--out", help="结果输出文件（UTF-8）")
    args = ap.parse_args()

    changes_data = load_json(args.changes)  # {story_id: [change...]}
    stories_raw = load_json(args.stories)
    stories = [norm_story(s) for s in load_story_list(stories_raw)]
    if not stories:
        print("[error] 需求列表为空，请检查 --stories 文件结构", file=sys.stderr)
        sys.exit(2)

    tt_date = datetime.strptime(args.tt_date, "%Y-%m-%d").date()

    # 1. 父需求识别：被其他需求 parent_id 引用的需求
    parent_ids = set()
    for s in stories:
        pid = s.get("parent_id")
        if pid:
            parent_ids.add(str(pid))
    parent_set = {str(s.get("id")) for s in stories if str(s.get("id")) in parent_ids}

    # 2. 解析每个需求的首次测试中时间 + 提测日当天最晚流转
    rows = []
    for s in stories:
        sid = str(s.get("id"))
        name = s.get("name") or ""
        owner = s.get("owner") or ""
        is_parent = sid in parent_set
        if is_parent:
            rows.append({"id": sid, "name": name, "owner": owner, "is_parent": True,
                         "first_testing": None, "judge": "父需求", "note": "父需求无提测要求，不计入"})
            continue

        first_testing = None
        first_author = None
        tt_day_transitions = []  # 提测日当天的 (时间, 前状态, 后状态)
        for change in changes_data.get(sid, []):
            parsed = status_changes(change)
            if not parsed:
                continue
            created, before, after = parsed
            dt = parse_created(created)
            if dt is None:
                continue
            after_s = (after or "").strip()
            if after_s == STATUS_TESTING and first_testing is None:
                first_testing = dt
                first_author = change.get("creator") or ""
            if dt.date() == tt_date:
                tt_day_transitions.append((dt, before, after))

        # 判定
        if first_testing is None:
            judge, note = "未按时", "从未提测"
        elif first_testing.date() > tt_date:
            judge, note = "未按时", "超期提测"
        elif tt_day_transitions:
            last = max(tt_day_transitions, key=lambda x: x[0])
            before_s = (last[1] or "").strip()
            after_s = (last[2] or "").strip()
            if after_s in ("测试中", "验收中", "已实现", "已完成"):
                # ⚠️ 当天最晚流转已到"测试中"或在其后正常前进（测试中→验收中→已实现），不算未按时
                judge, note = "按时", ""
            else:
                # 误提测转回（测试中→实现中/未开始/规划中）或当天未到测试中
                judge, note = "未按时", f"提测日当天最晚流转未到测试中（{before_s or '-'}→{after_s or '-'}）"
        else:
            judge, note = "按时", "提前提测" if first_testing.date() < tt_date else ""

        rows.append({"id": sid, "name": name, "owner": owner, "is_parent": False,
                     "first_testing": first_testing, "first_author": first_author,
                     "judge": judge, "note": note})

    # 3. 输出
    lines = []
    total = len(rows)
    parents = [r for r in rows if r["is_parent"]]
    overdue = [r for r in rows if r["judge"] == "未按时"]
    ontime = [r for r in rows if r["judge"] == "按时"]

    lines.append(f"需求总数：{total}（父需求 {len(parents)} 条已排除；纳入统计 {total - len(parents)} 条）")
    lines.append(f"未按时提测：{len(overdue)} 条 | 按时提测：{len(ontime)} 条")
    lines.append("")
    lines.append("=== 未按时提测需求清单 ===")
    lines.append("| 序号 | 需求ID | 标题 | 首次测试中时间 | 处理人 | 操作人 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, r in enumerate(sorted(overdue, key=lambda x: (x["first_testing"] or datetime.min)), 1):
        ft = r["first_testing"].strftime("%Y-%m-%d %H:%M:%S") if r["first_testing"] else "-"
        lines.append(f"| {i} | {r['id']} | {r['name']} | {ft} | {r['owner']} | {r['first_author'] or ''} | {r['note']} |")
    lines.append("")
    lines.append("=== 父需求（已排除）===")
    for r in parents:
        lines.append(f"- {r['id']} {r['name']}")

    output = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"[done] result saved -> {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
