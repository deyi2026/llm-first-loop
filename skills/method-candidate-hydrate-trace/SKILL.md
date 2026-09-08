---
name: method-candidate-hydrate-trace
description: Qwen3.8-27B 从离线网页绕路 episode 经 teacher exemplar 蒸馏出的实验 candidate；仅用于独立 transfer qualification，不代表已 promotion。适用于当前页面是 loading shell 且显式引用可能负责加载目标内容的脚本时，测试是否应先沿 hydration/provenance chain 而不是宽枚举；静态 HTML 或无关脚本是反例。
status: candidate
---
# Qwen-authored candidate (verbatim)

FRICTION: 7 calls for a 3–4 call job. Decisive evidence (app.js → article endpoint) was read last, after the answer was already found by enumeration; stale_search_snippet.txt and navigation.json were dead ends read in between.

DISCRIMINATOR: Step 1 already showed "loading shell + explicit `<script src=\"assets/app.js\">`". That signal means content is JS-hydrated: the data source lives in the script, not in static HTML, search snippets, or unrelated responses.

SHORTEST_PATH: read page.html → read assets/app.js → identify article API endpoint → read captured response for that endpoint. (3–4 calls; search_files(*) only if file layout unknown.)

GENERAL_RULE: On a JS-hydrated page, trace the hydration chain (shell → script → endpoint → captured response) before reading any other file; treat stale snippets and unrelated responses as distractors, not evidence.

COUNTEREXAMPLE: Server-rendered page (content already in HTML, no loading shell) — reading the script first is wasted; or data embedded in an inline blob (e.g. `__NEXT_DATA__`) where the source is in the HTML, not the JS. Rule applies only when the shell+script signal is present.

METHOD CARD
- Name: hydrate-trace
- Trigger: page.html is a loading shell with explicit script src
- Steps: 1) read shell 2) read the script 3) extract data endpoint 4) read captured response for that endpoint
- Stop: endpoint's captured response read
- Avoid: enumerating all files first; reading stale snippets / unrelated responses before the chain is traced
- Cost: 3–4 calls vs 7
