# -*- coding: utf-8 -*-
"""
缺陷统计脚本（与 acceptance-report SKILL.md 缺陷口径一致）
输入：bug_changes JSON（fetch_changes.py 输出）+ 缺陷列表 JSON（fetch_lists.py 输出）
输出：
  ① 开发人员缺陷统计汇总（开发人员、缺陷数量、缺陷产生原因、主要问题类型、建议改进方向）
  ② 缺陷明细列表（缺陷类型、开发人员、缺陷产生原因、关联需求、标题）
  ③ 缺陷分析总结
  ④ 版本遗留问题候选（状态未变更缺陷）
  ⑤ 优化类 / 无修复人清单

用法（PowerShell）：
  python -B analyze_bugs.py --bugs s91_bugs.json --changes s91_bug_changes.json
  python -B analyze_bugs.py --bugs s91_bugs.json --changes s91_bug_changes.json --bug-story-map s91_bug_story_map.json --exclude 测试A,测试B --out result.txt

参数：
  --bugs           缺陷列表 JSON（fetch_lists.py 输出），需含 id,title,status,
                   custom_field_one（开发负责人）, custom_field_three（缺陷类型）, custom_field_five（缺陷产生原因）
  --changes        bug_changes JSON（fetch_changes.py --type bugs 的输出）
  --bug-story-map  可选，bug→story 关联映射 JSON（fetch_relations.py 输出），用于补全 story_id 为空的关联需求
  --exclude        测试工程师名单（逗号分隔），默认读取 config/project.config.json 的 team.testers
  --out            可选，结果写入 UTF-8 文件

统计口径（用户确认）：
  1. 开发人员优先取 TAPD 自定义字段 custom_field_one（开发负责人），为空时回退到状态变更修复人
  2. 修复人 = 最后一次 in_progress→resolved 或 reopened→resolved 状态变更的 author
  3. 最后修复人是测试人员时回溯更早的非测试修复人
  4. 剔除 title 以【优化】开头的优化类缺陷（不计入缺陷统计）
  5. 不统计状态为"已关闭"（closed）的缺陷
  6. 不统计缺陷类型为"历史遗留缺陷"的缺陷（custom_field_three 含"历史遗留缺陷"）
  7. 被拒绝（rejected）/转需求/设计如此/无流转的缺陷无修复人，不计入开发人员统计
"""

import argparse
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

from config_util import get_testers

sys.dont_write_bytecode = True

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

RESOLVED_WORDS = {"已解决", "resolved", "Resolved"}
IN_PROGRESS_WORDS = {"进行中", "in_progress", "In Progress"}
REOPENED_WORDS = {"重新打开", "reopened", "Reopened"}
LEGACY_STATUS = {"new", "reopened", "in_progress", "新", "重新打开", "进行中"}
CLOSED_STATUS = {"closed", "已关闭", "Closed"}

HISTORICAL_DEFECT_TYPE = "历史遗留缺陷"  # 缺陷类型为"历史遗留缺陷"的不计入统计


# 相似原因合并规则（按优先级匹配，先匹配先合并）
# 格式：(合并后标签, [关键词列表])
CAUSE_MERGE_RULES = [
    ("UI/文案错误", ["UI文案", "UI错误", "文案错误", "文案遗漏", "文案细节", "文案没注意",
                      "文案未调整", "UI细节", "ui还原", "UI遗漏", "未仔细检查文案"]),
    ("组件复用问题", ["组件复用", "组件bug", "公共组件"]),
    ("需求/细节遗漏", ["需求遗漏", "遗漏需求", "遗漏细节", "开发遗漏", "逻辑细节遗漏",
                       "遗漏了", "遗漏细节"]),
    ("精度/金额问题", ["精度", "金额元和符号"]),
    ("校验逻辑问题", ["校验", "等号", "校验未"]),
    ("原型理解偏差", ["原型图", "原型上", "原型混乱", "原型未体现"]),
    ("场景检查不足", ["场景检查", "检查漏了", "没测到", "测试遗漏"]),
    ("接口调用问题", ["接口传参", "接口调用", "Feign", "传参丢失"]),
    ("数据/权限问题", ["权限", "数据权限", "过滤条件", "显隐"]),
    ("兼容性问题", ["兼容", "ios", "H5"]),
    ("交互理解偏差", ["需求理解", "需求判断", "产品和ui不统一", "交互没仔细看", "前端交互"]),
    ("刷新/时机问题", ["刷新时机", "刷新"]),
    ("打印/备注问题", ["打印", "备注", "预包装码"]),
    ("规格/换算问题", ["换算", "规格", "多单位"]),
    ("历史遗留", ["历史遗留", "历史bug", "历史文案"]),
    ("已知问题未跟进", ["已知问题"]),
]


