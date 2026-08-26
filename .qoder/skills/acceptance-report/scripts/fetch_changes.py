# -*- coding: utf-8 -*-
"""
通用 TAPD 状态变更历史拉取脚本（story_changes / bug_changes）
MCP (mcp-server-tapd) 未封装这两个接口，需直连 TAPD OpenAPI。

用法（PowerShell）：
  python fetch_changes.py --type stories --ids "{需求ID1},{需求ID2}" --out s91_story_changes.json
  python fetch_changes.py --type stories --ids-file story_ids.txt --out s91_story_changes.json
  python fetch_changes.py --type bugs --ids-file bug_ids.txt --out s91_bug_changes.json

参数：
  --type       stories | bugs（必选）
  --ids        逗号分隔 ID 列表（与 --ids-file 二选一）
  --ids-file   ID 文本文件，每行一个（与 --ids 二选一）
  --out        输出 JSON 路径（必选）
  --workspace  TAPD workspace_id，默认读取 config/project.config.json 的 tapd.workspace_id
  --all-fields story_changes 不按 change_field=status 过滤（默认只取状态流转，数据量小）

token 自动从 ~/.qoder/mcp.json 的 mcpServers.mcp-server-tapd.env.TAPD_ACCESS_TOKEN 读取。
输出为 {story_id 或 bug_id: [变更记录...]} 的 JSON，变更记录保留原始结构（嵌套 WorkitemChange 或扁平两种结构均原样保存）。
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from config_util import get_workspace_id

sys.dont_write_bytecode = True  # 禁止生成 __pycache__

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://api.tapd.cn"
MCP_CONFIG = Path.home() / ".qoder" / "mcp.json"


def load_token():
    """从 mcp.json 读取 TAPD_ACCESS_TOKEN，避免硬编码"""
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
    """带重试的 GET 请求，返回解析后的 JSON；Authorization 用 Bearer Header（URL 参数方式会 422）"""
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


def read_ids(csv_or_file):
    """优先按文件读取（每行一个 ID），否则按逗号分隔"""
    p = Path(csv_or_file)
    if p.exists():
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [x.strip() for x in csv_or_file.split(",") if x.strip()]


def extract_item(item):
    """兼容 WorkitemChange / BugChange / 扁平 三种返回结构"""
    if isinstance(item, dict):
        for key in ("WorkitemChange", "BugChange"):
            inner = item.get(key)
            if isinstance(inner, dict) and inner:
                return inner
    return item


def fetch_story_changes(ids, token, workspace, status_only=True):
    """story_changes 支持 story_id 逗号分隔批量查询，每批最多 10 个"""
    all_changes = {}
    for i in range(0, len(ids), 10):
        batch = ids[i:i + 10]
        params = {"workspace_id": workspace, "story_id": ",".join(batch), "limit": 100}
        if status_only:
            params["change_field"] = "status"
        page = 1
        while True:
            data = http_get(f"{BASE_URL}/story_changes", {**params, "page": page}, token)
            if not data or data.get("status") != 1:
                break
            items = data.get("data", []) or []
            if not items:
                break
            for item in items:
                wc = extract_item(item)
                sid = wc.get("story_id")
                if sid:
                    all_changes.setdefault(str(sid), []).append(wc)
            if len(items) < 100:
                break
            page += 1
        print(f"  story batch {i // 10 + 1} done ({len(batch)} ids)", file=sys.stderr)
    return all_changes


def fetch_bug_changes(ids, token, workspace):
    """bug_changes 逐条查询（接口不支持批量）"""
    all_changes = {}
    for idx, bid in enumerate(ids, 1):
        page = 1
        collected = []
        while True:
            data = http_get(
                f"{BASE_URL}/bug_changes",
                {"workspace_id": workspace, "bug_id": bid, "limit": 100, "page": page},
                token,
            )
            if not data or data.get("status") != 1:
                break
            items = data.get("data", []) or []
            if not items:
                break
            for item in items:
                collected.append(extract_item(item))
            if len(items) < 100:
                break
            page += 1
        all_changes[str(bid)] = collected
        if idx % 10 == 0 or idx == len(ids):
            print(f"  bug_changes progress {idx}/{len(ids)}", file=sys.stderr)
    return all_changes


def main():
    ap = argparse.ArgumentParser(description="TAPD story_changes/bug_changes 状态变更历史拉取")
    ap.add_argument("--type", required=True, choices=["stories", "bugs"], help="stories | bugs")
    ap.add_argument("--ids", help="逗号分隔 ID 列表")
    ap.add_argument("--ids-file", help="ID 文本文件（每行一个）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    ap.add_argument("--workspace", default=None, help="默认读取 config/project.config.json")
    ap.add_argument("--all-fields", action="store_true", help="story_changes 不按 status 过滤")
    args = ap.parse_args()
    args.workspace = get_workspace_id(args.workspace)

    if not args.ids and not args.ids_file:
        print("[error] 需提供 --ids 或 --ids-file", file=sys.stderr)
        sys.exit(2)
    ids = read_ids(args.ids_file if args.ids_file else args.ids)
    if not ids:
        print("[error] ID 列表为空", file=sys.stderr)
        sys.exit(2)

    token = load_token()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.type == "stories":
        result = fetch_story_changes(ids, token, args.workspace, status_only=not args.all_fields)
    else:
        result = fetch_bug_changes(ids, token, args.workspace)

    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {len(result)} items saved -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
