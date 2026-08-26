# -*- coding: utf-8 -*-
r"""
为缺陷列表查询 bug→story 关联关系（TAPD Relations API）。
TAPD Bug.story_id 字段常为空（Sprint88 中 105/110 条为空），
缺陷与需求的真实关联存储在 /relations 表中（source_type=bug, target_type=story），
需逐条查询每个 bug_id 获取关联。

用法（PowerShell）：
  python fetch_relations.py --bug-ids "{缺陷ID1},{缺陷ID2}" --out _tmp\s88_bug_story_map.json
  python fetch_relations.py --bug-ids-file _tmp\s88_bug_ids.txt --out _tmp\s88_bug_story_map.json

参数：
  --bug-ids      逗号分隔缺陷 ID 列表（与 --bug-ids-file 二选一）
  --bug-ids-file 缺陷 ID 文本文件，每行一个（与 --bug-ids 二选一）
  --out          输出 JSON 路径（必选），格式 {"bug_id": "story_id", ...}，无关联时为 null
  --workspace    TAPD workspace_id，默认读取 config/project.config.json 的 tapd.workspace_id

token 自动从 ~/.qoder/mcp.json 的 mcpServers.mcp-server-tapd.env.TAPD_ACCESS_TOKEN 读取。

输出说明：
  - 找到关联的 bug：{"{缺陷ID}": "{需求ID}", ...}
  - 无关联的 bug：{"{缺陷ID}": null, ...}
  - 关联到多条 story 的 bug（罕见）：{"{缺陷ID}": ["{需求ID1}", "{需求ID2}"], ...}
    输出 key 的 value 为数组而非字符串
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from config_util import get_workspace_id

sys.dont_write_bytecode = True

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://api.tapd.cn"
MCP_CONFIG = Path.home() / ".qoder" / "mcp.json"


def load_token():
    """从 mcp.json 读取 TAPD_ACCESS_TOKEN"""
    if not MCP_CONFIG.exists():
        print(f"[error] {MCP_CONFIG} not found", file=sys.stderr)
        sys.exit(2)
    try:
        cfg = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[error] read {MCP_CONFIG} failed: {e}", file=sys.stderr)
        sys.exit(2)
    env = cfg.get("mcpServers", {}).get("mcp-server-tapd", {}).get("env", {})
    token = env.get("TAPD_ACCESS_TOKEN", "")
    if not token:
        print("[error] TAPD_ACCESS_TOKEN not found in mcp.json", file=sys.stderr)
        sys.exit(2)
    return token


def http_get(url, params, token, retries=3):
    """带重试的 GET 请求，Bearer Header 鉴权"""
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}")
    req.add_header("Authorization", f"Bearer {token}")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [retry {attempt + 1}] GET {url} failed: {e}", file=sys.stderr)
    return None


def fetch_bug_story_relations(bug_ids, token, workspace):
    """
    逐条查询每个 bug_id 的 relations，返回 {bug_id: story_id | None | [story_ids]} 映射。
    查询方式：GET /relations?workspace_id=X&source_type=bug&source_id={bid}&limit=10
    返回 target_type=story 的记录即为关联需求。
    """
    result = {}
    total = len(bug_ids)
    for idx, bid in enumerate(bug_ids, 1):
        params = {
            "workspace_id": workspace,
            "source_type": "bug",
            "source_id": bid,
            "limit": 10,
        }
        data = http_get(f"{BASE_URL}/relations", params, token)
        stories = []
        if data and data.get("status") == 1:
            items = data.get("data", []) or []
            for item in items:
                rel = item.get("Relation", item)
                if rel.get("target_type") == "story":
                    stories.append(str(rel["target_id"]))
        if not stories:
            result[str(bid)] = None
        elif len(stories) == 1:
            result[str(bid)] = stories[0]
        else:
            # 罕见情况：一个缺陷关联多个需求，保留数组
            result[str(bid)] = stories
        if idx % 10 == 0 or idx == total:
            linked = sum(1 for v in result.values() if v is not None)
            print(f"  relations progress {idx}/{total} (linked={linked})", file=sys.stderr)
    return result


def read_ids(csv_or_file):
    """优先按文件读取（每行一个 ID），否则按逗号分隔"""
    p = Path(csv_or_file)
    if p.exists():
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [x.strip() for x in csv_or_file.split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser(description="TAPD bug→story Relations 查询")
    ap.add_argument("--bug-ids", help="逗号分隔缺陷 ID 列表")
    ap.add_argument("--bug-ids-file", help="缺陷 ID 文本文件（每行一个）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    ap.add_argument("--workspace", default=None, help="默认读取 config/project.config.json")
    args = ap.parse_args()
    args.workspace = get_workspace_id(args.workspace)

    if not args.bug_ids and not args.bug_ids_file:
        print("[error] 需提供 --bug-ids 或 --bug-ids-file", file=sys.stderr)
        sys.exit(2)
    ids = read_ids(args.bug_ids_file if args.bug_ids_file else args.bug_ids)
    if not ids:
        print("[error] bug ID 列表为空", file=sys.stderr)
        sys.exit(2)

    token = load_token()
    print(f"查询 {len(ids)} 个 bug 的关联关系...", file=sys.stderr)
    mapping = fetch_bug_story_relations(ids, token, args.workspace)

    # 统计结果
    linked = sum(1 for v in mapping.values() if v is not None)
    unlinked = len(mapping) - linked
    print(f"[done] 关联={linked}, 无关联={unlinked}", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] mapping saved -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()