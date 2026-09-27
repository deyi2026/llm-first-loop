# WebGPT long-context / text-ingress qualification — 2026-09-27

## Decision

- Keep production `CHATGPT_WEB_CONTEXT_TOKENS=262144`.
- Do **not** promote WebGPT to 512K with the current one-message snapshot transport.
- Add a separate qualified text-ingress guard: `CHATGPT_WEB_MAX_REQUEST_CHARS=150000`.
- The guard applies to the complete rendered browser message (protocol preamble + JSON request + tools/messages), not just LFL history.
- Oversize requests fail before `composer.fill()` as an `LLMProtocolError` containing `request_too_large`, so the existing LFL overflow path remains authoritative.

## Why 256K remains valid

WebGPT has no authoritative tokenizer endpoint. LFL therefore uses its conservative fallback projection of `0.6 chars/token`. With the existing 90% context safety margin and 16K output reserve:

- 256K context projects to about `141,557` chars before later schema/history accounting.
- 512K context projects to about `283,115` chars.

The real ChatGPT Web text-ingress boundary observed below is compatible with the 256K projection and incompatible with the 512K projection.

## Real-page evidence

All probes used the exact leased ChatGPT Project surface through CDP without foreground activation.

### Standard LFL protocol

- `145,036` complete rendered chars: **PASS**. The model returned the exact random retrieval marker.
- `176,547` complete rendered chars: **FAIL**. ChatGPT Web displayed `你提交的消息过长，请修改后重新提交。` / `你提交的消息过长，请编辑后重新发送。` and produced no assistant answer.

### Coarse raw-size probes

- 200K raw chars did not produce the explicit too-long error, but the Project's LFL ingress policy handled the non-protocol message, so this is only size evidence, not a semantic/provider PASS.
- 300K raw chars produced the explicit too-long error.
- A 1.4M-char direct-message probe was rejected as too long.

### Attachment probe

- A 1.4M-char text file could be attached successfully.
- Under the existing strict LFL model protocol, the model correctly refused to treat the attachment as readable provider context because no LFL file-reading tool was supplied and ChatGPT-native tools are prohibited.
- Therefore attachment transport is **not** qualified and the LFL/native-tool boundary remains unchanged.

## Guard qualification

The guard is set to `150000` complete rendered chars, above the real 145,036-char PASS and below the real 176,547-char FAIL.

A real mechanical oversize test produced:

- rendered chars: `151,914`
- local error: `request_too_large: ChatGPT Web rendered request exceeds qualified text ingress limit`
- `is_overflow_error(...) == True`
- browser remained on the clean Project root
- composer remained empty
- no ChatGPT `消息过长` UI appeared

This protects browser state while reusing the existing deterministic overflow shrink/rebuild behavior.

## Cache conclusion

Prompt-prefix stability remains useful for provider-side caching when available, but it does not extend the Web text-ingress envelope. Cache is therefore an efficiency optimization, not a substitute for context capacity.

## Next direction

Do not bypass this boundary by enabling ChatGPT-native file/search tools or by treating outer ChatGPT history as LFL memory. Further gains should come from LFL-owned selective hydration/compaction and stable-prefix reuse inside the qualified 256K / 150K-envelope design. A future larger Web surface can be requalified by raising `CHATGPT_WEB_MAX_REQUEST_CHARS` only after new real-page evidence.
