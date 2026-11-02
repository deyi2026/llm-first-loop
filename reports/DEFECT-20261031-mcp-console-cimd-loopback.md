# 缺陷报告：CIMD 客户端校验对 native 应用 loopback 临时端口做裸字符串比较，导致 ChatGPT/Codex 无法完成 OAuth 授权

| 项 | 内容 |
|---|---|
| 报告编号 | DEFECT-20261031-MCPCONSOLE-CIMD-LOOPBACK |
| 报告日期 | 2026-10-31 |
| 产品 | MCP Console（macOS 桌面版，`com.mcpconsole.desktop`） |
| 版本 | `0.1.537`（CFBundleVersion）；构建号 2026-10-13 13:58:47（原构建串按可读日期时间格式转写，数字未改） |
| 部署形态 | 本地服务 `127.0.0.1:8790`，Cloudflare named tunnel `mcp-console` → `https://mcp.llmfirstloop.com` |
| 故障端点 | `GET /oauth/authorize`（`issuer=https://mcp.llmfirstloop.com`） |
| 严重级别 | 高（互操作性阻断，功能不可用；**非安全漏洞**，方向是"过度限制"而非"过度放行"） |
| 类型 | 协议符合性缺陷（RFC 9700 §2.1/§4.1.3、RFC 8252 §7.3、CIMD 草案 §4.2） |
| 影响面 | 所有走 CIMD 且以系统临时端口接收回跳的 native 客户端：ChatGPT/Codex、Codex CLI、以及其他按 RFC 8252 实现的本地客户端 |

**一句话版本（可直接转述）**：授权服务器把 CIMD 文档里的 `redirect_uris` 当成裸字符串做全集比较，没有实现 RFC 9700/RFC 8252 对 native 应用 loopback 重定向"端口可变"的豁免；而 native 客户端的端口由操作系统临时分配，必然与文档中登记的无端口形式不同，因此每次授权 100% 被拒。

---

## 1. 摘要

用户从 ChatGPT 添加连接器 `https://mcp.llmfirstloop.com/mcp`，授权页返回：

```
invalid CIMD client: redirect_uri is not declared by the CIMD metadata document
```

请求参数中 `client_id=https://chatgpt.com/oauth/codex/client.json`、`redirect_uri=http://127.0.0.1:55049/callback`。该 CIMD 文档声明的 `redirect_uris` 为 `["http://127.0.0.1/callback","http://localhost/callback"]`（无端口）。除端口外，请求值与声明值在 scheme、host、path、query 上完全一致。

按 RFC 9700 §2.1 与 §4.1.3，授权服务器在比对已登记 redirect URI 时"必须使用精确字符串匹配，**native 应用 localhost 重定向 URI 的端口号除外**"，且"必须允许可变端口号（见 RFC 8252 §7.3）"。当前实现未落实该例外，把"端口不同"误判为"未声明"。

## 2. 影响

1. **功能不可用**：ChatGPT 侧连接器授权无法完成，无法取得 `mcp`/`offline_access` 令牌。
2. **客户端侧无绕法**：回跳端口由客户端在发起授权前向操作系统申请，用户不可指定；这是 RFC 8252 的推荐做法，属客户端正确行为。
3. **DCR 不是退路**：AS 虽提供 `registration_endpoint`，但该客户端使用 CIMD，不会走动态注册。
4. **故障面已精确隔离**：公网链路正常——AS 元数据与授权页均可从公网访问（`200`）；`/mcp` 未带凭据返回 `401` 并给出 `www-authenticate: ... resource_metadata="…/.well-known/oauth-protected-resource"`（符合 MCP 授权发现要求，实测）。问题只出在 authorize 的 redirect 校验。

## 3. 环境与前置

- macOS（Apple Silicon），MCP Console 桌面版运行中，本地端口 `8790`（见 `~/.mcp-console/mcp.toml`：`host=127.0.0.1`、`port=8790`、`publicBaseUrl=https://mcp.llmfirstloop.com`、`tunnelMode=named`）。
- 无需登录、无需通道 token 即可复现：校验发生在渲染授权页之前，错误在 HTML 中直接返回。

