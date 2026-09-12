"""工具 Schema 索引化测试（EVO-d5db88d9）.

lazy 索引（体积最小） / 默认全量零回归 / get_tool_schema 按需读取完整 Schema。
直接装配 ToolRegistry + 假工具，零真实 LLM、零真实网络。
"""

import json

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry


class _FakeTool:
    def __init__(self, name: str, description: str = "描述" * 50):
        self.name = name
        self.description = description
        self.parameters = {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "参数a说明很长"},
                "b": {"type": "integer", "description": "参数b"},
            },
            "required": ["a"],
        }

    def execute(self, **kwargs):
        return f"{self.name}:ok"


class _FutureTool(_FakeTool):
    def __init__(self, *, compact_description: str | None = None):
        super().__init__("future_plugin_tool", "F" * 300)
        if compact_description is not None:
            self.compact_description = compact_description


def _reg() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file"))
    reg.register(_FakeTool("execute_command"))
    return reg


def test_schemas_default_full_zeroregress():
    """默认（lazy=False）全量注入：完整 description + 完整 parameters（零回归）."""
    reg = _reg()
    defs = reg.schemas()
    assert len(defs) == 2
    for d in defs:
        assert d["description"]  # 完整 description
        assert "参数a说明很长" in d["parameters"]["properties"]["a"]["description"]  # 完整参数说明


def test_schemas_lazy_index_compact():
    """lazy=True 精简索引：description 截断 200 + 参数骨架（无 description）."""
    reg = _reg()
    defs = reg.schemas(lazy=True)
    for d in defs:
        assert len(d["description"]) <= 200  # 截断
        prop = d["parameters"]["properties"]["a"]
        assert "description" not in prop  # 骨架无参数说明
        assert prop["type"] == "string"  # 保留类型
        assert d["parameters"]["required"] == ["a"]


def test_lazy_index_smaller_than_full():
    """lazy 索引体积显著小于全量（期望效果：上下文占用可控）."""
    reg = _reg()
    full_len = len(json.dumps(reg.schemas(), ensure_ascii=False))
    lazy_len = len(json.dumps(reg.schemas(lazy=True), ensure_ascii=False))
    assert lazy_len < full_len


def test_unmapped_future_tool_remains_callable_with_bounded_description():
    """No compact map entry may ever turn into tool hiding or parameter loss."""
    reg = ToolRegistry()
    reg.register(_FutureTool())
    row = reg.schemas(lazy=True)[0]
    assert row["name"] == "future_plugin_tool"
    assert row["description"] == "F" * 120
    assert row["parameters"]["properties"]["a"] == {"type": "string"}
    assert row["parameters"]["required"] == ["a"]


def test_tool_owned_compact_description_overrides_fallback_without_touching_full():
    reg = ToolRegistry()
    tool = _FutureTool(compact_description="compact contract")
    reg.register(tool)
    assert reg.schemas(lazy=True)[0]["description"] == "compact contract"
    assert reg.schemas()[0]["description"] == "F" * 300


def test_get_tool_schema_full():
    """get_tool_schema 返回指定工具完整 Schema（含参数说明）."""
    reg = _reg()
    tool = GetToolSchemaTool(reg)
    result = tool.execute(tool_name="read_file")
    assert result.status == ToolResultStatus.SUCCESS
    assert "read_file" in result.content
    assert "参数a说明很长" in result.content  # 完整参数说明可读


def test_get_tool_schema_not_found():
    """get_tool_schema 查询不存在工具 → 如实 FAILURE + 可用工具列表."""
    reg = _reg()
    tool = GetToolSchemaTool(reg)
    result = tool.execute(tool_name="no_such_tool")
    assert result.status == ToolResultStatus.FAILURE
    assert "工具不存在" in result.content
    assert "read_file" in result.content


def test_compact_contract_keeps_load_bearing_search_and_evidence_semantics():
    """P0: compact schema may drop prose, but not semantics that change how a call is interpreted."""
    reg = ToolRegistry()
    reg.register(_FakeTool("search_files"))
    reg.register(_FakeTool("read_evidence"))
    reg.register(_FakeTool("search_evidence"))
    defs = {row["name"]: row for row in reg.schemas(lazy=True)}

    assert "pattern+content" in defs["search_files"]["description"]
    assert "限定文件" in defs["search_files"]["description"]
    assert "path" in defs["search_files"]["description"]
    assert "stat" in defs["search_files"]["description"]
    assert "root 只接受搜索根目录" in defs["search_files"]["description"]
    assert "不能填文件路径" in defs["search_files"]["description"]
    assert "root=<父目录> + pattern=<文件名> + content=<关键词>" in defs["search_files"]["description"]
    assert "不执行内容搜索" in defs["search_files"]["description"]
    assert ".tmp-ci/.backup/.worktrees" in defs["search_files"]["description"]
    assert "显式 root" in defs["search_files"]["description"]
    assert "root" in defs["search_files"]["description"]
    assert "text_char" in defs["read_evidence"]["description"]
    assert "Unicode 字符" in defs["read_evidence"]["description"]
    assert "line" in defs["read_evidence"]["description"]
    assert "0-based" in defs["read_evidence"]["description"]
    assert "limit" in defs["read_evidence"]["description"]
    assert "4000" in defs["read_evidence"]["description"]
    assert "source 版本" in defs["read_evidence"]["description"]
    assert "当前任务" in defs["read_evidence"]["description"]


