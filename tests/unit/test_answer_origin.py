"""GPT 审计批次2（2026-08-28）: answer_origin 单一真相源——行为+接线测试.

核心: run_end_reason 显式信号（completed→model, 其余→program）写入 Message.metadata，
投影/记忆过滤 origin 优先，prefix 仅 legacy 兜底；程序反馈不携带 reasoning。
"""

from llm_loop.core.message import Message, MessageSource
from llm_loop.memory.extractor import MemoryExtractor


def _extractor() -> MemoryExtractor:
    # _build_history_text 为纯方法（无 self 依赖），绕过重型 __init__
    return object.__new__(MemoryExtractor)


class TestExtractorOriginFilter:
    """GPT 审计第三条: origin 过滤覆盖所有 role（含 system 原生程序反馈）。"""

    def test_program_system_message_filtered(self):
        # system 原生程序反馈（如 [停滞提醒]）——旧实现只挡 assistant，此处为修复核心
        msgs = [
            Message(role="user", content="用户提问", source=MessageSource.USER),
            Message(
                role="system",
                content="[停滞提醒] 检测到停滞",
                source=MessageSource.SYSTEM,
                metadata={"answer_origin": "program"},
            ),
        ]
        text = _extractor()._build_history_text(msgs)
        assert "停滞提醒" not in text
        assert "用户提问" in text

    def test_program_assistant_message_filtered(self):
        msgs = [
            Message(
                role="assistant",
                content="[LLM 调用异常] 连接超时",
                source=MessageSource.SYSTEM,
                metadata={"answer_origin": "program", "run_end_reason": "llm_error"},
            ),
        ]
        assert "LLM 调用异常" not in _extractor()._build_history_text(msgs)

    def test_legacy_prefix_assistant_fallback(self):
        # 老消息无 metadata——prefix 兜底仍生效
        msgs = [Message(role="assistant", content="[程序异常] xxx", source=MessageSource.USER)]
        assert "程序异常" not in _extractor()._build_history_text(msgs)

    def test_legacy_prefix_system_fallback(self):
        # 老的 system 原生反馈（无 metadata）同样被 prefix 兜底过滤
        msgs = [
            Message(role="system", content="[搜索空结果提醒] 无结果", source=MessageSource.SYSTEM)
        ]
        assert "搜索空结果提醒" not in _extractor()._build_history_text(msgs)

    def test_model_origin_and_normal_kept(self):
        # origin=model 的正常回答 + 完全普通的消息都保留
        msgs = [
            Message(role="user", content="问题A", source=MessageSource.USER),
            Message(
                role="assistant",
                content="正常回答内容",
                source=MessageSource.USER,
                metadata={"answer_origin": "model", "run_end_reason": "completed"},
            ),
        ]
        text = _extractor()._build_history_text(msgs)
        assert "正常回答内容" in text and "问题A" in text


class TestOriginWiring:
    """源码断言: 三处接线钉死（防回退）——engine 保存点/build 投影/reasoning 双保险。"""

    def test_engine_save_point_wiring(self):
        from pathlib import Path

        # B5-W4-01: origin 判定/元数据接线随收尾段迁 engine_services/run_finalizer.py
        # （_persist_turn 持久化半程）——接线锚点随新家（D-B5-10② 口径）
        src = (
            Path(__file__).resolve().parents[2]
            / "src/llm_loop/core/loop/engine_services/run_finalizer.py"
        ).read_text(encoding="utf-8")
        assert '_answer_origin = "model" if _run_end_reason == "completed" else "program"' in src
        assert "metadata=_origin_metadata" in src
        assert 'resp.reasoning_content and _answer_origin == "model"' in src

    def test_build_projection_wiring(self):
        from pathlib import Path

        # B4-CLOSE-01 步B: origin 投影条件随 scrub_provider_view 迁
        # stages/base_assembly.py（语义原样；锚点随新家）
        src = (
            Path(__file__).resolve().parents[2]
            / "src/llm_loop/core/prompt_build/stages/base_assembly.py"
        ).read_text(encoding="utf-8")
        assert '(m.metadata or {}).get("answer_origin") == "program"' in src