## 4. 复现步骤

### 4.1 UI 路径

1. 在 ChatGPT 中添加连接器，URL 填 `https://mcp.llmfirstloop.com/mcp`；
2. 跳转授权页，页面显示 `Client: https://chatgpt.com/oauth/codex/client.json`、`Redirect: http://127.0.0.1:55049/callback`；
3. 页面正文报错 `invalid CIMD client: redirect_uri is not declared by the CIMD metadata document`，无授权表单。

### 4.2 最小命令行复现（不依赖 ChatGPT，跳过隧道直连本地服务）

两条命令只有 `redirect_uri` 的端口不同：

```bash
# ① 无端口 → 通过（返回授权表单）
curl -sS -G 'http://127.0.0.1:8790/oauth/authorize' \
  -d 'response_type=code' \
  -d 'client_id=https://chatgpt.com/oauth/codex/client.json' \
  -d 'redirect_uri=http://127.0.0.1/callback' \
  -d 'scope=mcp offline_access' -d 'state=probe' \
  -d 'code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM' \
  -d 'code_challenge_method=S256'

# ② 带临时端口 → 失败（返回错误页）
#    仅把 redirect_uri 换成 http://127.0.0.1:55049/callback，其余参数完全相同
```

判定方式：响应 HTML 中出现 `invalid CIMD client` 即为被拒。同一组命令把 host 换成 `https://mcp.llmfirstloop.com` 结果一致。

### 4.3 实测矩阵（`client_id=https://chatgpt.com/oauth/codex/client.json`，PKCE S256，`state=probe`）

| # | redirect_uri | 结果 | 说明 |
|---|---|---|---|
| 1 | `http://127.0.0.1/callback` | ✅ 授权页 | 与声明值逐字节相同 |
| 2 | `http://localhost/callback` | ✅ 授权页 | 同上 |
| 3 | `http://127.0.0.1:55049/callback` | ❌ invalid CIMD client | **真实故障场景**：仅端口不同 |
| 4 | `http://localhost:55049/callback` | ❌ invalid CIMD client | 同上，host 为 `localhost` |
| 5 | `http://127.0.0.1:80/callback` | ❌ invalid CIMD client | `:80` 与省略端口在 URI 语义上等价，仍被拒 → 无端口规范化 |
| 6 | `HTTP://127.0.0.1/callback` | ❌ invalid CIMD client | scheme 大小写未归一（URI scheme 大小写不敏感，RFC 3986 §3.1） |
| 7 | `http://127.0.0.1/callback/` | ❌ invalid CIMD client | 路径尾斜杠不放宽（合理，保留） |
| 8 | `https://127.0.0.1:55049/callback` | ❌ invalid CIMD client | 未声明的 https 变体被拒（合理，保留） |
| 9 | `http://127.0.0.1.evil.example/callback` | ❌ invalid CIMD client | **重要**：host 严格相等，非后缀/包含匹配，不存在开放重定向风险 |

所有响应 HTTP 状态码均为 `200`（错误与正常页同为 200，仅正文不同），详见 §10.1。

## 5. 期望行为 vs 实际行为

| | 期望 | 实际 |
|---|---|---|
| #3（`127.0.0.1` + 任意端口） | 通过。RFC 8252 §7.3 的 "loopback **IP** redirect URI" 明文情形，RFC 9700 §4.1.3 要求"必须允许可变端口" | 拒绝 |
| #4（`localhost` + 任意端口） | 通过。RFC 9700 §2.1 的措辞是 "localhost redirection URIs of native apps" | 拒绝 |
| #1/#2（无端口） | 通过 | 通过 |
| #5（`:80`） | 通过（等价 URI） | 拒绝 |
| #6（scheme 大写） | 通过（scheme 大小写不敏感） | 拒绝 |
| #7/#8/#9（路径/host 不符） | 拒绝 | 拒绝 ✅ |

## 6. 根因分析

