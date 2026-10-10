import test from 'node:test';
import assert from 'node:assert/strict';
import {
  LflSseParser, resumeDecision, resumePayload, cancellationPayload,
  artifactCandidates, historyAnswer
} from '../entry/src/main/ets/bridge/StreamProtocol.ts';

const event = (type, data) => `data: ${JSON.stringify({type, data})}\n\n`;

test('fragmented frames, id binding, UTF-8 split at multibyte boundary and terminal', () => {
  const raw = event('run_started', {session_id:'s1',run_generation:'g1'}) +
    event('answer_delta',{data:'汉🌿'}) +
    event('done',{session_id:'s1',final_answer:'汉🌿',run_incomplete:false});
  const bytes = new TextEncoder().encode(raw);
  const decoder = new TextDecoder('utf-8');
  const parser = new LflSseParser();
  let events = [];
  for (const b of bytes) {
    events.push(...parser.push(decoder.decode(new Uint8Array([b]), {stream:true})));
  }
  events.push(...parser.push(decoder.decode()));
  assert.deepEqual(events.map(x => x.type), ['run_started','answer_delta','done']);
  assert.deepEqual(events[0].data,{session_id:'s1',run_generation:'g1'});
  assert.equal(events[1].data.data, '汉🌿');
  assert.equal(parser.hasTerminal(), true);
  assert.equal(parser.push(event('answer_delta',{data:'late'})).length, 0);
});

test('split source without trailing blank line remains nonterminal', () => {
  const p = new LflSseParser();
  assert.equal(p.push('data: {"type":"done","data":{"final_answer":"a"}}\n').length, 0);
  assert.equal(p.hasTerminal(), false);
  assert.equal(p.push('\n').length, 1);
  assert.equal(p.hasTerminal(), true);
});

test('invalid frame and missing run identity reject rather than silently succeed', () => {
  assert.throws(() => new LflSseParser().push('data: broken\n\n'), /malformed_sse_event/);
  assert.throws(() => new LflSseParser().push(event('run_started',{session_id:'s1'})), /run_identity_missing/);
  assert.throws(() => new LflSseParser().push('x'.repeat(1024 * 1024 + 1)), /sse_frame_too_large/);
  assert.equal(new LflSseParser().push(event('error',{error:'no_active_run'}))[0].type,'error');
});

test('resume binds exact run and never sends a new human turn', () => {
  assert.equal(resumeDecision({running:true,run_generation:'g1'},'g1'),'resume');
  assert.equal(resumeDecision({running:true,run_generation:'g2'},'g1'),'generation_mismatch');
  assert.equal(resumeDecision({running:true},'g1'),'unknown');
  assert.equal(resumeDecision({running:false},'g1'),'history');
  assert.deepEqual(JSON.parse(resumePayload('s1','g1')),
    {message:'resume',session_id:'s1',resume:true,run_generation:'g1'});
  assert.throws(() => resumePayload('s1',''), /resume_requires_exact_identity/);
});

test('cancel must specify exact session and run generation', () => {
  assert.deepEqual(JSON.parse(cancellationPayload('s1','g1')),
    {session_id:'s1',run_generation:'g1'});
  assert.throws(() => cancellationPayload('s1',''), /cancel_requires_exact_identity/);
});

test('artifact refs are only unverified candidates, deduplicated and shape checked', () => {
  const valid='artifact://v1/' + 'a'.repeat(32);
  const vals=artifactCandidates(valid + ', ' + valid + '; artifact://v1/' +
    'b'.repeat(31) + ' and artifact://v1/'+'c'.repeat(33), 'done');
  assert.deepEqual(vals,[{ref:valid,source:'done',verification:'unverified_ref'}]);
});

test('history result uses last nonempty assistant text without inventing run outcome', () => {
  assert.equal(historyAnswer({session_id:'s1',messages:[
    {role:'assistant',content:'older'},
    {role:'user',content:'next'},
    {role:'assistant',content:''},
    {role:'assistant',content:'latest'}
  ]}), 'latest');
  assert.equal(historyAnswer({session_id:'s1',messages:[{role:'user',content:'x'}]}),'');
});
