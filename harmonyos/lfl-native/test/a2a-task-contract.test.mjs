import test from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === './StreamProtocol' &&
      context.parentURL?.endsWith('/A2ATaskContract.ts')) {
      return {
        url: new URL('../entry/src/main/ets/bridge/StreamProtocol.ts', import.meta.url).href,
        shortCircuit: true
      };
    }
    return nextResolve(specifier, context);
  }
});
const { A2aTaskBindings, A2aTaskState } =
  await import('../entry/src/main/ets/bridge/A2ATaskContract.ts');

const caller = { principalId: 'platform-principal-A', verifiedByHost: true };
const other = { principalId: 'platform-principal-B', verifiedByHost: true };
const digest = 'a'.repeat(64);
const input = (taskId = 'task-1') => ({
  taskId,
  contextId: 'ctx-1',
  clientSessionId: 'client-1',
  agentId: 'agent-LFL',
  requestSha256: digest
});
const receipt = (taskId = 'task-1', newlyReserved = true) => ({
  taskId,
  principalId: caller.principalId,
  requestSha256: digest,
  durableRecordConfirmed: true,
  newlyReserved,
  receiptId: 'durable-local-test-' + taskId
});
function fresh(taskId = 'task-1') {
  const guard = new A2aTaskBindings();
  const admission = guard.registerExecute(caller, input(taskId), receipt(taskId));
  assert.equal(admission.shouldSubmitNewHumanTurn, true);
  return guard;
}

test('Huawei published TaskState numeric names are frozen as shadow contract only', () => {
  assert.equal(A2aTaskState.SUBMITTED, 0);
  assert.equal(A2aTaskState.WORKING, 1);
  assert.equal(A2aTaskState.COMPLETED, 3);
  assert.equal(A2aTaskState.CANCELED, 4);
  assert.equal(A2aTaskState.FAILED, 5);
  assert.equal(A2aTaskState.AUTH_REQUIRED, 7);
});

test('host authorization and durable backend CAS are mandatory before new ingress', () => {
  const guard = new A2aTaskBindings();
  assert.throws(() => guard.registerExecute(
    {principalId: 'untrusted', verifiedByHost: false}, input(), receipt()
  ), /host_authentication_required/);
  assert.throws(() => guard.registerExecute(caller, input()), /durable_backend_admission_receipt_required/);
  assert.throws(() => guard.registerExecute(caller, input(), {
    ...receipt(), principalId: 'wrong'
  }), /durable_backend_admission_receipt_required/);
  assert.throws(() => guard.registerExecute(caller, {...input(), requestSha256: 'not-sha'}, receipt()),
    /request_digest_required/);
});

test('same task replay never authorizes a second human turn or a changed payload', () => {
  const guard = fresh();
  const duplicate = guard.registerExecute(caller, input(), receipt('task-1', false));
  assert.equal(duplicate.shouldSubmitNewHumanTurn, false);
  assert.throws(() => guard.registerExecute(caller, {...input(), contextId:'ctx-2'}, receipt()),
    /task_id_reuse_conflict/);
  assert.throws(() => guard.registerExecute(other, input(), {...receipt(), principalId:other.principalId}),
    /task_id_reuse_conflict/);
  assert.equal(guard.read(caller, 'task-1').state, A2aTaskState.SUBMITTED);
});

test('after process restart CAS existing receipt cannot trigger new dispatch', () => {
  const guard = new A2aTaskBindings();
  assert.throws(() => guard.registerExecute(caller, input(), receipt('task-1', false)),
    /task_already_reserved_recover_without_replay/);
  assert.throws(() => guard.read(caller, 'task-1'), /task_not_accessible_to_principal/);
});

test('run_started creates immutable exact task to LFL run binding', () => {
  const guard = fresh();
  assert.equal(guard.bindRun(caller, 'task-1', 'session-LFL', 'gen-1').state,
    A2aTaskState.WORKING);
  assert.equal(guard.bindRun(caller, 'task-1', 'session-LFL', 'gen-1').runGeneration, 'gen-1');
  assert.throws(() => guard.bindRun(caller, 'task-1', 'session-LFL', 'gen-2'),
    /run_identity_mismatch/);
  guard.registerExecute(caller, input('task-2'), receipt('task-2'));
  assert.throws(() => guard.bindRun(caller, 'task-2', 'session-LFL', 'gen-1'),
    /run_already_bound_to_another_task/);
});

