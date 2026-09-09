"""M4.3 认知缓存标记单测（研究线 M1/M2 落地）.

覆盖: 打标规则全分支 / 端点开关 / 幂等 / 原列表不可变 / 注入段 summary。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from llm_loop.cognitive.cache_tags import (
    PIN_TAGS,
    apply_cognitive_cache_tags,
    tagging_enabled_for,
)


class TestRules:
    def test_system_gets_rules(self):
        out = apply_cognitive_cache_tags([{"role": "system", "content": "x"}])
        assert out[0]["cache_tag"] == "rules" and "rules" in PIN_TAGS

    def test_tail_user_gets_goal_earlier_user_untagged(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "follow up"},
        ]
        out = apply_cognitive_cache_tags(msgs)
        assert out[3]["cache_tag"] == "goal"
        assert "cache_tag" not in out[1]  # 非尾部 user 不打（历史问题段，默认桶）

    def test_compact_marker_gets_summary(self):
        out = apply_cognitive_cache_tags(
            [
                {"role": "user", "content": "[上下文压缩] 早期摘要……"},
                {"role": "user", "content": "go"},
            ]
        )
        assert out[0]["cache_tag"] == "summary" and "summary" not in PIN_TAGS

    def test_injection_marker_gets_summary(self):
        out = apply_cognitive_cache_tags(
            [
                {"role": "user", "content": "[上下文注入·非新指令] 继续当前任务……"},
                {"role": "user", "content": "go"},
            ]
        )
        assert out[0]["cache_tag"] == "summary"

    def test_evidence_marker_user_and_assistant(self):
        msgs = [
            {"role": "assistant", "content": "见 evidence://abc 的记录"},
            {"role": "user", "content": "引用 evidence://def 验证（非尾部）"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "继续"},
        ]
        out = apply_cognitive_cache_tags(msgs)
        assert out[0]["cache_tag"] == "evidence"  # assistant 观察 → evidence
        assert out[1]["cache_tag"] == "evidence"  # 非尾部 user 引用 → evidence
        assert "evidence" in PIN_TAGS
        assert out[3]["cache_tag"] == "goal"  # 尾部 user 优先 goal（tail 优先于 evidence）

    def test_multimodal_content_untagged(self):
        out = apply_cognitive_cache_tags(
            [
                {"role": "user", "content": [{"type": "text", "text": "img"}]},
            ]
        )
        assert "cache_tag" not in out[0]


class TestSwitch:
    def test_default_off(self):
        assert not tagging_enabled_for("http://localhost:8901/v1", env={})

    def test_wildcard_match(self):
        assert tagging_enabled_for(
            "http://localhost:8901/v1", env={"COGNITIVE_TAG_ENDPOINTS": "http://localhost:8901*"}
        )

    def test_cloud_never_matched_by_default(self):
        assert not tagging_enabled_for(
            "https://api.glm.com/v1", env={"COGNITIVE_TAG_ENDPOINTS": "http://localhost:8901*"}
        )

    def test_none_url_off(self):
        assert not tagging_enabled_for(None, env={"COGNITIVE_TAG_ENDPOINTS": "*"})


class TestProperties:
    def test_idempotent(self):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
        once = apply_cognitive_cache_tags(msgs)
        assert apply_cognitive_cache_tags(once) == once

    def test_source_list_untouched(self):
        msgs = [{"role": "system", "content": "s"}]
        apply_cognitive_cache_tags(msgs)
        assert msgs[0] == {"role": "system", "content": "s"}

    def test_explicit_tag_respected(self):
        out = apply_cognitive_cache_tags(
            [{"role": "system", "content": "s", "cache_tag": "identity"}]
        )
        assert out[0]["cache_tag"] == "identity"
