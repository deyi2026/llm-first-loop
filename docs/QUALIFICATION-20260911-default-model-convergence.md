# DeepSeek Bootstrap Default Convergence Qualification — 2026-09-11

> **Verdict:** PASS / ADMIT rebuilt default-model migration.
> **Integration parent:** `integration/convergence-20260911@6df4749b9117944244c46d5f3a0e36c95c0a5515`.
> **Source evidence:** `8e589de58661188333234d003a72b011fd3d9ad4`.
> **Qualified implementation:** `c1932770afa43dd498a57eb8372c9217c2c58a41`.
> **Scope:** bootstrap/default naming and current configuration surfaces only; no live provider call, no provider-selection heuristic, no hidden routing change.

## 1. Why the source commit was rebuilt instead of cherry-picked alone

`8e589de` correctly changes the built-in fallback from `deepseek-v4-flash` to the official `deepseek-flash` name, but its committed patch changes only:

- `src/llm_loop/config.py`;
- `tests/unit/test_config.py`.

On the convergence parent, current operator-facing surfaces still advertised the old name in README, `.env.example`, configuration docs, real-LLM helper defaults and the Web no-registry fallback. Admitting only the two-file source patch would therefore create a new current-config authority split.

The convergence implementation preserves the source semantic core and synchronizes only current bootstrap/configuration surfaces. Historical benchmark/qualification documents are intentionally not rewritten.

## 2. Public provider fact

DeepSeek's official 2026-09-10 release announcement states that V4.1 Flash is available through the API as:

```text
model = deepseek-flash
```

Official source:

`https://www.deepseek.com/en/news/deepseek-v4-1-flash/`

The same announcement states that the former `deepseek-v4-flash` API name is temporarily routed to V4.1 Flash and that `deepseek-v4-pro` has a separately announced transition schedule. The convergence change therefore:

- makes `deepseek-flash` the new built-in/bootstrap name;
- continues honoring explicit old aliases supplied by an operator/registry;
- does not fabricate automatic migration of arbitrary explicit model references.

## 3. Sanitized local provider-registry provenance

The live local provider registry is operational/ignored state and is **not copied into this document or committed by this workline**.

Sanitized provenance at qualification time:

```text
tracked              false
providers.json bytes 5277
providers.json SHA256
bf463c72a8cfcd9261ed2d8c11d4f8b3d4ed37569bb4f678d50566e231e6be4e
```

Only non-secret typed facts were inspected:

- current provider set includes DeepSeek;
- DeepSeek registry default model is `deepseek-flash`;
- `deepseek-flash`, `deepseek-v4-flash`, and `deepseek-v4-pro` all remain resolvable registry entries at this snapshot;
- `deepseek-flash` is represented as context=1,000,000, multimodal=true, reasoning-capable=true, reasoning-control=`thinking_type`, send_tool_choice=false.

No API key, credential value, raw auth header, or private provider body is included in this qualification.

The current machine also has an explicit `LLM_MODEL` operator override, so the built-in fallback is not the live model-selection authority for the already-running instance. Its main effect is fresh bootstrap / configurations that intentionally omit `LLM_MODEL`.

## 4. Bootstrap ownership boundary

This workline does not add a programmatic provider/model chooser.

Existing precedence is preserved exactly:

```text
LLM_MODEL explicit
  > OPENSYGAI_DEEPSEEK_DEFAULT_MODEL explicit compatibility override
  > built-in DeepSeek bootstrap default (`deepseek-flash`)
```

The documentation now says explicitly that omitting `LLM_MODEL` means accepting the DeepSeek bootstrap default. Operators using another provider should set `LLM_MODEL` explicitly.

No hostname-based hard gate is added: a custom OpenAI-compatible endpoint may legitimately expose `deepseek-flash`, so the program must not infer semantic model availability merely from the endpoint domain.

## 5. Deterministic assembly checks

### 5.1 Registry-backed resolution

Against the sanitized current local registry, without a network request:

```text
resolve(`deepseek-flash`)        -> (`deepseek`, `deepseek-flash`)
resolve(`deepseek-v4-flash`)     -> (`deepseek`, `deepseek-v4-flash`)
```

### 5.2 Fresh L0 bootstrap without `providers.json`

With an isolated empty data directory and an explicit DeepSeek endpoint/model bootstrap tuple, `load_registry`/`build_engine` produces:

```text
provider     deepseek
model        deepseek-flash
registry     one synthesized DeepSeek provider
network I/O  none
```

This proves the new built-in name is valid in both the rich-registry path and the L0 fallback path.

## 6. Provider-visible invariant under explicit operator model

The migration changes only what happens when the model is omitted. With the same explicitly selected model on parent and candidate, actual `build_engine` provider surfaces are byte-equivalent:

```text
registered provider params
  parent/candidate: 62 tools
  SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37

runtime-health projected provider params
  parent/candidate: 60 tools
  SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8

Universal Prompt
  parent/candidate: 192 chars
  SHA ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e
```

No tool projection, prompt, cache semantics, reasoning policy, RG admission rule, or provider fallback selection is changed by this migration.

## 7. Qualification gates

```text
config/provider/factory/model/Web focused suite   PASS
complete changed-Python Ruff                      PASS
complete changed-Python py_compile                PASS
Pyright repository                                0 errors / 0 warnings / 0 informations
git diff --check                                  PASS
private addition scan                             0 findings
Git security hook on implementation               PASS
full pytest tests -q -m 'not real_llm' rerun      RC=0
```

### 7.1 First full-run performance outlier

The first full run had exactly one failure unrelated to the changed surface:

```text
tests/perf/test_build_leak_detection_bench.py::test_findings_path_within_budget
observed median = 5.142 ms
threshold       = 5.000 ms
```

No cache/config/provider file in this workline touches the detector. Mechanical attribution:

- `src/llm_loop/core/trace_leak/leak_detector.py` parent/candidate Git blob: exact match;
- the perf test parent/candidate Git blob: exact match;
- five interleaved parent/candidate measurements on the same machine were all approximately 1.065–1.084 ms, with no candidate regression;
- the unchanged full suite then reran successfully with explicit RC=0.

Disposition: transient machine-load noise. The 5ms gate is **not** weakened or modified to make this migration pass.

## 8. A.5 / LLM-First ruling

This is an operator bootstrap default, not a semantic runtime control machine.

- explicit user/operator model choice remains higher authority;
- the program does not infer task complexity or silently switch provider/model;
- old explicit aliases continue to resolve where the provider registry says they do;
- provider/model facts remain inspectable through the registry/model surfaces;
- rollback is a single default/configuration commit with no data migration.

## 9. Verdict

**PASS / ADMIT** `c193277` plus this qualification onto the single convergence ancestry.

The original two-file `8e589de` is preserved as source provenance but is not used as the complete integration unit because current configuration surfaces required synchronization.