**已确证的事实**（全部由 §4.3 回执支持）：

- 校验对象是 CIMD 文档 `redirect_uris` 数组；
- 逐字节相同的 URI 通过（#1、#2），仅端口不同即失败（#3、#4）→ 比对维度包含端口且要求相等；
- `:80` 与省略端口不等价（#5）→ 未做默认端口规范化；
- scheme 大小写不等价（#6）→ 未做 URI 解析后的规范化；
- host 不做前缀/后缀放宽（#9）→ 明确不是模式匹配，是严格相等。

**推断（高置信，需在源码中确认）**：`redirect_uri` 与 `redirect_uris` 的比较实现为**原始字符串 `==`**（或解析后仍直接比较 `authority` 含端口），既没有 loopback 端口豁免，也没有任何 URI 规范化。若成立，这不是"漏了某个客户端"，而是比较器缺少整类规范要求。

**待确认项（本机无法核对）**：本机只有编译产物 `/Applications/MCP Console.app/Contents/MacOS/mcp-console`（错误串在其中可见），未找到 Rust 源码；因此具体函数位置与是否已有部分规范化逻辑，需由维护方在源码确认。**本报告未修改任何代码。**

## 7. 规范依据

1. **RFC 9700 §2.1（OAuth 2.0 Security BCP）**：
   > When comparing client redirection URIs against pre-registered URIs, authorization servers **MUST utilize exact string matching except for port numbers in localhost redirection URIs of native apps** (see Section 4.1.3).

2. **RFC 9700 §4.1.3**：
   > …the authorization server MUST ensure that the two URIs are equal; see Section 6.2.1 of [RFC3986], Simple String Comparison… **The only exception is native apps using a localhost URI: In this case, the authorization server MUST allow variable port numbers as described in Section 7.3 of [RFC8252].**

3. **RFC 8252 §7.3**：
   > **The authorization server MUST allow any port to be specified at the time of the request for loopback IP redirect URIs**, to accommodate clients that obtain an available ephemeral port from the operating system at the time of the request.

4. **CIMD（`draft-ietf-oauth-client-id-metadata-document-02`）§4.2** 要求对授权请求中的 redirect URL 做 "exact match, using simple string comparison"。**注意正确读法**：该句的精确匹配定义直接引自 RFC 9700，而 RFC 9700 已在同一处明文排除 native 应用的 localhost 端口号。因此 CIMD 的 "exact match" **不构成**拒绝临时端口的依据；把两者读成"必须逐字节相等"是对引用链的误解。

**结论**：当前行为违反 RFC 9700 的 **MUST**。客户端的 `client.json`（`application_type: native`，声明无端口 loopback）是符合 RFC 8252 的正确写法，不需要改。

## 8. 修复要求（验收口径）

### R1 引入专用比较器 `redirect_uri_matches(registered, requested, client_metadata)`

必须按 URI 语义比较，而非字符串比较：

1. 两者解析为绝对 URI（RFC 3986）；解析失败、含 fragment、含单点/双点路径段 → 拒绝。
2. `scheme` 小写后必须相等；`path` 必须逐字节相等；`query` 必须相等（缺失视为空）。
3. `host` 小写后必须相等。**不做** `127.0.0.1` ↔ `localhost` ↔ `[::1]` 的互认（保持现状的严格性，避免额外放行面）。
4. `port` 比较前先规范化：`http` 的 `:80`、`https` 的 `:443` 视同省略。
5. **唯一例外（本条是修复核心）**：当 `scheme == http` 且 `host ∈ {127.0.0.1, [::1], localhost}` 且 `client_metadata.application_type == native` 时，**忽略端口差异**（任意端口，含未指定端口）。
6. 其余情况端口必须相等。

### R2 例外不得扩大

- `application_type` 缺失或非 `native` → 走严格匹配（不得默认放宽）。
- `http` 且 host 非 loopback → 一律拒绝（RFC 9700 §4.1.3 要求 AS 不得允许非 native loopback 的 http 重定向）。
- `https` 且 host 为域名 → 严格匹配，不做端口放宽。
- 禁止用正则/前缀/后缀匹配替代上述规则。

