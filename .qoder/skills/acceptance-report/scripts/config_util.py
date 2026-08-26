# -*- coding: utf-8 -*-
"""
项目配置加载工具（供 acceptance-report/scripts 下脚本共享）。

从项目根 config/project.config.json 读取私有配置（workspace_id、测试人员名单等），
避免在脚本中硬编码。配置文件说明见 config/README.md。

查找顺序：
1. 脚本所在位置向上回溯（scripts → acceptance-report → skills → .qoder → 项目根）
2. 当前工作目录向上逐级查找 config/project.config.json
找不到时返回空 dict，调用方通过 CLI 参数显式传入（CLI 参数始终优先于配置）。
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

CONFIG_RELPATH = Path("config") / "project.config.json"


def _candidate_roots():
    """依次产出可能的项目根目录"""
    here = Path(__file__).resolve()
    if len(here.parents) >= 5:
        yield here.parents[4]  # scripts → acceptance-report → skills → .qoder → 根
    cwd = Path.cwd().resolve()
    yield cwd
    yield from cwd.parents


def load_project_config():
    """加载 config/project.config.json，找不到或解析失败时返回 {}"""
    for root in _candidate_roots():
        cfg_path = root / CONFIG_RELPATH
        if cfg_path.is_file():
            try:
                return json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[warn] parse {cfg_path} failed: {e}", file=sys.stderr)
                return {}
    return {}


def get_workspace_id(cli_value=None):
    """获取 TAPD workspace_id：CLI 参数 > 配置文件；均无则报错退出"""
    if cli_value:
        return str(cli_value)
    ws = load_project_config().get("tapd", {}).get("workspace_id", "")
    if ws and not ws.startswith("<"):
        return str(ws)
    print(
        "[error] workspace_id 未配置：请通过 --workspace 传入，"
        "或在 config/project.config.json 的 tapd.workspace_id 中配置（运行 /setup 可自动生成）",
        file=sys.stderr,
    )
    sys.exit(2)


def get_testers(cli_value=None):
    """获取测试人员名单：CLI 参数（逗号分隔）> 配置 team.testers；均无则返回空列表"""
    if cli_value:
        return [x.strip() for x in cli_value.split(",") if x.strip()]
    testers = load_project_config().get("team", {}).get("testers", [])
    return [t for t in testers if t and not str(t).startswith("<")]
