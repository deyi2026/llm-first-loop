# LFL HarmonyOS native bridge v0.1 — frozen PoC contract

Status: **isolated experiment**, not an installed/signed App, A2A admission, or production rollout.
Authority: existing LFL `src/llm_loop/web/routes.py`, `web/schemas.py`,
`core/loop/runner.py`, `workspace/artifacts.py` at the worktree HEAD.
Backend HTTP and HarmonyOS A2A are **distinct interfaces**. Do not present HTTPS as native A2A.

## Identity, authorization, ingress

- Configure an explicit **HTTPS** URL to a user-authorized LFL backend.
  No default production endpoint; never print, store or transmit bearer tokens elsewhere.
- One user send = at most one `POST /api/v1/chat/stream` with
  `{message, new_session:true}` OR `{message,session_id}`.
- HTTP errors, no `run_started`, and transport uncertainty **do not justify resending**:
  server may already have durably accepted the human turn.
- `run_started` is the first valid evidence of this run's
  `session_id + run_generation`; no reference to another session/run is permitted.
- SSE wire is `data: {"type":"<name>","data":{...}}\n\n`, encoded UTF-8.
  Frames may split across transport chunks, including mid UTF-8 codepoints.
  Types: `run_started`, `answer_delta`, `reasoning_delta`,
  `tool_round`, `tool_result`, `done`, `error`.
  `answer_delta.data` is text; `done.final_answer` is terminal authority
  and replaces accumulated partial deltas. `error` is terminal.
- `done.run_incomplete=true` **must not** be shown as a completed task.
  `dataEnd` without a terminal event means unknown/interrupted, never success.

## Interruption, cancel, reconnect

- SSE transport disconnect cancels only the subscription, **not** the backend Run.
- Cancellation uses `POST /api/v1/chat/cancel` with
  `{session_id,run_generation}`. The optional run_generation is introduced
  additively for the native PoC; server must match under runner lock.
  Existing Web clients that send only session_id keep their legacy contract.
- A cancel acknowledgment indicates a requested stop, **not** that all external
  work/provider transport/budget effects already terminated.
- On a known session stream disconnect, GET
  `/api/v1/chat/stream/status?session_id=...`. Resume only a known exact
  `run_generation`, using `POST /api/v1/chat/stream` with
  `{message:"resume",session_id,resume:true,run_generation}`.
  If the generation mismatches, do **not** attach to another run or resend.
- A resume replay may resend past deltas; reset the tentative answer before
  displaying resumed deltas. Terminal `done` takes final authority.
- If the status reports `running=false`, get
  `/api/v1/sessions/{session_id}/messages?limit=20&offset=0`.
  History is a *read-only reconstruction*, not evidence of the just-ended Run
  without an exact matching run receipt. No duplicate human ingress.
- Network recovery attempts are bounded (max one automatic resume);
  manual recovery can be explicitly requested using an entered session ID.
- For an unknown session ID before `run_started`, no automatic retry/recover
  by shared `/session/current` pointer, as that could bind to another user's run.

## Artifact semantics and A2A mapping

- A workspace artifact identifier has shape `artifact://v1/[0-9a-f]{32}`.
  Its appearance in final answer/history creates an
  **unverified reference candidate**, not a fetched/validated/downloaded file.
- Real byte delivery would require a separately scoped, authenticated
  immutable artifact hydration endpoint with SHA256/readback and workspace
  ownership checks. There is **no** such verified App endpoint in this PoC.
- Map (in a subsequent actual AFK adapter): A2A task ID -> exact
  `session_id/run_generation`; task active -> stream/status;
  task terminal -> `done/error`; artifacts -> *verified* workspace artifact
  descriptors only. Do not claim a generated A2A `Artifact` from an opaque ref.
- The current SDK-neutral shadow adapter in `bridge/A2ATaskContract.ts`
  additionally requires verified caller identity, SHA256 request fingerprint
  and a backend durable task CAS reservation receipt. No issuer exists in
  current LFL; neither this component nor the native App may submit a real
  A2A `EXECUTE` without a valid separately implemented backend authority.
- An in-flight `CANCEL` with a racing `done` remains `UNSPECIFIED` pending
  an authoritative outcome receipt. HTTP cancel acknowledged does not imply
  A2A `CANCELED`. The public `TaskState` numbers in the shadow contract
  must be compared against actual installed SDK .d.ts on qualification.
- A2A admission, SDK API availability, phone/tablet device, signing,
  real Xiǎoyì dispatch, performance/parity and end-device privacy remain
  **unverified** until separate real-device receipts are captured.

## Required verification

1. Host-side tests: fragmented SSE/UTF-8, terminal authority, malformed
   or truncated streams, generation selection, stale cancel negative, artifact
   positive/negative, no-replay after unknown write.
2. API26 `hvigor assembleHap` including ArkTS check, generated unsigned HAP.
3. Loopback fixture HTTP tests (no external model/provider call); compare
   actual LFL DTOs/routes to frozen contract.
4. Real device A2A/HTTPS, signed build and native-vs-mobile-Web metrics:
   *not* satisfied by host fixture or unsigned package.
