import { LflTransport } from '../bridge/LflTransport';
import { A2aTaskBindings } from '../bridge/A2ATaskContract';
import { NativeA2aCompileProbe } from '../bridge/NativeA2aCompileProbe';
import {
  LflEvent, artifactCandidates, cancellationPayload, historyAnswer,
  resumeDecision, resumePayload
} from '../bridge/StreamProtocol';

@Entry
@Component
struct Index {
  @State endpoint: string = '';
  @State authToken: string = '';
  @State message: string = '';
  @State sessionId: string = '';
  @State runGeneration: string = '';
  @State restoreSession: string = '';
  @State answer: string = '';
  @State artifacts: string = '';
  @State state: string = 'idle';
  @State busy: boolean = false;

  private transport: LflTransport = new LflTransport();
  // Offline type-check only: NO native A2A server registration. This guard is
  // deliberately unarmed without trusted host identity + backend CAS receipts.
  private a2aContract: A2aTaskBindings = new A2aTaskBindings();
  // Typechecked at build time only; does not create or start an A2A server.
  private a2aSdkCompileProbe: NativeA2aCompileProbe = new NativeA2aCompileProbe();

  private process(event: LflEvent): void {
    const row = event.data;
    if (event.type === 'run_started') {
      // Never render a different run into the current session.
      if (this.sessionId && row.session_id !== this.sessionId) {
        this.state = 'stream_session_mismatch';
        return;
      }
      if (this.runGeneration && row.run_generation !== this.runGeneration) {
        this.state = 'stream_generation_mismatch';
        return;
      }
      this.sessionId = row.session_id ?? '';
      this.runGeneration = row.run_generation ?? '';
      this.restoreSession = this.sessionId;
      this.state = 'running';
    } else if (event.type === 'answer_delta') {
      this.answer += row.data ?? '';
      this.state = 'answering';
    } else if (event.type === 'tool_round') {
      this.state = 'using_tool';
    } else if (event.type === 'tool_result') {
      this.state = 'integrating';
    } else if (event.type === 'done') {
      if (this.sessionId && row.session_id !== this.sessionId) {
        this.state = 'terminal_session_mismatch';
        return;
      }
      if (!row.session_id || typeof row.final_answer !== 'string') {
        this.state = 'invalid_terminal_receipt';
        return;
      }
      this.sessionId = row.session_id;
      this.restoreSession = this.sessionId;
      // The server's terminal answer, not partial deltas, is authoritative.
      this.answer = row.final_answer;
      this.artifacts = artifactCandidates(this.answer, 'done')
        .map((candidate) => candidate.ref + ' (unverified)').join('\n');
      this.state = row.run_incomplete ? 'run_incomplete' : 'done';
    } else if (event.type === 'error') {
      this.state = 'engine: ' + (row.error ?? 'unknown');
    }
  }

  private async send(): Promise<void> {
    if (this.busy || !this.message.trim()) {
      return;
    }
    this.answer = '';
    this.artifacts = '';
    this.runGeneration = '';
    const body: Record<string, string | boolean> = { message: this.message };
    if (this.sessionId) {
      body['session_id'] = this.sessionId;
    } else {
      body['new_session'] = true;
    }
    this.busy = true;
    this.state = 'connecting';
    await this.execute(JSON.stringify(body), false);
    this.busy = false;
  }

  private async execute(body: string, alreadyRecovered: boolean): Promise<void> {
    try {
      await this.transport.stream(this.endpoint, this.authToken, body, (event: LflEvent) => {
        this.process(event);
      });
    } catch (_err) {
      if (this.state === 'stream_session_mismatch' ||
          this.state === 'stream_generation_mismatch' ||
          this.state === 'terminal_session_mismatch' ||
          this.state === 'invalid_terminal_receipt') {
        return;
      }
      if (!this.sessionId) {
        this.state = 'submission_outcome_unknown_no_replay';
        return;
      }
      this.state = 'connection_interrupted';
      if (!alreadyRecovered) {
        await this.recoverKnown(true);
      } else {
        this.state = 'retry_limit_reached_use_recover';
      }
    }
  }

