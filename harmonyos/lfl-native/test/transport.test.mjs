import test from 'node:test';
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
const shimBase = new URL('./shims/', import.meta.url);
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === '@kit.NetworkKit') return {url:new URL('NetworkKit.mjs',shimBase).href,shortCircuit:true};
    if (specifier === '@kit.ArkTS') return {url:new URL('ArkTS.mjs',shimBase).href,shortCircuit:true};
    if (specifier === './StreamProtocol' && context.parentURL?.endsWith('/LflTransport.ts')) {
      return {url:new URL('../entry/src/main/ets/bridge/StreamProtocol.ts',import.meta.url).href,shortCircuit:true};
    }
    return nextResolve(specifier,context);
  }
});
const {LflTransport} = await import('../entry/src/main/ets/bridge/LflTransport.ts');
const {queueScenario,observed}=await import('./shims/NetworkKit.mjs');

const message = (type, data) => new TextEncoder().encode(`data: ${JSON.stringify({type, data})}\n\n`);

test('actual ArkTS transport decodes byte-fragmented UTF8 stream and terminal receipt', async () => {
  const bytes = new Uint8Array([...message('run_started',{session_id:'s1',run_generation:'g1'}),
    ...message('answer_delta',{data:'雨☔'}),
    ...message('done',{session_id:'s1',final_answer:'雨☔',run_incomplete:false})]);
  queueScenario({chunks:[...bytes].map(b => new Uint8Array([b]))});
  const events=[];
  const transport=new LflTransport();
  await transport.stream('https://example.test', 'test-token',
    JSON.stringify({message:'offline'}),e=>events.push(e));
  assert.deepEqual(events.map(e=>e.type),['run_started','answer_delta','done']);
  assert.equal(events[1].data.data,'雨☔');
  const last=observed.at(-1);
  assert.equal(last.url,'https://example.test/api/v1/chat/stream');
  assert.equal(last.opts.header.Authorization,'Bearer test-token');
});

test('truncated stream raises error rather than claiming done', async () => {
  queueScenario({chunks:[message('run_started',{session_id:'s1',run_generation:'g1'})]});
  await assert.rejects(new LflTransport().stream('https://example.test','',
    '{"message":"offline"}',()=>{}),/stream_ended_without_terminal_receipt/);
});

test('headers/paths for status, history, cancel stay scoped and bound',async()=>{
  queueScenario({body:JSON.stringify({running:true,run_generation:'g1'})});
  const bridge=new LflTransport();
  assert.deepEqual(await bridge.readStatus('https://example.test','','s1'),
    {running:true,run_generation:'g1'});
  queueScenario({body:JSON.stringify({session_id:'s1',messages:[{role:'assistant',content:'verified history'}]})});
  assert.equal((await bridge.readHistory('https://example.test','','s1')).messages[0].content,'verified history');
  queueScenario({body:JSON.stringify({cancelled:true})});
  const cancelled=await bridge.cancel('https://example.test','','{"session_id":"s1","run_generation":"g1"}');
  assert.equal(cancelled.status,200);
  assert.ok(observed.at(-1).opts.extraData.includes('"g1"'));
});

test('unknown status shape, foreign history identity, and unsafe origins fail closed',async()=>{
  queueScenario({body:'{}'});
  await assert.rejects(new LflTransport().readStatus('https://example.test','','s1'),/invalid_status_contract/);
  queueScenario({body:JSON.stringify({session_id:'other',messages:[]})});
  await assert.rejects(new LflTransport().readHistory('https://example.test','','s1'),/history_identity_mismatch/);
  assert.throws(()=>LflTransport.origin('https://token@example.test'),/explicit_https_origin_required/);
  assert.throws(()=>LflTransport.origin('http://localhost:8903'),/explicit_https_origin_required/);
});