### R3 `/oauth/token` 必须使用同一套规则

- 授权码需绑定**授权请求中实际收到的 `redirect_uri` 原值**；token 端点要求提交的 `redirect_uri` 与授权时原值相等（RFC 6749 §4.1.3）。
- 即：`authorize` 用 R1 的放宽比较器判定合法性，`code` 用原值做严格绑定回验。否则会出现"授权能过、换令牌又失败"的半修复。

### R4 错误响应与可观测性

- CIMD 校验失败应返回 **4xx**（建议 `400`，body 含 `error=invalid_request` 或 `invalid_client` 与 `error_description`），不要用 `200` 承载致命错误；错误分支**不得**重定向回未验证的 `redirect_uri`。
- 记一条 `warn` 级日志：`client_id`、`requested_redirect_uri`、`registered_redirect_uris`、命中的规则（`exact` / `loopback-port-relaxed`）。**不得**记录 token、`channel_token`、PKCE `code_verifier`。
- 错误文案区分三类，便于定位：`redirect_uri not declared` / `port not allowed` / `malformed redirect_uri`。

### R5 回归要求

- 现有通过用例（§4.3 #1、#2）必须仍通过；
- 拒绝用例（#7、#8、#9）必须仍被拒；
- 已注册的 DCR 客户端行为不变；
- 新增用例见 §9 全部通过。

## 9. 验收测试用例

`client_id=https://chatgpt.com/oauth/codex/client.json`（`application_type=native`，registered = `http://127.0.0.1/callback`、`http://localhost/callback`）：

| # | requested redirect_uri | 期望 |
|---|---|---|
| 1 | `http://127.0.0.1/callback` | 通过 |
| 2 | `http://127.0.0.1:55049/callback` | 通过（RFC 8252 §7.3） |
| 3 | `http://127.0.0.1:80/callback` | 通过（默认端口规范化） |
| 4 | `http://localhost:55049/callback` | 通过（RFC 9700 §2.1 措辞覆盖 localhost） |
| 5 | `http://[::1]:55049/callback` | 通过（若 CIMD 声明了 `[::1]` 形式；未声明则拒绝） |
| 6 | `HTTP://127.0.0.1:55049/callback` | 通过（scheme 大小写不敏感） |
| 7 | `http://127.0.0.1/other` | 拒绝（path 不符） |
| 8 | `http://127.0.0.1/callback/` | 拒绝（path 尾斜杠） |
| 9 | `http://127.0.0.1:55049/callback?x=1` | 拒绝（query 未声明） |
| 10 | `https://127.0.0.1:55049/callback` | 拒绝（scheme 不符） |
| 11 | `http://127.0.0.1.evil.example:55049/callback` | 拒绝（host 非 loopback） |
| 12 | `http://192.168.x.x:55049/callback` | 拒绝（非 loopback） |
| 13 | `http://127.0.0.1:55049/callback#f` | 拒绝（含 fragment） |
| 14 | 同上 1/2/3 但 `application_type=web` | 仅 #1 通过，#2/#3 拒绝（例外仅限 native） |

## 10. 附带发现（低优先级，可同批修）

### 10.1 致命错误用 HTTP 200 承载
`/oauth/authorize` 在校验失败时返回 `200` + HTML 错误页（实测 7 个拒绝分支状态码全为 `200`）。影响：程序化客户端与监控无法按状态码区分成功/失败，排障只能靠匹配正文。建议 `400`。

### 10.2 scheme 大小写导致误拒
`HTTP://127.0.0.1/callback` 被拒。URI scheme 大小写不敏感（RFC 3986 §3.1），随 R1 的规范化一并修正。

### 10.3 错误文案把两种原因合并
"redirect_uri is not declared" 同时覆盖"真的没声明"与"端口不同"，是本次排障绕弯的直接原因。按 R4 拆分。