def merge_cause(cause_text):
    """将缺陷产生原因合并到相似分类"""
    if not cause_text:
        return "未填写"
    for label, keywords in CAUSE_MERGE_RULES:
        for kw in keywords:
            if kw in cause_text:
                return label
    # 无法匹配，返回截断原文（20字符）
    return cause_text[:20] if len(cause_text) > 20 else cause_text
CAUSE_SUGGESTION_MAP = {
    "精度": "金额计算涉及精度必须使用 decimal 类型",
    "组件复用": "组件复用前检查所有使用场景的差异",
    "UI": "全局 UI 规范（如金额符号、小数位数）需统一",
    "文案": "文案需在开发完成后逐页核对，避免遗漏或错别字",
    "需求遗漏": "需求评审时逐条确认功能点，开发时对照需求 checklist",
    "需求判断": "需求评审时逐条确认功能点，开发时对照需求 checklist",
    "接口传参": "接口调用前梳理完整参数列表，联调时验证所有参数",
    "原型图": "原型图标注不清时主动与产品确认，避免猜测实现",
    "校验": "校验逻辑需单独测试，尤其注意边界值与等号场景",
    "供应商": "涉及供应商结算等新功能，需梳理完整字段和展示规则",
    "精度丢失": "金额计算涉及精度必须使用 decimal 类型",
    "场景检查": "多场景覆盖需在自测阶段逐一验证",
    "兼容": "H5/iOS/Android 兼容性需在真机测试",
    "换算": "多规格/多单位场景需梳理完整换算逻辑",
    "公共组件": "公共组件使用前确认参数是否满足当前场景",
    "权限": "权限控制需在测试用例中覆盖所有角色",
    "边界值": "测试用例需覆盖权限控制、边界值（如负数、0）",
    "已知问题": "已知问题需在系统记录并跟踪",
    "字段对齐": "前后端字段对齐需仔细确认",
    "交互": "交互细节需仔细阅读原型",
    "测试遗漏": "测试用例需覆盖权限控制、边界值（如负数、0）",
    "打印": "打印、备注等细节需对齐业务规则",
    "日期": "日期组件快捷选项需覆盖所有业务场景",
    "核销": "核销类功能需覆盖全链路测试",
    "离线": "离线场景需在真实离线环境下验证",
}

# 缺陷类型→改进建议映射
TYPE_SUGGESTIONS = {
    "常规缺陷": "加强代码自测，提测前完成功能自检checklist",
    "低级缺陷": "加强代码review与自测，提测前逐条验证核心路径",
    "重复修改缺陷": "建立修改影响范围评估机制，修改前梳理关联模块",
    "修改引入缺陷": "加强回归测试，修改关联模块时评估影响范围，补充回归用例",
    "UI错误": "加强UI走查，开发完成后逐页面核对设计稿",
    "用例未执行": "开发自测需覆盖全部用例，提测前确认用例执行情况",
    "需求优化": "需求评审阶段充分讨论边界场景与交互细节",
    "历史遗留缺陷": "排期修复历史遗留问题，避免技术债累积",
    "环境问题": "规范环境管理，测试前确认环境配置一致性",
}


def load_json(path):
    p = Path(path)
    if not p.exists():
        print(f"[error] {path} not found", file=sys.stderr)
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def load_bug_list(data):
    """兼容 MCP 输出多种结构：{"data":[...]} / {"Bug":[...]} / {"data":{"Bug":[...]}} / 纯数组"""
    if isinstance(data, dict):
        for key in ("data", "Bug"):
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    return val
                if isinstance(val, dict):
                    for k2 in ("Bug", "bugs", "data"):
                        if k2 in val and isinstance(val[k2], list):
                            return val[k2]
        return []
    if isinstance(data, list):
        return data
    return []


def norm_bug(bug):
    return bug.get("Bug", bug) if isinstance(bug, dict) else bug


def status_events(changes):
    """从 bug_changes 提取状态变更事件列表 [(author, created, before, after)]，兼容扁平与嵌套结构"""
    events = []
    for ch in changes:
        fields = ch.get("field_changes")
        if isinstance(fields, list):
            for fc in fields:
                if fc.get("field") == "status" or fc.get("value_after_parsed") is not None:
                    events.append((ch.get("author"), ch.get("created"),
                                   fc.get("value_before_parsed"), fc.get("value_after_parsed")))
        elif ch.get("field") == "status" or ch.get("new_value") is not None:
            events.append((ch.get("author"), ch.get("created"),
                           ch.get("old_value"), ch.get("new_value")))
    return events


