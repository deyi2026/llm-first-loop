/**
 * Pure LFL Web SSE wire helpers. No network/credentials here so the exact
 * parser and run identity rules can be tested under Node and built by ArkTS.
 */
export interface LflEventData {
  session_id?: string;
  run_generation?: string;
  data?: string;
  final_answer?: string;
  run_incomplete?: boolean;
  verification_note?: string | null;
  error?: string;
  detail?: string;
  tool_call_id?: string;
  tool_name?: string;
  status?: string;
}

export interface LflEvent {
  type: string;
  data: LflEventData;
}

export interface LflStreamStatus {
  running: boolean;
  run_generation?: string;
}

export interface LflHistoryMessage {
  role: string;
  content: string;
}

export interface LflHistory {
  session_id: string;
  messages: LflHistoryMessage[];
}

export interface ArtifactCandidate {
  ref: string;
  source: string;
  verification: string;
}

const MAX_PENDING_FRAME = 1024 * 1024;
const REF_PATTERN = /artifact:\/\/v1\/[0-9a-f]{32}(?![0-9a-zA-Z])/g;

export class LflSseParser {
  private pending: string = '';
  private terminal: boolean = false;

  public push(chunk: string): LflEvent[] {
    if (this.terminal) {
      return [];
    }
    this.pending += chunk;
    const events: LflEvent[] = [];
    let boundary: number = this.pending.indexOf('\n\n');
    while (boundary !== -1) {
      const frame: string = this.pending.substring(0, boundary);
      this.pending = this.pending.substring(boundary + 2);
      const lines: string[] = frame.split('\n');
      for (const line of lines) {
        if (!line.startsWith('data: ')) {
          continue;
        }
        let event: LflEvent;
        try {
          event = JSON.parse(line.substring(6)) as LflEvent;
        } catch (_err) {
          throw new Error('malformed_sse_event');
        }
        if (!event || typeof event.type !== 'string' || !event.data || typeof event.data !== 'object') {
          throw new Error('invalid_sse_envelope');
        }
        if (event.type === 'run_started' &&
          (!event.data.session_id || !event.data.run_generation)) {
          throw new Error('run_identity_missing');
        }
        events.push(event);
        if (event.type === 'done' || event.type === 'error') {
          this.terminal = true;
          return events;
        }
      }
      boundary = this.pending.indexOf('\n\n');
    }
    if (this.pending.length > MAX_PENDING_FRAME) {
      throw new Error('sse_frame_too_large');
    }
    return events;
  }

  public hasTerminal(): boolean {
    return this.terminal;
  }
}

export function resumeDecision(status: LflStreamStatus, expectedGeneration: string): string {
  if (!status.running) {
    return 'history';
  }
  if (!status.run_generation) {
    return 'unknown';
  }
  if (expectedGeneration.length > 0 && status.run_generation !== expectedGeneration) {
    return 'generation_mismatch';
  }
  return 'resume';
}

export function resumePayload(sessionId: string, runGeneration: string): string {
  if (!sessionId || !runGeneration) {
    throw new Error('resume_requires_exact_identity');
  }
  return JSON.stringify({
    message: 'resume',
    session_id: sessionId,
    resume: true,
    run_generation: runGeneration
  });
}

export function cancellationPayload(sessionId: string, runGeneration: string): string {
  if (!sessionId || !runGeneration) {
    throw new Error('cancel_requires_exact_identity');
  }
  return JSON.stringify({ session_id: sessionId, run_generation: runGeneration });
}

export function artifactCandidates(text: string, source: string): ArtifactCandidate[] {
  const out: ArtifactCandidate[] = [];
  const unique = new Set<string>();
  REF_PATTERN.lastIndex = 0;
  for (const match of text.matchAll(REF_PATTERN)) {
    const ref = match[0];
    if (!unique.has(ref)) {
      unique.add(ref);
      out.push({ ref: ref, source: source, verification: 'unverified_ref' });
    }
  }
  return out;
}

export function historyAnswer(history: LflHistory): string {
  for (let i = history.messages.length - 1; i >= 0; i--) {
    const row: LflHistoryMessage = history.messages[i];
    if (row.role === 'assistant' && row.content.trim().length > 0) {
      return row.content;
    }
  }
  return '';
}
