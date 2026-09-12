"""模型 ID 双命名归一（catalog 层）测试 — 2026-09-12 v0.6.14.

覆盖:
- canonical_model_id: LM Studio 路径形态 / HF cache 形态 / 已规范形态 / 空串
- ProviderRegistry.resolve: 别名形态 ↔ 注册形态 双向解析（限定 provider 与跨 provider）
- 歧义防护: 规范形态命中多条注册 → 拒绝并列出候选（fail-loud, 不静默选错）
- catalog_summary: 同物理模型双注册只展示一行完整规格 + 一行别名指向（去重）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.llm.model_ids import canonical_model_id, is_alias_form
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec

PATH_FORM = str(Path.home() / ".lmstudio" / "models" / "ornith-ai" / "Ornith-1.5-35B-A3B-MLX")
HF_FORM = "ornith-ai/Ornith-1.5-35B-A3B-MLX"


def _registry(models: dict[str, ModelSpec]) -> ProviderRegistry:
    return ProviderRegistry(providers={
        "lmstudio": ProviderSpec(
            id="lmstudio", base_url="http://127.0.0.1:8901/v1", api_key_env="X",
            models=models,
        ),
    })


class TestCanonicalModelId:
    def test_lmstudio_path_to_hf(self):
        assert canonical_model_id(PATH_FORM) == HF_FORM

    def test_hf_form_unchanged(self):
        assert canonical_model_id(HF_FORM) == HF_FORM

    def test_hf_cache_form(self):
        assert canonical_model_id("models--Qwen--Qwen3.5-35B-A3B") == "Qwen/Qwen3.5-35B-A3B"

    def test_plain_id_unchanged(self):
        assert canonical_model_id("gpt-4o") == "gpt-4o"

    def test_empty(self):
        assert canonical_model_id("") == ""

    def test_is_alias_form(self):
        assert is_alias_form(PATH_FORM)
        assert not is_alias_form(HF_FORM)
        assert not is_alias_form("gpt-4o")


class TestResolveAliasFallback:
    def test_qualified_path_form_resolves_to_hf_registered(self):
        reg = _registry({HF_FORM: ModelSpec()})
        assert reg.resolve(f"lmstudio/{PATH_FORM}") == ("lmstudio", HF_FORM)

    def test_qualified_hf_form_resolves_to_path_registered(self):
        reg = _registry({PATH_FORM: ModelSpec()})
        assert reg.resolve(f"lmstudio/{HF_FORM}") == ("lmstudio", PATH_FORM)

    def test_bare_path_form_resolves_cross_provider(self):
        reg = _registry({HF_FORM: ModelSpec()})
        assert reg.resolve(PATH_FORM) == ("lmstudio", HF_FORM)

    def test_exact_match_still_wins_without_ambiguity(self):
        reg = _registry({HF_FORM: ModelSpec(), PATH_FORM: ModelSpec()})
        # exact 命中优先于归一, 不因别名歧义而失败
        assert reg.resolve(f"lmstudio/{PATH_FORM}") == ("lmstudio", PATH_FORM)
        assert reg.resolve(f"lmstudio/{HF_FORM}") == ("lmstudio", HF_FORM)

    def test_third_form_with_dual_registration_fails_loud(self):
        # HF 与路径两形态都注册时, 第三种形态(HF cache)归一后命中两条 → 拒绝并列候选
        reg = _registry({HF_FORM: ModelSpec(), PATH_FORM: ModelSpec()})
        with pytest.raises(ValueError, match="多个注册条目"):
            reg.resolve("models--ornith-ai--Ornith-1.5-35B-A3B-MLX")

    def test_dual_registration_exact_bare_still_resolves(self):
        # 双注册不破坏 exact 裸引用: 各自命中各自条目
        reg = _registry({HF_FORM: ModelSpec(), PATH_FORM: ModelSpec()})
        assert reg.resolve(PATH_FORM) == ("lmstudio", PATH_FORM)

    def test_bare_hf_form_with_unknown_provider_prefix_resolves(self):
        # "ornith-ai/X" 含 "/" 但 pid 未知 → 整串按裸名解析
        reg = _registry({HF_FORM: ModelSpec()})
        assert reg.resolve(HF_FORM) == ("lmstudio", HF_FORM)

    def test_unknown_model_lists_candidates_with_canonical(self):
        reg = _registry({HF_FORM: ModelSpec()})
        with pytest.raises(ValueError, match="候选"):
            reg.resolve("lmstudio/nope")


class TestCatalogDedupe:
    def test_dual_registration_dedupes_in_summary(self):
        reg = _registry({
            HF_FORM: ModelSpec(context=131072),
            PATH_FORM: ModelSpec(context=131072),
        })
        summary = reg.catalog_summary()
        lines = summary.splitlines()
        full_lines = [ln for ln in lines if ln.strip().startswith(f"- {HF_FORM}:")]
        alias_lines = [ln for ln in lines if ln.strip().startswith(f"- {PATH_FORM} →")]
        # 完整规格行只出现一次, 另一条以 alias 行呈现（同一物理模型展示去重）
        assert len(full_lines) == 1
        assert len(alias_lines) == 1 and f"→ alias of {HF_FORM}" in alias_lines[0]


# ---- 短名桥接（唯一匹配守卫）: HF/路径形态 → 注册短名 ----

def test_loose_key_basic():
    from llm_loop.llm.model_ids import loose_key
    assert loose_key(HF_FORM) == "ornith-1.5-35b-a3b-mlx"
    assert loose_key(PATH_FORM) == "ornith-1.5-35b-a3b-mlx"
    assert loose_key("ornith-1.5-35b-a3b-mlx") == "ornith-1.5-35b-a3b-mlx"


class TestShortnameBridge:
    def test_scoped_hf_form_bridges_to_shortname(self):
        reg = _registry({"ornith-1.5-35b-a3b-mlx": ModelSpec(), "qwen3.8-27b-cog": ModelSpec()})
        assert reg.resolve(f"lmstudio/{HF_FORM}") == ("lmstudio", "ornith-1.5-35b-a3b-mlx")
        assert reg.resolve(f"lmstudio/{PATH_FORM}") == ("lmstudio", "ornith-1.5-35b-a3b-mlx")

    def test_bare_forms_bridge_cross_provider(self):
        reg = _registry({"ornith-1.5-35b-a3b-mlx": ModelSpec()})
        assert reg.resolve(HF_FORM) == ("lmstudio", "ornith-1.5-35b-a3b-mlx")

    def test_ambiguity_rejected(self):
        reg = ProviderRegistry(providers={
            "p1": ProviderSpec(id="p1", base_url="http://a/v1", api_key_env="X",
                               models={"ornith-1.5-35b-a3b-mlx": ModelSpec()}),
            "p2": ProviderSpec(id="p2", base_url="http://b/v1", api_key_env="X",
                               models={"Ornith-1.5-35B-A3B-MLX": ModelSpec()}),
        })
        with pytest.raises(ValueError, match="全限定名"):
            reg.resolve(HF_FORM)

    def test_no_match_fails_loud_with_candidates(self):
        reg = _registry({"qwen3.8-27b-cog": ModelSpec()})
        with pytest.raises(ValueError, match="不在注册表中"):
            reg.resolve(HF_FORM)
