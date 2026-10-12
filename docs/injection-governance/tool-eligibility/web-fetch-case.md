# R8.6 benchmark case: `web_fetch` -> `web-fetch-fast`

Status: **R8.6/R8.7 historical benchmark; current fetch-path addendum applied 2026-09-06**

> **2026-09-06 current behavior:** supported Toutiao article URL shapes (`/article/<id>`, `/i<id>`, or `group_id=<id>`) are allowed through registry preflight and handled inside `WebFetchTool` by the protected deterministic `info/v2` adapter. Only Toutiao URL shapes not covered by that adapter retain the preflight typed-recovery route. This removes the former `web_fetch → skill_load → web_fetch` loop while preserving SSRF/redirect/DNS-rebinding protections. P1-B also retired recovery-driven tool visibility; recovery metadata is factual guidance, not a tool-selection grant.

## Current behavior

`web_fetch` already contains substantial internal fallback logic:

```text
httpx
-> rotate 3 browser/mobile user agents on 403/418/429
-> detect JS shell
-> curl fallback with the UA pool
-> extraction / pagination / Evidence projection
```

R8.7 keeps the raw failure body factual; matched next-step guidance is emitted only by the typed recovery policy, so generic and typed routes do not compete.

The implementation therefore should not be characterized as a naive fetcher. Its low aggregate success is primarily a **site/context-routing problem**.

## Current observed domain outcomes

From the point-in-time event-log snapshot frozen at `2026-08-30T23:37:03+08:00`, **25 calls can be attributed to the public URL domains below**. One additional `web_fetch` record is a `blocked` private-target/security-policy case and is intentionally excluded from the public-domain success table. Event logs continue growing after this cutoff, so these counts are evidence for the audit decision, not a future fixed-point assertion.

| Domain | Calls | Success |
|---|---:|---:|
| `github.com` | 3 | 3 |
| `docs.xai.ac.cn` | 2 | 2 |
| `docs.bigmodel.cn` | 1 | 1 |
| `blog.csdn.net` | 1 | 1 |
| `www.weather.com.cn` | 1 | 1 |
| `inco.ai` | 1 | 1 |
| `www.toutiao.com` | 5 | 0 |
| `m.toutiao.com` | 3 | 0 |
| `zhuanlan.zhihu.com` | 2 | 0 |
| `manual.nssurge.com` | 4 | 0 |
| `nssurge.com` | 1 | 0 |
| `openai.com` | 1 | 0 |

The important signal is not merely `web_fetch` aggregate success. It is that some domains are healthy while other failure classes are highly predictable.

## Existing Skill

`skills/web-fetch-fast/SKILL.md` already contains the specialized knowledge needed for article/anti-bot sites:

- Toutiao `info/v2` path;
- mobile-UA curl path;
- `RENDER_DATA` extraction;
- avoid repeating the same failed `web_fetch`;
- alternate source/browser fallback.

The former lifecycle disconnect was resolved by moving the deterministic site adapter inside the protected `web_fetch` execution path. The Skill now teaches when to fetch/stop/recover; it does not provide a raw-curl bypass.

## Proposed routing

### Preflight

```text
URL is ordinary/static and no known bad-domain evidence
-> web_fetch

URL is a supported Toutiao article shape
-> web_fetch
-> protected internal site adapter (`info/v2`)

Toutiao host is known but URL shape is not supported by the adapter
-> preflight typed recovery
-> skill_load("web-fetch-fast") / alternate source as guidance
```

### Failure recovery

```text
403 / 418
-> anti_bot_or_access_reject
-> do not repeat web_fetch
-> web-fetch-fast or web_search

404
-> url_not_found
-> do not change UA/browser first
-> web_search canonical/current URL

429
-> rate_limited
-> no same-round retry
-> alternate source; backoff only if same origin is required

JS shell after internal curl fallback
-> do not repeat web_fetch
-> web-fetch-fast

timeout / 5xx
-> one bounded retry may be valid
-> after repeat failure switch path/source

SSRF/private-target block
-> stop and report policy boundary
-> never turn "disable the safety policy" into the normal recovery recommendation
```

## Runtime-health caveat

The Skill currently documents Chromium as its final fallback, but the current audit runtime reports:

```text
python playwright: MISSING
chromium executable: MISSING
```

Therefore the implementation must intersect Skill guidance with runtime health. Today the Skill's earlier curl/API/JSON paths remain useful, while its Chromium fallback is not executable in this environment.

## Target result shape

The model should receive a short matched recovery record such as:

```text
[tool recovery]
failure_class=javascript_shell_or_anti_bot
retry_same_tool=false
preferred_skill=web-fetch-fast
next=skill_load:web-fetch-fast
```

It should not receive the complete domain decision tree on every request.

## Acceptance fixture set

At minimum test:

1. ordinary GitHub/document URL -> `web_fetch` remains eligible;
2. supported Toutiao article URL -> registry reaches `WebFetchTool` and the protected `toutiao_info_v2` adapter; unsupported Toutiao path -> typed preflight recovery;
3. HTTP 404 -> canonical-URL search, no same-URL retry;
4. HTTP 403 after internal UA exhaustion -> no same-tool retry;
5. timeout -> one bounded retry allowed;
6. SSRF block -> no unsafe bypass recommendation;
7. Skill recommends unavailable Chromium -> runtime-health layer marks that fallback unavailable;
8. no matched rule -> generic truthful failure remains available.


## R8.7 applied behavior

- **Historical R8.7 behavior:** all Toutiao hosts were preflight-routed before `WebFetchTool.execute()`. **Current behavior (2026-09-06):** adapter-supported article URLs bypass that broad preflight and execute the protected `toutiao_info_v2` fast path; unsupported Toutiao paths still receive typed preflight recovery.
- Ordinary URL tasks still expose `web_fetch`; unrelated tasks do not.
- 403/418, 404, 429, JS-shell, timeout/5xx, and security-block results map to typed recovery classes.
- `ToolResult.recovery_advice` is rendered as the matched recovery recommendation and copied to `Message.metadata.tool_recovery`; under P1-B it does not change the provider-callable tool surface.
- If no typed rule matches, legacy truthful generic guidance remains available.
- Playwright/Chromium are not installed by this phase; the current Playwright tools are runtime-quarantined instead of being advertised as a working fallback.