def match_status(value, words):
    v = (value or "").strip()
    return v in words


def find_fixer(events, exclude_set):
    """最后一次 in_progress/reopened→resolved 的 author；若为测试人员则回溯更早的非测试修复人"""
    resolved_events = []
    for author, created, before, after in events:
        if match_status(after, RESOLVED_WORDS) and (
            match_status(before, IN_PROGRESS_WORDS) or match_status(before, REOPENED_WORDS)
        ):
            resolved_events.append((created or "", author))
    if not resolved_events:
        return None
    resolved_events.sort(key=lambda x: x[0])
    for _, author in reversed(resolved_events):
        if author not in exclude_set:
            return author
    return resolved_events[-1][1]


def extract_cause_list(causes):
    """合并相似缺陷产生原因，按频次排序，返回摘要字符串"""
    if not causes:
        return "未填写"
    counter = Counter()
    for c in causes:
        if c:
            label = merge_cause(c)
            counter[label] += 1
    parts = []
    for label, cnt in counter.most_common():
        if cnt > 1:
            parts.append(f"{label}（{cnt}次）")
        else:
            parts.append(f"{label}（1次）")
    return "、".join(parts) if parts else "未填写"


def extract_type_keywords(defect_types):
    """汇总缺陷类型关键词（去重），如"精度计算、UI对齐、组件复用"""
    if not defect_types:
        return "未分类"
    seen = set()
    keywords = []
    for dt in defect_types:
        for t in (dt or "").split("|"):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                keywords.append(t)
    return "、".join(keywords) if keywords else "未分类"


def generate_suggestions(defect_types, causes):
    """基于缺陷类型和具体原因生成编号建议列表"""
    suggestions = []
    seen = set()
    # 1. 从缺陷产生原因匹配精准建议
    for c in causes:
        if not c:
            continue
        for keyword, suggestion in CAUSE_SUGGESTION_MAP.items():
            if keyword in c and suggestion not in seen:
                suggestions.append(suggestion)
                seen.add(suggestion)
                break
    # 2. 从缺陷类型补充建议
    type_suggestion_map = {
        "UI错误": "加强UI走查，开发完成后逐页面核对设计稿",
        "低级缺陷": "加强代码 review 与自测，提测前逐条验证核心路径",
        "用例未执行": "开发自测需覆盖全部用例，提测前确认用例执行情况",
        "修改引入缺陷": "建立修改影响范围评估机制，修改前梳理关联模块",
        "环境问题": "规范环境管理，测试前确认环境配置一致性",
    }
    for dt in defect_types:
        for t in (dt or "").split("|"):
            t = t.strip()
            if t in type_suggestion_map:
                s = type_suggestion_map[t]
                if s not in seen:
                    suggestions.append(s)
                    seen.add(s)
    # 3. 兜底
    if not suggestions:
        suggestions.append("加强常规自测与代码 review")
    return "；".join(f"{i}. {s}" for i, s in enumerate(suggestions[:5], 1))


