/**
 * Provider/SDK-independent shadow contract for the publicly documented
 * Huawei Agent Framework Kit A2A Task semantics.
 *
 * IMPORTANT: this is NOT @hms.ai.A2A, not an A2A server, and not an auth
 * provider. It MUST NOT be wired to untrusted RequestContext fields until
 * the real SDK/host authorization boundary is proven.
 */

import { cancellationPayload } from './StreamProtocol';

// Public Huawei API delta (2026-07-28). Verify against installed .d.ts
// before connecting native calls; these integers are NOT a replacement kit.
export const A2aTaskState = {
  SUBMITTED: 0,
  WORKING: 1,
  INPUT_REQUIRED: 2,
  COMPLETED: 3,
  CANCELED: 4,
  FAILED: 5,
  REJECTED: 6,
  AUTH_REQUIRED: 7,
  UNSPECIFIED: 8
};

export type A2aStateCode = number;

/**
 * Only a separately authenticated platform/backend adapter may issue this
 * proof. A2A taskId, clientSessionId, contextId and getAgentId() are NOT
 * proof of caller identity. The 'verified' flag alone is not cryptography.
 */
export interface TrustedCaller {
  principalId: string;
  verifiedByHost: boolean;
}

export interface A2aTaskIngress {
  taskId: string;
  contextId: string;
  clientSessionId: string;
  agentId: string;
  requestSha256: string;
}

/**
 * The future backend durable idempotency gate must validate and issue this
 * receipt. Current LFL does not provide this API. A self-declared value from
 * an incoming A2A RequestContext MUST NOT be trusted. The PoC never wires
 * this class to an actual native dispatch entrypoint.
 */
export interface BackendAdmissionReceipt {
  taskId: string;
  principalId: string;
  requestSha256: string;
  durableRecordConfirmed: boolean;
  newlyReserved: boolean;
  receiptId: string;
}

export interface A2aBindingSnapshot {
  taskId: string;
  contextId: string;
  clientSessionId: string;
  agentId: string;
  state: A2aStateCode;
  sessionId: string;
  runGeneration: string;
  cancelRequested: boolean;
  needsRecovery: boolean;
  reason: string;
}

export interface A2aAdmission {
  shouldSubmitNewHumanTurn: boolean;
  snapshot: A2aBindingSnapshot;
}

export interface A2aCancelInstruction {
  shouldDispatch: boolean;
  // Empty when the exact active Run is unbound or the request was repeated.
  body: string;
}

interface InternalBinding {
  callerId: string;
  ingress: A2aTaskIngress;
  state: A2aStateCode;
  sessionId: string;
  runGeneration: string;
  cancelRequested: boolean;
  needsRecovery: boolean;
  reason: string;
}

const SHA256_HEX = /^[0-9a-f]{64}$/;

function requireId(value: string, name: string): string {
  if (typeof value !== 'string' || !value.trim() || value.length > 256) {
    throw new Error(name + '_required');
  }
  return value;
}

function requireTrusted(caller: TrustedCaller): string {
  if (!caller || caller.verifiedByHost !== true) {
    throw new Error('host_authentication_required');
  }
  return requireId(caller.principalId, 'principal');
}

function isTerminal(state: A2aStateCode): boolean {
  return state === A2aTaskState.COMPLETED || state === A2aTaskState.CANCELED ||
    state === A2aTaskState.FAILED || state === A2aTaskState.REJECTED;
}

/**
 * In-memory pre-admission and A2A task-to-LFL-run identity guard.
 *
 * This avoids duplicate submits *during this process lifetime*, but it is
 * NOT a durable journal. Every initial admission also requires a trusted
 * server-side CAS receipt for the exact Task/principal/payload hash. The
 * required issuer does not exist yet; without it admission is disabled.
 * This is an offline-testable component, not native registration.
 */
export class A2aTaskBindings {
  private tasks: Map<string, InternalBinding> = new Map<string, InternalBinding>();
  private runOwners: Map<string, string> = new Map<string, string>();

