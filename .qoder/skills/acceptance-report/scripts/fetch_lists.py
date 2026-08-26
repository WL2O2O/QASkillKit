# -*- coding: utf-8 -*-
"""
通用 TAPD 需求/缺陷列表拉取脚本（stories / bugs）
供 analyze_testing.py / analyze_bugs.py 提供标准 JSON 输入。
支持多迭代合并（主迭代 Sprint{版本号} + 平行迭代 hotfix-s{版本号}）。

用法（PowerShell）：
  python fetch_lists.py --type stories --iterations "{主迭代ID},{hotfix迭代ID}" --out s91_stories.json
  python fetch_lists.py --type bugs --iterations "{主迭代ID},{hotfix迭代ID}" --out s91_bugs.json

参数：
  --type        stories | bugs（必选）
  --iterations  逗号分隔迭代 ID，多个迭代自动合并去重（必选）
  --out         输出 JSON 路径（必选），格式 {"data": [...]}
  --workspace   TAPD workspace_id，默认读取 config/project.config.json 的 tapd.workspace_id
  --fields      可选覆盖拉取字段（默认已含分析所需全部字段）

token 自动从 ~/.qoder/mcp.json 的 mcpServers.mcp-server-tapd.env.TAPD_ACCESS_TOKEN 读取（勿硬编码）。
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

DEFAULT_FIELDS = {
    "stories": "id,name,status,owner,developer,created,modified,parent_id,children_id,priority_label,iteration_id",
    # ⚠️ bugs 默认字段已包含验收报告所需的 TAPD 自定义字段映射：
    #   custom_field_one   → 开发负责人（开发人员）
    #   custom_field_three → 缺陷 类型（常规缺陷/UI错误/修改引入缺陷等）
    #   custom_field_five  → 缺陷产生原因（开发填写的原因分析）
    "bugs": "id,title,status,reporter,current_owner,created,modified,severity,story_id,priority_label,resolution,custom_field_one,custom_field_three,custom_field_five",
}


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


def extract_item(item):
    """解嵌套：TAPD 列表接口返回 {"Story": {...}} / {"Bug": {...}} 包装结构"""
    if isinstance(item, dict):
        for key in ("Story", "Bug"):
            inner = item.get(key)
            if isinstance(inner, dict) and inner:
                return inner
    return item


def fetch_list(entity, iterations, token, workspace, fields):
    """按迭代分页拉取列表，合并去重；输出与 MCP 返回结构一致 {"data": [...]}"""
    seen = {}
    for iter_id in iterations:
        page = 1
        while True:
            params = {
                "workspace_id": workspace,
                "iteration_id": iter_id,
                "fields": fields,
                "limit": 100,
                "page": page,
            }
            data = http_get(f"{BASE_URL}/{entity}", params, token)
            if not data or data.get("status") != 1:
                break
            items = data.get("data", []) or []
            if not items:
                break
            for it in items:
                key = extract_item(it).get("id")
                if key is not None:
                    seen[str(key)] = it
            if len(items) < 100:
                break
            page += 1
        print(f"  iteration {iter_id} done (累计 {len(seen)})", file=sys.stderr)
    return list(seen.values())


def main():
    ap = argparse.ArgumentParser(description="TAPD 需求/缺陷列表拉取（多迭代合并）")
    ap.add_argument("--type", required=True, choices=["stories", "bugs"], help="stories | bugs")
    ap.add_argument("--iterations", required=True, help="逗号分隔迭代 ID（主迭代+hotfix 迭代合并）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    ap.add_argument("--workspace", default=None, help="默认读取 config/project.config.json")
    ap.add_argument("--fields", default=None, help="覆盖默认拉取字段")
    args = ap.parse_args()
    args.workspace = get_workspace_id(args.workspace)

    iterations = [x.strip() for x in args.iterations.split(",") if x.strip()]
    if not iterations:
        print("[error] --iterations 为空", file=sys.stderr)
        sys.exit(2)

    token = load_token()
    fields = args.fields if args.fields else DEFAULT_FIELDS[args.type]
    result = fetch_list(args.type, iterations, token, args.workspace, fields)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"data": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {len(result)} {args.type} saved -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
