"""M3 <think> 标签流式剥离测试（场景 B 适配）."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from llm_loop.llm.client import LLMClient


def _simulate(client, chunks):
    """模拟流式 content delta 序列（驱动 client 的剥离逻辑）. """
    texts, reasonings = [], []
    for chunk in chunks:
        client._think_buf = getattr(client, "_think_buf", "") + chunk
        _in_think = getattr(client, "_in_think", False)
        while True:
            if not _in_think:
                idx = client._think_buf.find("<think>")
                if idx == -1:
                    normal = client._think_buf
                    client._think_buf = ""
                    if normal:
                        texts.append(normal)
                    break
                normal = client._think_buf[:idx]
                client._think_buf = client._think_buf[idx:]
                if normal:
                    texts.append(normal)
                _in_think = True
            else:
                end = client._think_buf.find("</think>")
                if end == -1:
                    think = client._think_buf
                    client._think_buf = ""
                    if think:
                        reasonings.append(think)
                    break
                think = client._think_buf[:end]
                client._think_buf = client._think_buf[end + len("</think>"):]
                _in_think = False
                if think:
                    reasonings.append(think)
        client._in_think = _in_think
    return "".join(texts), "".join(reasonings)


class TestThinkStrip:
    def test_single_think(self):
        c = LLMClient(api_key="x", base_url="x", model="x")
        texts, reas = _simulate(c, ["<think>思考内容</think>回答"])
        assert texts == "回答"
        assert "思考内容" in reas

    def test_think_split_across_deltas(self):
        c = LLMClient(api_key="x", base_url="x", model="x")
        texts, reas = _simulate(c, ["<think>第一部", "分思考</think>", "正文"])
        assert texts == "正文"
        assert "第一部分思考" in reas

    def test_think_unclosed_at_end(self):
        c = LLMClient(api_key="x", base_url="x", model="x")
        texts, reas = _simulate(c, ["<think>未闭合思考"])
        assert texts == ""
        assert "未闭合思考" in reas  # 兜底进 reasoning

    def test_no_think(self):
        c = LLMClient(api_key="x", base_url="x", model="x")
        texts, reas = _simulate(c, ["普通回答内容"])
        assert texts == "普通回答内容"
        assert reas == ""

    def test_multiple_think_blocks(self):
        c = LLMClient(api_key="x", base_url="x", model="x")
        texts, reas = _simulate(c, ["<think>思考1</think>正文1<think>思考2</think>正文2"])
        assert texts == "正文1正文2"
        assert "思考1" in reas and "思考2" in reas

    def test_normal_then_think(self):
        c = LLMClient(api_key="x", base_url="x", model="x")
        texts, reas = _simulate(c, ["前言<think>思考</think>后语"])
        assert texts == "前言后语"
        assert "思考" in reas
