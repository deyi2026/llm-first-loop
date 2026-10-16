import test from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';

const BRIDGE = new URL('../entry/src/main/ets/bridge/', import.meta.url);
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (context.parentURL?.endsWith('.ts') &&
      (specifier === './StreamProtocol' || specifier === './A2ATaskContract')) {
      return { url: new URL(specifier + '.ts', BRIDGE).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  }
});
const { A2aTaskBindings, A2aTaskState } =
  await import('../entry/src/main/ets/bridge/A2ATaskContract.ts');
const { A2aDispatchCoordinator, denyAllPrincipals } =
  await import('../entry/src/main/ets/bridge/A2aDispatch.ts');

const sha = 'a'.repeat(64);
const projection = (method, taskId = 'task-1') => ({
  method, taskId, contextId: 'ctx-1', clientSessionId: 'cs-1',
  agentId: 'agent-1', requestSha256: sha
});
const verifierFor = (id) => ({ verify: () => ({ principalId: id }) });
const receiptFor = (taskId, principalId, requestSha) => ({
  taskId, principalId, requestSha256: requestSha,
  durableRecordConfirmed: true, newlyReserved: true, receiptId: 'r-' + taskId
});
const failingReceipts = { fetch: async () => { throw new Error('offline'); } };
const receiptSourceFor = (r) => ({ fetch: async () => r });
const recordingDispatch = () => {
  const calls = { submit: 0, cancel: [], };
  return {
    calls,
    dispatch: {
      submitHumanTurn: async () => { calls.submit += 1; },
      cancelBoundRun: async (payload) => { calls.cancel.push(payload); }
    }
  };
};

test('EXECUTE without host-verified principal is rejected, no submit', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(), denyAllPrincipals,
    failingReceipts, dispatch);
  const out = await c.handle(projection('EXECUTE'));
  assert.equal(out.kind, 'rejected');
  assert.equal(out.reason, 'host_authentication_required');
  assert.equal(calls.submit, 0);
});

test('EXECUTE with receipt failure is rejected before any submit', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), failingReceipts, dispatch);
  const out = await c.handle(projection('EXECUTE'));
  assert.equal(out.kind, 'rejected');
  assert.equal(out.reason, 'durable_backend_admission_receipt_required');
  assert.equal(calls.submit, 0);
});

test('EXECUTE with verified principal and CAS receipt submits exactly once', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), receiptSourceFor(receiptFor('task-1', 'p1', sha)), dispatch);
  const out = await c.handle(projection('EXECUTE'));
  assert.equal(out.kind, 'submitted');
  assert.equal(out.snapshot.state, A2aTaskState.SUBMITTED);
  assert.equal(calls.submit, 1);
});

test('redelivered EXECUTE is a duplicate and never resubmits', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), receiptSourceFor(receiptFor('task-1', 'p1', sha)), dispatch);
  await c.handle(projection('EXECUTE'));
  const out = await c.handle(projection('EXECUTE'));
  assert.equal(out.kind, 'duplicate');
  assert.equal(calls.submit, 1);
});

test('mismatched receipt is rejected by the binding contract', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), receiptSourceFor(receiptFor('other-task', 'p1', sha)), dispatch);
  const out = await c.handle(projection('EXECUTE'));
  assert.equal(out.kind, 'rejected');
  assert.equal(out.reason, 'durable_backend_admission_receipt_required');
  assert.equal(calls.submit, 0);
});

test('CANCEL before a bound run is rejected; after bind it dispatches exact payload', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), receiptSourceFor(receiptFor('task-1', 'p1', sha)), dispatch);
  await c.handle(projection('EXECUTE'));
  const early = await c.handle(projection('CANCEL'));
  assert.equal(early.kind, 'rejected');
  assert.equal(early.reason, 'cancel_requires_bound_run');
  c.onLflEvent('p1', 'task-1', {
    type: 'run_started',
    data: { session_id: 's-9', run_generation: 'g-9' }
  });
  const out = await c.handle(projection('CANCEL'));
  assert.equal(out.kind, 'cancel_dispatched');
  assert.deepEqual(calls.cancel, [JSON.stringify({ session_id: 's-9', run_generation: 'g-9' })]);
  const repeat = await c.handle(projection('CANCEL'));
  assert.equal(repeat.kind, 'cancel_suppressed');
  assert.equal(calls.cancel.length, 1);
});

test('TaskStatus surfaces the bound snapshot; unknown method rejected', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), receiptSourceFor(receiptFor('task-1', 'p1', sha)), dispatch);
  await c.handle(projection('EXECUTE'));
  c.onLflEvent('p1', 'task-1', {
    type: 'run_started', data: { session_id: 's-1', run_generation: 'g-1' }
  });
  const status = await c.handle(projection('TaskStatus'));
  assert.equal(status.kind, 'status');
  assert.equal(status.snapshot.state, A2aTaskState.WORKING);
  assert.equal(status.snapshot.sessionId, 's-1');
  const unknown = await c.handle(projection('CLEAR_CONTEXT'));
  assert.equal(unknown.kind, 'rejected');
  assert.equal(unknown.reason, 'unsupported_method');
});

test('done event completes a clean run; cancel race stays UNSPECIFIED', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), receiptSourceFor(receiptFor('task-1', 'p1', sha)), dispatch);
  await c.handle(projection('EXECUTE'));
  c.onLflEvent('p1', 'task-1', {
    type: 'run_started', data: { session_id: 's-1', run_generation: 'g-1' }
  });
  await c.handle(projection('CANCEL'));
  c.onLflEvent('p1', 'task-1', {
    type: 'done',
    data: { session_id: 's-1', run_generation: 'g-1', final_answer: 'ok', run_incomplete: false }
  });
  const raced = await c.handle(projection('TaskStatus'));
  assert.equal(raced.snapshot.state, A2aTaskState.UNSPECIFIED);
  assert.equal(raced.snapshot.needsRecovery, true);
});

test('second task on the same run identity is refused by run exclusivity', async () => {
  const { calls, dispatch } = recordingDispatch();
  const c = new A2aDispatchCoordinator(new A2aTaskBindings(),
    verifierFor('p1'), {
      fetch: async (ingress) => receiptFor(ingress.taskId, 'p1', ingress.requestSha256)
    }, dispatch);
  await c.handle(projection('EXECUTE', 'task-1'));
  c.onLflEvent('p1', 'task-1', {
    type: 'run_started', data: { session_id: 's-shared', run_generation: 'g-shared' }
  });
  await c.handle(projection('EXECUTE', 'task-2'));
  assert.throws(() => c.onLflEvent('p1', 'task-2', {
    type: 'run_started', data: { session_id: 's-shared', run_generation: 'g-shared' }
  }), /run_already_bound_to_another_task/);
});