def main():
    ap = argparse.ArgumentParser(description="缺陷修复人统计与 TAPD 自定义字段分析")
    ap.add_argument("--bugs", required=True, help="缺陷列表 JSON（fetch_lists.py 输出）")
    ap.add_argument("--changes", required=True, help="bug_changes JSON（fetch_changes.py 输出）")
    ap.add_argument("--bug-story-map", default=None, help="bug→story 关联映射 JSON（fetch_relations.py 输出）")
    ap.add_argument("--exclude", default=None,
                    help="测试人员名单（逗号分隔），默认读取 config/project.config.json 的 team.testers")
    ap.add_argument("--out", help="结果输出文件（UTF-8）")
    args = ap.parse_args()

    bugs = [norm_bug(b) for b in load_bug_list(load_json(args.bugs))]
    changes_data = load_json(args.changes)
    exclude_set = set(get_testers(args.exclude))

    # 加载 bug→story 关联映射（用于补全 story_id 为空的关联需求）
    bug_story_map = {}
    if args.bug_story_map:
        try:
            bug_story_map = load_json(args.bug_story_map)
        except Exception:
            pass

    # --- 分类数据结构 ---
    closed_bugs = []               # 已关闭缺陷（不参与统计）
    optimization = []              # 【优化】类
    historical_defects = []        # 历史遗留缺陷类型（不参与统计）
    legacy = []                    # 版本遗留候选
    no_fixer = []                  # 无修复人（被拒/转需求/无流转）
    analyzed = []                  # 参与统计的缺陷：(developer, bug_detail_dict)

    for b in bugs:
        bid = str(b.get("id"))
        title = b.get("title") or ""
        status = (b.get("status") or "").strip()
        events = status_events(changes_data.get(bid, []))
        fixer = find_fixer(events, exclude_set)

        # 读取 TAPD 自定义字段
        dev_owner = (b.get("custom_field_one") or "").strip()      # 开发负责人
        defect_type = (b.get("custom_field_three") or "").strip()   # 缺陷类型
        cause_text = (b.get("custom_field_five") or "").strip()     # 缺陷产生原因
        story_id = (b.get("story_id") or "").strip()                # 关联需求

        # 用 bug_story_map 补全 story_id
        if not story_id and bug_story_map:
            mapped = bug_story_map.get(bid)
            if mapped:
                story_id = str(mapped).strip()

        # 判定开发人员：优先 custom_field_one → 状态变更修复人
        developer = dev_owner if dev_owner else (fixer or "")

        bug_detail = {
            "id": bid,
            "title": title,
            "status": status,
            "developer": developer,
            "defect_type": defect_type,
            "cause": cause_text,
            "story_id": story_id,
            "fixer": fixer or "",
        }

        # ① 剔除【优化】类
        if title.strip().startswith("【优化】"):
            optimization.append(bug_detail)
            continue

        # ② 剔除已关闭
        if status in CLOSED_STATUS:
            closed_bugs.append(bug_detail)
            continue

        # ③ 剔除历史遗留缺陷类型（custom_field_three 含"历史遗留缺陷"）
        if HISTORICAL_DEFECT_TYPE in defect_type:
            historical_defects.append(bug_detail)
            continue

        # ④ 版本遗留（未进入 resolved）
        if status in LEGACY_STATUS:
            legacy.append(bug_detail)
            continue

        # ⑤ 无修复人（被拒/转需求/无流转）
        if not fixer:
            no_fixer.append(bug_detail)
            continue

        # ⑥ 计入统计
        analyzed.append(bug_detail)

    # --- 输出 ---
    lines = []

    # ========== 一、开发人员缺陷统计汇总表 ==========
    lines.append("=" * 80)
    lines.append("=== 一、开发人员缺陷统计汇总（不统计已关闭缺陷，剔除【优化】类与历史遗留缺陷类型）===")
    lines.append(f"（统计口径：取 TAPD 自定义字段 custom_field_one（开发负责人）为开发人员，")
    lines.append(f" 为空时回退到状态变更修复人；剔除测试工程师验证操作记录；")
    lines.append(f" 标题以【优化】开头的优化类不计入；已关闭缺陷不计入；")
    lines.append(f' 缺陷类型为"历史遗留缺陷"的不计入；')
    lines.append(f" 被拒绝/转需求/设计如此类缺陷未计入；合计 {len(analyzed)} 条）")
    lines.append("")

    # 按开发人员分组
    dev_groups = defaultdict(list)
    for bug in analyzed:
        dev = bug["developer"] if bug["developer"] else "未分配"
        dev_groups[dev].append(bug)

    lines.append("| 开发人员 | 缺陷数量 | 缺陷产生原因 | 主要问题类型 | 建议改进方向 |")
    lines.append("|---|---|---|---|---|")
    total_analyzed = 0
    for dev, bug_list in sorted(dev_groups.items(), key=lambda x: -len(x[1])):
        cnt = len(bug_list)
        causes = [b["cause"] for b in bug_list if b["cause"]]
        types = [b["defect_type"] for b in bug_list if b["defect_type"]]
        cause_list = extract_cause_list(causes)
        type_keywords = extract_type_keywords(types) if types else "未分类"
        suggestions = generate_suggestions(types, causes)
        lines.append(f"| {dev} | {cnt} | {cause_list} | {type_keywords} | {suggestions} |")
        total_analyzed += cnt
    lines.append(f"| **合计** | **{total_analyzed}** | | | |")
    lines.append("")

    # ========== 二、缺陷明细列表（按开发人员分组） ==========
    lines.append("=" * 80)
    lines.append("=== 二、缺陷明细（按开发人员分组，不统计已关闭缺陷）===")
    lines.append("")

    for dev, bug_list in sorted(dev_groups.items(), key=lambda x: -len(x[1])):
        lines.append(f"【{dev} - {len(bug_list)}条】")
        lines.append("| 序号 | 缺陷类型 | 缺陷产生原因 | 关联需求 | 标题 |")
        lines.append("|---|---|---|---|---|")
        for idx, bug in enumerate(bug_list, 1):
            dt = bug["defect_type"] or "-"
            cause = (bug["cause"] or "-")[:50]  # 截断过长内容
            sid = bug["story_id"] if bug["story_id"] else "-"
            title = bug["title"][:60]
            lines.append(f"| {idx} | {dt} | {cause} | {sid} | {title} |")
        lines.append("")

    # ========== 三、缺陷分析总结 ==========
    lines.append("=" * 80)
    lines.append("=== 三、缺陷分析总结 ===")
    lines.append("")

    # 缺陷类型分布
    all_types = Counter()
    for bug in analyzed:
        for t in (bug["defect_type"] or "").split("|"):
            t = t.strip()
            if t:
                all_types[t] += 1
    lines.append(f"1. 缺陷类型分布（共 {len(analyzed)} 条）：")
    if all_types:
        for t, cnt in all_types.most_common():
            pct = cnt / len(analyzed) * 100 if analyzed else 0
            lines.append(f"   - {t}：{cnt} 条（{pct:.1f}%）")
    else:
        lines.append("   （缺陷类型字段未填写，待人工补充）")
    lines.append("")

    # 缺陷产生原因归类（基于关键词）
    lines.append(f"2. 缺陷产生原因归类：")
    cause_summary = Counter()
    for bug in analyzed:
        c = bug["cause"]
        if c:
            cause_summary[c[:30]] += 1
    if cause_summary:
        for text, cnt in cause_summary.most_common():
            pct = cnt / len(analyzed) * 100 if analyzed else 0
            lines.append(f"   - {text}：{cnt} 条（{pct:.1f}%）")
    else:
        lines.append("   （缺陷产生原因字段未填写）")
    lines.append("")

    # 全局改进建议
    lines.append("3. 全局改进建议：")
    all_causes = [bug["cause"] for bug in analyzed if bug["cause"]]
    all_types_set = [bug["defect_type"] for bug in analyzed if bug["defect_type"]]
    global_suggestions = generate_suggestions(all_types_set, all_causes)
    lines.append(global_suggestions)
    lines.append("")

    # 重点开发人员提示
    lines.append(f"4. 缺陷 Top 开发人员：")
    for dev, bug_list in sorted(dev_groups.items(), key=lambda x: -len(x[1]))[:5]:
        cnt = len(bug_list)
        pct = cnt / len(analyzed) * 100 if analyzed else 0
        lines.append(f"   - {dev}：{cnt} 条（占比 {pct:.1f}%）")
    lines.append("")

    # ========== 四、已关闭缺陷（不参与统计） ==========
    lines.append("=" * 80)
    lines.append(f"=== 四、已关闭缺陷（不参与统计，共 {len(closed_bugs)} 条）===")
    for bug in closed_bugs:
        lines.append(f"- {bug['id']} {bug['title'][:60]}")
    lines.append("")

    # ========== 五、历史遗留缺陷类型（不参与统计） ==========
    lines.append("=" * 80)
    lines.append(f"=== 五、历史遗留缺陷类型（不进统计，共 {len(historical_defects)} 条）===")
    for bug in historical_defects:
        lines.append(f"- {bug['id']} [{bug['status']}] {bug['title'][:60]}")
    lines.append("")

    # ========== 六、版本遗留问题候选 ==========
    lines.append("=" * 80)
    lines.append(f"=== 六、版本遗留问题候选（状态未进入已解决，共 {len(legacy)} 条）===")
    for bug in legacy:
        lines.append(f"- {bug['id']} [{bug['status']}] {bug['title'][:60]}")
    lines.append("")

    # ========== 七、优化类 ==========
    lines.append("=" * 80)
    lines.append(f"=== 七、优化类（不计入缺陷统计，共 {len(optimization)} 条）===")
    for bug in optimization:
        lines.append(f"- {bug['id']} {bug['title'][:60]}")
    lines.append("")

    # ========== 八、无修复人 ==========
    lines.append("=" * 80)
    lines.append(f"=== 八、无修复人（被拒/转需求/无状态流转，共 {len(no_fixer)} 条）===")
    for bug in no_fixer:
        lines.append(f"- {bug['id']} {bug['title'][:60]}")

    output = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"[done] result saved -> {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