def test_compact_contract_keeps_versioned_edit_discovery_path():
    """Factory strict edit precondition must be discoverable without guessing parameter provenance."""
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file"))
    reg.register(_FakeTool("edit_file"))
    reg.register(_FakeTool("get_tool_schema"))
    defs = {row["name"]: row for row in reg.schemas(lazy=True)}

    assert "snapshot=true" in defs["read_file"]["description"]
    assert "snapshot_ref" in defs["read_file"]["description"]
    assert "必须" in defs["read_file"]["description"]
    assert "read_file(snapshot=true)" in defs["edit_file"]["description"]
    assert "expected_snapshot_ref" in defs["edit_file"]["description"]
    assert "参数/协议失败" in defs["get_tool_schema"]["description"]


def test_compact_contract_keeps_first_call_task_and_evidence_bounds():
    """First-call-ready facts must survive lazy projection instead of forcing avoidable retries."""
    reg = ToolRegistry()
    list_tool = _FakeTool("list_evidence")
    list_tool.parameters = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "FULL list limit prose"}},
    }
    search_tool = _FakeTool("search_evidence")
    search_tool.parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "FULL query prose"},
            "limit": {"type": "integer", "description": "FULL search limit prose"},
        },
        "required": ["query"],
    }
    update_tool = _FakeTool("task_update")
    update_tool.parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "blocked", "done", "failed", "cancelled"],
                "description": "FULL status prose",
            },
        },
    }
    for tool in (list_tool, search_tool, _FakeTool("task_create"), update_tool):
        reg.register(tool)
    defs = {row["name"]: row for row in reg.schemas(lazy=True)}

    assert "scope=recent/recovery" in defs["list_evidence"]["description"]
    assert "1..20" in defs["list_evidence"]["parameters"]["properties"]["limit"]["description"]
    assert "最多 20" in defs["search_evidence"]["parameters"]["properties"]["limit"]["description"]
    # Unreviewed parameter prose is still stripped from lazy transport.
    assert "description" not in defs["search_evidence"]["parameters"]["properties"]["query"]

    create_desc = defs["task_create"]["description"]
    assert "get_goal" in create_desc
    assert "不得猜" in create_desc
    assert "create_goal" in create_desc
    assert "同 Goal 已存在 task_id" in create_desc
    assert "acceptance 必填" in create_desc

    update_desc = defs["task_update"]["description"]
    assert "blocked_reason" in update_desc
    assert "evidence_refs" in update_desc
    assert "confirm=true" in update_desc
    status_desc = defs["task_update"]["parameters"]["properties"]["status"]["description"]
    assert "pending" in status_desc and "不能直接 done" in status_desc
    assert "in_progress" in status_desc and "blocked/failed" in status_desc


def test_compact_contract_keeps_skill_discovery_trigger_without_forcing_selection():
    """Failure replay: compacting must not erase the only cue that reusable Skills exist."""
    reg = ToolRegistry()
    reg.register(_FakeTool("skill_list"))
    reg.register(_FakeTool("skill_load"))
    defs = {row["name"]: row for row in reg.schemas(lazy=True)}

    list_desc = defs["skill_list"]["description"]
    load_desc = defs["skill_load"]["description"]
    assert "格式转换/PDF" in list_desc
    assert "特定站点抓取" in list_desc
    assert "execute_command" in list_desc
    assert "先用本工具发现候选" in list_desc
    assert "模型根据当前任务判断" in list_desc
    assert "skill_list 已发现" in load_desc
    assert "不代表" in load_desc and "适用于当前任务" in load_desc


def test_lazy_schema_preserves_current_machine_bounds_without_parameter_prose():
    """Lazy transport keeps current hard bounds as machine schema, not duplicate prose."""
    from llm_loop.tools.builtin.agent_message import AgentMessageTool
    from llm_loop.tools.builtin.schedule import ScheduleTool
    from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

    reg = ToolRegistry()
    reg.register(ScheduleTool())
    reg.register(AgentMessageTool(None))
    reg.register(SubAgentResultTool(None))
    defs = {row["name"]: row for row in reg.schemas(lazy=True)}

    schedule_message = defs["schedule"]["parameters"]["properties"]["message"]
    agent_content = defs["agent_message"]["parameters"]["properties"]["content"]
    wait_seconds = defs["subagent_result"]["parameters"]["properties"]["wait_seconds"]

    assert schedule_message == {"type": "string", "maxLength": 4000}
    assert agent_content == {"type": "string", "maxLength": 4000}
    assert wait_seconds == {"type": "number", "minimum": 0, "maximum": 30}
    assert all("description" not in spec for spec in (schedule_message, agent_content, wait_seconds))


def test_lazy_schema_does_not_copy_unreviewed_validator_keywords():
    """New validator kinds require an explicit provider/prefix audit before entering lazy."""
    spec = {
        "type": "string",
        "minLength": 2,
        "maxLength": 9,
        "pattern": "^[a-z]+$",
        "description": "high-tax prose",
    }
    assert ToolRegistry._lazy_schema_skeleton(spec) == {
        "type": "string",
        "maxLength": 9,
    }