  public registerExecute(caller: TrustedCaller, ingress: A2aTaskIngress,
    durableReceipt?: BackendAdmissionReceipt): A2aAdmission {
    const principal: string = requireTrusted(caller);
    requireId(ingress.taskId, 'task_id');
    requireId(ingress.contextId, 'context_id');
    requireId(ingress.clientSessionId, 'client_session_id');
    requireId(ingress.agentId, 'agent_id');
    if (!SHA256_HEX.test(ingress.requestSha256)) {
      throw new Error('request_digest_required');
    }
    if (!durableReceipt || durableReceipt.durableRecordConfirmed !== true ||
      durableReceipt.taskId !== ingress.taskId ||
      durableReceipt.principalId !== principal ||
      durableReceipt.requestSha256 !== ingress.requestSha256 ||
      !durableReceipt.receiptId || durableReceipt.receiptId.length > 256) {
      throw new Error('durable_backend_admission_receipt_required');
    }
    const previous: InternalBinding | undefined = this.tasks.get(ingress.taskId);
    if (previous) {
      if (previous.callerId !== principal ||
        previous.ingress.contextId !== ingress.contextId ||
        previous.ingress.clientSessionId !== ingress.clientSessionId ||
        previous.ingress.agentId !== ingress.agentId ||
        previous.ingress.requestSha256 !== ingress.requestSha256) {
        throw new Error('task_id_reuse_conflict');
      }
      return { shouldSubmitNewHumanTurn: false, snapshot: this.read(caller, ingress.taskId) };
    }
    // After process restart a durable CAS replay must return newlyReserved
    // false: do not turn an already-reserved Task into a second human ingress.
    if (durableReceipt.newlyReserved !== true) {
      throw new Error('task_already_reserved_recover_without_replay');
    }

    // Reserve the task *before* dispatch. A failed/unknown transport cannot
    // be implicitly retried as another human ingress.
    const entry: InternalBinding = {
      callerId: principal,
      ingress: {
        taskId: ingress.taskId,
        contextId: ingress.contextId,
        clientSessionId: ingress.clientSessionId,
        agentId: ingress.agentId,
        requestSha256: ingress.requestSha256
      },
      state: A2aTaskState.SUBMITTED,
      sessionId: '',
      runGeneration: '',
      cancelRequested: false,
      needsRecovery: false,
      reason: ''
    };
    this.tasks.set(ingress.taskId, entry);
    return { shouldSubmitNewHumanTurn: true, snapshot: this.read(caller, ingress.taskId) };
  }

  public bindRun(caller: TrustedCaller, taskId: string, sessionId: string,
    generation: string): A2aBindingSnapshot {
    const entry: InternalBinding = this.requireEntry(caller, taskId);
    requireId(sessionId, 'session_id');
    requireId(generation, 'run_generation');
    if (isTerminal(entry.state)) {
      throw new Error('terminal_task_cannot_rebind');
    }
    if (entry.sessionId) {
      if (entry.sessionId !== sessionId || entry.runGeneration !== generation) {
        throw new Error('run_identity_mismatch');
      }
      return this.read(caller, taskId);
    }
    const runKey: string = JSON.stringify([sessionId, generation]);
    const owner: string | undefined = this.runOwners.get(runKey);
    if (owner && owner !== taskId) {
      throw new Error('run_already_bound_to_another_task');
    }
    entry.sessionId = sessionId;
    entry.runGeneration = generation;
    entry.state = A2aTaskState.WORKING;
    this.runOwners.set(runKey, taskId);
    return this.read(caller, taskId);
  }

  public markTransportUnknown(caller: TrustedCaller, taskId: string): A2aBindingSnapshot {
    const entry: InternalBinding = this.requireEntry(caller, taskId);
    if (!isTerminal(entry.state)) {
      entry.needsRecovery = true;
      entry.reason = 'subscription_or_transport_unknown';
    }
    // Never submit again, mark COMPLETE, or cancel merely on disconnect.
    return this.read(caller, taskId);
  }

  public requestCancel(caller: TrustedCaller, taskId: string): A2aCancelInstruction {
    const entry: InternalBinding = this.requireEntry(caller, taskId);
    if (!entry.sessionId || !entry.runGeneration) {
      throw new Error('cancel_requires_bound_run');
    }
    if (isTerminal(entry.state) || entry.cancelRequested) {
      return { shouldDispatch: false, body: '' };
    }
    entry.cancelRequested = true;
    return {
      shouldDispatch: true,
      body: cancellationPayload(entry.sessionId, entry.runGeneration)
    };
  }

