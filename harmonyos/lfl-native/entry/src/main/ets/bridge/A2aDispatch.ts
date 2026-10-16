/**
 * Provider-free dispatch decision layer for the offline A2A adapter.
 *
 * Wires the frozen A2A Task semantics (A2ATaskContract.ts) to explicit
 * backend actions WITHOUT trusting unverified host identity: every
 * EXECUTE is refused unless a separately qualified host principal
 * verifier AND the backend durable admission CAS receipt both succeed.
 * This module never constructs an A2A Server and performs no network IO.
 */

import { A2aTaskBindings } from './A2ATaskContract';
import type {
  BackendAdmissionReceipt,
  A2aTaskIngress,
  A2aBindingSnapshot
} from './A2ATaskContract';
import type { LflEvent } from './StreamProtocol';

export interface RequestContextProjection {
  method: string;
  taskId: string;
  contextId: string;
  clientSessionId: string;
  agentId: string;
  requestSha256: string;
}

export interface HostPrincipalVerifier {
  verify(projection: RequestContextProjection): { principalId: string | null };
}

/** Fail-closed default: the PoC has no qualified platform verifier yet. */
export const denyAllPrincipals: HostPrincipalVerifier = {
  verify: (_projection: RequestContextProjection): { principalId: string | null } => {
    return { principalId: null };
  }
};

export interface AdmissionReceiptSource {
  fetch(ingress: A2aTaskIngress): Promise<BackendAdmissionReceipt>;
}

export interface BackendDispatch {
  /** One human turn submit; implementors must markTransportUnknown on loss. */
  submitHumanTurn(): Promise<void>;
  cancelBoundRun(payload: string): Promise<void>;
}

export type DispatchOutcome =
  | { kind: 'rejected'; reason: string }
  | { kind: 'duplicate'; snapshot: A2aBindingSnapshot }
  | { kind: 'submitted'; snapshot: A2aBindingSnapshot }
  | { kind: 'cancel_dispatched'; snapshot: A2aBindingSnapshot }
  | { kind: 'cancel_suppressed'; snapshot: A2aBindingSnapshot }
  | { kind: 'status'; snapshot: A2aBindingSnapshot };

interface VerifiedCaller {
  principalId: string;
}

export class A2aDispatchCoordinator {
  private readonly bindings: A2aTaskBindings;
  private readonly verifier: HostPrincipalVerifier;
  private readonly receipts: AdmissionReceiptSource;
  private readonly dispatch: BackendDispatch;

  constructor(bindings: A2aTaskBindings, verifier: HostPrincipalVerifier,
    receipts: AdmissionReceiptSource, dispatch: BackendDispatch) {
    this.bindings = bindings;
    this.verifier = verifier;
    this.receipts = receipts;
    this.dispatch = dispatch;
  }

  public async handle(projection: RequestContextProjection): Promise<DispatchOutcome> {
    if (projection.method === 'EXECUTE') {
      const verified: { principalId: string | null } = this.verifier.verify(projection);
      if (!verified || verified.principalId === null) {
        return { kind: 'rejected', reason: 'host_authentication_required' };
      }
      const ingress: A2aTaskIngress = {
        taskId: projection.taskId,
        contextId: projection.contextId,
        clientSessionId: projection.clientSessionId,
        agentId: projection.agentId,
        requestSha256: projection.requestSha256
      };
      let receipt: BackendAdmissionReceipt;
      try {
        receipt = await this.receipts.fetch(ingress);
      } catch (_err) {
        return { kind: 'rejected', reason: 'durable_backend_admission_receipt_required' };
      }
      let admission: { shouldSubmitNewHumanTurn: boolean; snapshot: A2aBindingSnapshot };
      try {
        admission = this.bindings.registerExecute(
          { principalId: verified.principalId, verifiedByHost: true },
          ingress, receipt);
      } catch (err) {
        return { kind: 'rejected', reason: (err as Error).message };
      }
      if (!admission.shouldSubmitNewHumanTurn) {
        return { kind: 'duplicate', snapshot: admission.snapshot };
      }
      await this.dispatch.submitHumanTurn();
      return { kind: 'submitted', snapshot: admission.snapshot };
    }
    if (projection.method === 'CANCEL') {
      const caller: VerifiedCaller | null = this.requirePrincipal(projection);
      if (caller === null) {
        return { kind: 'rejected', reason: 'host_authentication_required' };
      }
      let instruction: { shouldDispatch: boolean; body: string };
      try {
        instruction = this.bindings.requestCancel(this.trusted(caller), projection.taskId);
      } catch (err) {
        return { kind: 'rejected', reason: (err as Error).message };
      }
      if (!instruction.shouldDispatch) {
        return {
          kind: 'cancel_suppressed',
          snapshot: this.bindings.read(this.trusted(caller), projection.taskId)
        };
      }
      await this.dispatch.cancelBoundRun(instruction.body);
      return {
        kind: 'cancel_dispatched',
        snapshot: this.bindings.read(this.trusted(caller), projection.taskId)
      };
    }
    if (projection.method === 'TaskStatus') {
      const caller: VerifiedCaller | null = this.requirePrincipal(projection);
      if (caller === null) {
        return { kind: 'rejected', reason: 'host_authentication_required' };
      }
      try {
        return {
          kind: 'status',
          snapshot: this.bindings.read(this.trusted(caller), projection.taskId)
        };
      } catch (err) {
        return { kind: 'rejected', reason: (err as Error).message };
      }
    }
    return { kind: 'rejected', reason: 'unsupported_method' };
  }

  /** Feed one verified LFL SSE event into the Task-to-Run binding. */
  public onLflEvent(principalId: string, taskId: string, event: LflEvent): void {
    const caller = this.trusted({ principalId: principalId });
    if (event.type === 'run_started') {
      this.bindings.bindRun(caller, taskId, event.data.session_id || '',
        event.data.run_generation || '');
    } else if (event.type === 'done') {
      this.bindings.markDone(caller, taskId, event.data.session_id || '',
        event.data.run_generation || '', event.data.final_answer || '',
        event.data.run_incomplete === true);
    } else if (event.type === 'error') {
      this.bindings.markBackendError(caller, taskId, event.data.session_id || '',
        event.data.run_generation || '', event.data.error || 'backend_error');
    }
    // Other event types carry no Task-state authority.
  }

  private requirePrincipal(projection: RequestContextProjection): VerifiedCaller | null {
    const verified: { principalId: string | null } = this.verifier.verify(projection);
    if (!verified || verified.principalId === null) {
      return null;
    }
    return { principalId: verified.principalId };
  }

  private trusted(caller: VerifiedCaller): { principalId: string; verifiedByHost: boolean } {
    return { principalId: caller.principalId, verifiedByHost: true };
  }
}