### 10.4 未验证项（本报告不作断言）
- CIMD 文档的缓存时长与失效行为；
- 若 CIMD 文档拉取失败（5xx/超时）时的降级路径；
- `/oauth/token` 端当前的确切行为（无有效 code，无法实测；R3 依据规范提出，非实测缺陷）。

### 10.5 资源元数据与 AS 元数据的 scope 不一致
`/.well-known/oauth-protected-resource` 的 `scopes_supported` 为 `["mcp"]`，而 AS 元数据为 `["mcp","offline_access"]`，本次授权请求实际为 `mcp offline_access`（授权页接受）。按 RFC 9728，客户端以 PRM 的 `scopes_supported` 决定申请哪些 scope；PRM 缺 `offline_access` 可能使部分客户端不申请刷新令牌，导致长连接会话提前失效。建议对齐为 `["mcp","offline_access"]`。

## 11. 附录

### A. 客户端元数据文档（`https://chatgpt.com/oauth/codex/client.json`，实测原文）

```json
{"client_id":"https://chatgpt.com/oauth/codex/client.json","client_uri":"https://chatgpt.com/codex","application_type":"native","redirect_uris":["http://127.0.0.1/callback","http://localhost/callback"],"token_endpoint_auth_method":"none","token_endpoint_auth_methods_supported":["none"],"grant_types":["authorization_code","refresh_token"],"response_types":["code"],"client_name":"Codex","logo_uri":"https://persistent.oaistatic.com/sonic/misc/openai-logo.png"}
```

### B. 授权服务器元数据（`/.well-known/oauth-authorization-server`，实测原文）

```json
{"issuer":"https://mcp.llmfirstloop.com","authorization_endpoint":"https://mcp.llmfirstloop.com/oauth/authorize","token_endpoint":"https://mcp.llmfirstloop.com/oauth/token","revocation_endpoint":"https://mcp.llmfirstloop.com/oauth/revoke","revocation_endpoint_auth_methods_supported":["client_secret_basic","client_secret_post","none","private_key_jwt"],"registration_endpoint":"https://mcp.llmfirstloop.com/oauth/register","response_types_supported":["code"],"grant_types_supported":["authorization_code","refresh_token"],"code_challenge_methods_supported":["S256"],"token_endpoint_auth_methods_supported":["client_secret_basic","client_secret_post","none","private_key_jwt"],"authorization_response_iss_parameter_supported":true,"client_id_metadata_document_supported":true,"scopes_supported":["mcp","offline_access"],"service_documentation":"https://mcp.llmfirstloop.com/"}
```

说明：AS 已声明 `client_id_metadata_document_supported: true`，即对外承诺完整支持 CIMD；R1 属该承诺的应有之义。

### C. 失败响应正文片段（实测）

```html
<h2>授权 MCP Console</h2>
<p style="color:#c00;...">invalid CIMD client: redirect_uri is not declared by the CIMD metadata document</p>
```

### D. 复现脚本（可直接跑，判定看正文是否含 `invalid CIMD`）

```bash
CC="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
probe() {
  code=$(curl -sS -o /tmp/b.html -w '%{http_code}' -G 'http://127.0.0.1:8790/oauth/authorize' \
    -d 'response_type=code' \
    -d 'client_id=https://chatgpt.com/oauth/codex/client.json' \
    --data-urlencode "redirect_uri=$1" \
    -d 'scope=mcp offline_access' -d 'state=probe' \
    -d "code_challenge=$CC" -d 'code_challenge_method=S256')
  grep -q 'invalid CIMD' /tmp/b.html && r=REJECT || r=ACCEPT
  printf '%-42s http=%s %s\n' "$1" "$code" "$r"
}
probe "http://127.0.0.1/callback"
probe "http://127.0.0.1:55049/callback"
```

### E. 报告范围说明

本报告基于 2026-10-31 对运行中实例的实测（本地 `127.0.0.1:8790` 与公网 `https://mcp.llmfirstloop.com` 结果一致），未修改任何代码或配置。根因中的"裸字符串比较"为行为推断（高置信），最终以源码为准；§7 的规范引用为 RFC 原文摘录。