  private async recoverKnown(auto: boolean): Promise<void> {
    const sid: string = this.sessionId;
    if (!sid) {
      this.state = 'session_id_required';
      return;
    }
    try {
      const snap = await this.transport.readStatus(this.endpoint, this.authToken, sid);
      const action: string = resumeDecision(snap, this.runGeneration);
      if (action === 'generation_mismatch') {
        this.state = 'run_generation_mismatch_no_attach';
        return;
      }
      if (action === 'unknown') {
        this.state = 'status_run_identity_missing';
        return;
      }
      if (action === 'history') {
        const history = await this.transport.readHistory(this.endpoint, this.authToken, sid);
        this.answer = historyAnswer(history);
        this.artifacts = artifactCandidates(this.answer, 'history')
          .map((candidate) => candidate.ref + ' (unverified)').join('\n');
        this.state = 'history_read_only_not_run_receipt';
        return;
      }
      const generation: string = snap.run_generation ?? '';
      this.runGeneration = generation;
      // Resume replays old deltas. Reset tentative answer to prevent duplication.
      this.answer = '';
      this.artifacts = '';
      this.state = 'resuming';
      await this.execute(resumePayload(sid, generation), auto);
    } catch (_err) {
      this.state = 'recovery_failed_no_replay';
    }
  }

  private async manualRecover(): Promise<void> {
    if (this.busy) {
      return;
    }
    const sid = this.restoreSession.trim();
    if (!sid) {
      this.state = 'session_id_required';
      return;
    }
    this.sessionId = sid;
    this.runGeneration = '';
    this.busy = true;
    await this.recoverKnown(true);
    this.busy = false;
  }

  private async cancelCurrent(): Promise<void> {
    // Avoid a stale session-only cancel: both identities must be known.
    if (!this.busy || !this.sessionId || !this.runGeneration) {
      this.state = 'cancel_requires_exact_running_identity';
      return;
    }
    try {
      const result = await this.transport.cancel(
        this.endpoint, this.authToken,
        cancellationPayload(this.sessionId, this.runGeneration)
      );
      if (result.status === 409) {
        this.state = 'cancel_generation_mismatch';
      } else if (result.status !== 200) {
        this.state = 'cancel_HTTP_' + result.status.toString();
      } else {
        const response = JSON.parse(result.text) as { cancelled: boolean };
        this.state = response.cancelled ? 'cancel_requested_wait_for_terminal' :
          'cancel_not_accepted';
      }
    } catch (_err) {
      this.state = 'cancel_ack_unknown';
    }
  }

  aboutToDisappear(): void {
    this.transport.disconnectSubscription();
  }

  build() {
    Column({ space: 10 }) {
      Text('LFL · HarmonyOS').fontSize(25).fontWeight(FontWeight.Bold)
      Text('Native SSE client · existing LFL engine').fontSize(12)
      Text('A2A: awaiting matching SDK and verified host credentials').fontSize(11)
      TextInput({ text: this.endpoint, placeholder: 'Explicit HTTPS LFL origin' })
        .onChange((value: string) => { this.endpoint = value; })
      TextInput({ text: this.authToken, placeholder: 'Optional Bearer (memory only)' })
        .type(InputType.Password)
        .onChange((value: string) => { this.authToken = value; })
      TextArea({ text: this.message, placeholder: 'Ask LFL' })
        .height(90).onChange((value: string) => { this.message = value; })
      Row({ space: 10 }) {
        Button('Send').enabled(!this.busy).onClick(() => { this.send(); })
        Button('Stop').enabled(this.busy).onClick(() => { this.cancelCurrent(); })
        Button('New').enabled(!this.busy).onClick(() => {
          this.sessionId = '';
          this.runGeneration = '';
          this.restoreSession = '';
          this.answer = '';
          this.artifacts = '';
          this.state = 'idle';
        })
      }
      Text('State: ' + this.state).fontSize(13)
      Text('Session: ' + (this.sessionId || '(unbound)')).fontSize(11)
      Text('Run: ' + (this.runGeneration || '(unknown)')).fontSize(11)
      TextInput({ text: this.restoreSession, placeholder: 'Session ID for read-only recover' })
        .onChange((value: string) => { this.restoreSession = value; })
      Button('Recover').enabled(!this.busy).onClick(() => { this.manualRecover(); })
      Scroll() {
        Column({ space: 12 }) {
          Text(this.answer).fontSize(16).width('100%')
          Text(this.artifacts).fontSize(12).width('100%')
        }
      }.layoutWeight(1)
    }.padding(20).width('100%').height('100%')
  }
}