test('cross-principal access and session identifiers never bypass authorization', () => {
  const guard = fresh();
  assert.throws(() => guard.read(other, 'task-1'), /task_not_accessible_to_principal/);
  assert.throws(() => guard.bindRun(other, 'task-1', 'sid', 'gen'), /task_not_accessible_to_principal/);
  assert.throws(() => guard.requestCancel(other, 'task-1'), /task_not_accessible_to_principal/);
});

test('cancel must be bound and dispatches only the exact generation once', () => {
  const guard = fresh();
  assert.throws(() => guard.requestCancel(caller, 'task-1'), /cancel_requires_bound_run/);
  guard.bindRun(caller, 'task-1', 'LFL-sid', 'g-new');
  const instruction = guard.requestCancel(caller, 'task-1');
  assert.equal(instruction.shouldDispatch, true);
  assert.deepEqual(JSON.parse(instruction.body), {session_id:'LFL-sid',run_generation:'g-new'});
  assert.deepEqual(guard.requestCancel(caller, 'task-1'), {shouldDispatch:false, body:''});
  assert.equal(guard.read(caller, 'task-1').state, A2aTaskState.WORKING);
});

test('cancel ACK alone never fabricates CANCELED, requires confirmed same-run receipt', () => {
  const guard = fresh();
  guard.bindRun(caller, 'task-1', 'sid', 'g');
  guard.requestCancel(caller, 'task-1');
  assert.throws(() => guard.markCanceledWithAuthoritativeReceipt(caller, 'task-1', 'sid', 'g', false),
    /confirmed_cancel_receipt_required/);
  assert.throws(() => guard.markCanceledWithAuthoritativeReceipt(caller, 'task-1', 'sid', 'other', true),
    /run_identity_mismatch/);
  assert.equal(guard.markCanceledWithAuthoritativeReceipt(caller, 'task-1','sid','g',true).state,
    A2aTaskState.CANCELED);
  assert.deepEqual(guard.requestCancel(caller, 'task-1'), {shouldDispatch:false,body:''});
});

test('disconnect keeps run uncertain; only exact done may mark COMPLETED', () => {
  const guard = fresh();
  guard.bindRun(caller, 'task-1', 'sid', 'g');
  assert.equal(guard.markTransportUnknown(caller, 'task-1').needsRecovery, true);
  assert.equal(guard.registerExecute(caller, input(), receipt('task-1', false))
    .shouldSubmitNewHumanTurn, false);
  assert.throws(() => guard.markDone(caller, 'task-1', 'sid', 'future-g', 'ok', false),
    /run_identity_mismatch/);
  const done = guard.markDone(caller, 'task-1', 'sid', 'g', 'ok', false);
  assert.equal(done.state, A2aTaskState.COMPLETED);
  assert.equal(done.needsRecovery, false);
  assert.ok(!Object.hasOwn(done, 'finalAnswer'), 'sensitive text must not leak into binding');
  assert.throws(() => guard.markDone(caller, 'task-1', 'sid', 'g','again',false),
    /terminal_task_immutable/);
});

test('incomplete done and real backend error never report COMPLETED', () => {
  const guard = fresh();
  guard.bindRun(caller, 'task-1', 'sid', 'g');
  assert.equal(guard.markDone(caller, 'task-1', 'sid','g','partial',true).state, A2aTaskState.FAILED);
  assert.equal(guard.read(caller, 'task-1').reason, 'run_incomplete');
  const another = fresh('task-2');
  another.bindRun(caller, 'task-2','sid2','g2');
  assert.equal(another.markBackendError(caller, 'task-2','sid2','g2','provider_error').state,
    A2aTaskState.FAILED);
  assert.equal(another.read(caller, 'task-2').reason, 'provider_error');
});

test('cancel race cannot publish COMPLETED', () => {
  const guard = fresh();
  guard.bindRun(caller, 'task-1', 'sid', 'gen');
  guard.requestCancel(caller, 'task-1');
  const receipt = guard.markDone(caller, 'task-1', 'sid', 'gen', 'text', false);
  assert.equal(receipt.state, A2aTaskState.UNSPECIFIED);
  assert.equal(receipt.needsRecovery, true);
});