  public markBackendError(caller: TrustedCaller, taskId: string,
    sessionId: string, generation: string, code: string): A2aBindingSnapshot {
    const entry: InternalBinding = this.requireBoundRun(caller, taskId, sessionId, generation);
    if (isTerminal(entry.state)) {
      throw new Error('terminal_task_immutable');
    }
    entry.state = A2aTaskState.FAILED;
    entry.needsRecovery = false;
    entry.reason = code || 'backend_error';
    return this.read(caller, taskId);
  }

  public markDone(caller: TrustedCaller, taskId: string, sessionId: string,
    generation: string, finalAnswer: string, incomplete: boolean): A2aBindingSnapshot {
    const entry: InternalBinding = this.requireBoundRun(caller, taskId, sessionId, generation);
    if (isTerminal(entry.state)) {
      throw new Error('terminal_task_immutable');
    }
    if (typeof finalAnswer !== 'string' || typeof incomplete !== 'boolean') {
      throw new Error('invalid_backend_done_receipt');
    }
    if (incomplete) {
      entry.state = A2aTaskState.FAILED;
      entry.reason = 'run_incomplete';
      entry.needsRecovery = false;
    } else if (entry.cancelRequested) {
      // The existing LFL SSE done does not independently attest that a Stop
      // took effect. It may race with a normal finish: neither COMPLETED nor
      // CANCELED is safe to publish without a structured, paired receipt.
      entry.state = A2aTaskState.UNSPECIFIED;
      entry.reason = 'cancel_outcome_unverified';
      entry.needsRecovery = true;
    } else {
      entry.state = A2aTaskState.COMPLETED;
      entry.reason = '';
      entry.needsRecovery = false;
    }
    // Do not persist result content or secret text inside the mapping.
    return this.read(caller, taskId);
  }

  public markCanceledWithAuthoritativeReceipt(caller: TrustedCaller, taskId: string,
    sessionId: string, generation: string, cancelledConfirmed: boolean): A2aBindingSnapshot {
    const entry: InternalBinding = this.requireBoundRun(caller, taskId, sessionId, generation);
    if (isTerminal(entry.state)) {
      throw new Error('terminal_task_immutable');
    }
    if (!entry.cancelRequested || cancelledConfirmed !== true) {
      throw new Error('confirmed_cancel_receipt_required');
    }
    entry.state = A2aTaskState.CANCELED;
    entry.needsRecovery = false;
    entry.reason = 'confirmed_cancelled';
    return this.read(caller, taskId);
  }

  public read(caller: TrustedCaller, taskId: string): A2aBindingSnapshot {
    const entry: InternalBinding = this.requireEntry(caller, taskId);
    return {
      taskId: entry.ingress.taskId,
      contextId: entry.ingress.contextId,
      clientSessionId: entry.ingress.clientSessionId,
      agentId: entry.ingress.agentId,
      state: entry.state,
      sessionId: entry.sessionId,
      runGeneration: entry.runGeneration,
      cancelRequested: entry.cancelRequested,
      needsRecovery: entry.needsRecovery,
      reason: entry.reason
    };
  }

  private requireBoundRun(caller: TrustedCaller, taskId: string,
    sessionId: string, generation: string): InternalBinding {
    const entry: InternalBinding = this.requireEntry(caller, taskId);
    if (!entry.sessionId || !entry.runGeneration ||
      entry.sessionId !== sessionId || entry.runGeneration !== generation) {
      throw new Error('run_identity_mismatch');
    }
    return entry;
  }

  private requireEntry(caller: TrustedCaller, taskId: string): InternalBinding {
    const principal: string = requireTrusted(caller);
    const entry: InternalBinding | undefined = this.tasks.get(requireId(taskId, 'task_id'));
    if (!entry || entry.callerId !== principal) {
      throw new Error('task_not_accessible_to_principal');
    }
    return entry;
  }
}
