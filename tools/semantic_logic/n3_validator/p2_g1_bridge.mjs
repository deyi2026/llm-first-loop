import { createHash } from 'node:crypto';
import { SwiplEye, queryOnce } from 'eyereasoner';
import { Parser } from 'n3';

const RECEIPT_SCHEMA = 'smc.p2_g1_eye_bridge_receipt.v0.1';
const NS = 'urn:smc:p2:g1#';
const CASE = 'urn:smc:p2:g1:case';
const RESULT = 'urn:smc:p2:g1:result';

const INPUT_KEYS = Object.freeze([
  'availability',
  'grounding_kind',
  'grounding_ref',
  'observed_version',
  'projection_ref',
  'scope_ref',
  'target_id',
  'target_ref',
  'verb',
]);

const OUTPUT_PREDICATES = Object.freeze([
  'bindingStatus',
  'versionScope',
  'actionSchema',
  'actionDomain',
  'actionScopeRef',
  'actionVerb',
  'actionTargetId',
  'operationClass',
  'idempotencyClass',
  'atomicityClass',
  'actionExpectedVersion',
  'actionVersionScope',
  'actionVersionPrecondition',
]);

function sha256Hex(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

async function readStdin(maxBytes) {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > maxBytes) throw new Error('bridge_request_too_large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

function emit(value, code = 0) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
  process.exitCode = code;
}

function exactRequest(raw) {
  const value = JSON.parse(raw);
  if (
    value === null ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).sort().join(',') !== 'answer_cap,case_ref,values'
  ) {
    throw new Error('request_fields_mismatch');
  }
  if (typeof value.case_ref !== 'string' || !value.case_ref) throw new Error('case_ref_required');
  if (!Number.isSafeInteger(value.answer_cap) || value.answer_cap < 1 || value.answer_cap > 256) {
    throw new Error('answer_cap_out_of_range');
  }
  if (
    value.values === null ||
    typeof value.values !== 'object' ||
    Array.isArray(value.values) ||
    Object.keys(value.values).sort().join(',') !== [...INPUT_KEYS].sort().join(',')
  ) {
    throw new Error('values_fields_mismatch');
  }
  for (const key of INPUT_KEYS) {
    if (typeof value.values[key] !== 'string') throw new Error(`value_not_string:${key}`);
  }
  return value;
}

function lit(value) {
  return JSON.stringify(value);
}

function dataDocument(values) {
  const mapping = [
    ['targetRef', 'target_ref'],
    ['verb', 'verb'],
    ['availability', 'availability'],
    ['groundingRef', 'grounding_ref'],
    ['kind', 'grounding_kind'],
    ['projectionRef', 'projection_ref'],
    ['targetId', 'target_id'],
    ['scopeRef', 'scope_ref'],
    ['observedVersion', 'observed_version'],
  ];
  return mapping
    .map(([predicate, key]) => `<${CASE}> <${NS}${predicate}> ${lit(values[key])}.`)
    .join('\n') + '\n';
}

function successRule({ verb, kind, versionScope, resource = false }) {
  const targetPattern = resource
    ? `<${CASE}> <${NS}targetId> ?S.\n  <${CASE}> <${NS}scopeRef> ?S.`
    : `<${CASE}> <${NS}targetId> ?T.\n  <${CASE}> <${NS}scopeRef> ?S.`;
  const targetOutput = resource ? '?S' : '?T';
  const nonemptyTarget = resource
    ? `?S <http://www.w3.org/2000/10/swap/log#notEqualTo> "".`
    : `?T <http://www.w3.org/2000/10/swap/log#notEqualTo> "".\n  ?S <http://www.w3.org/2000/10/swap/log#notEqualTo> "".`;
  return `{
  <${CASE}> <${NS}availability> "available".
  <${CASE}> <${NS}targetRef> ?R.
  <${CASE}> <${NS}groundingRef> ?R.
  <${CASE}> <${NS}projectionRef> ?R.
  <${CASE}> <${NS}kind> "${kind}".
  <${CASE}> <${NS}verb> "${verb}".
  ${targetPattern}
  <${CASE}> <${NS}observedVersion> ?V.
  ?R <http://www.w3.org/2000/10/swap/log#notEqualTo> "".
  ${nonemptyTarget}
  ?V <http://www.w3.org/2000/10/swap/log#notEqualTo> "".
} => {
  <${CASE}> <${NS}bindingStatus> "bound".
  <${CASE}> <${NS}versionScope> "${versionScope}".
  <${CASE}> <${NS}actionSchema> "smc.semantic_action.v0.1".
  <${CASE}> <${NS}actionDomain> "browser".
  <${CASE}> <${NS}actionScopeRef> ?S.
  <${CASE}> <${NS}actionVerb> "${verb}".
  <${CASE}> <${NS}actionTargetId> ${targetOutput}.
  <${CASE}> <${NS}operationClass> "mutate".
  <${CASE}> <${NS}idempotencyClass> "unknown".
  <${CASE}> <${NS}atomicityClass> "single_dispatch".
  <${CASE}> <${NS}actionExpectedVersion> ?V.
  <${CASE}> <${NS}actionVersionScope> "${versionScope}".
  <${CASE}> <${NS}actionVersionPrecondition> "required".
}.`;
}

const RULES = [
  successRule({ verb: 'click', kind: 'object', versionScope: 'object' }),
  successRule({ verb: 'fill', kind: 'object', versionScope: 'object' }),
  successRule({ verb: 'select', kind: 'object', versionScope: 'object' }),
  successRule({ verb: 'scroll', kind: 'object', versionScope: 'object' }),
  successRule({ verb: 'navigate', kind: 'resource', versionScope: 'resource', resource: true }),
].join('\n');

const QUERY = OUTPUT_PREDICATES
  .map((predicate) => `{ <${CASE}> <${NS}${predicate}> ?O. } => { <${RESULT}> <${NS}${predicate}> ?O. }.`)
  .join('\n');

async function runEye(values, answerCap) {
  const output = [];
  const diagnostics = [];
  const Module = await SwiplEye({
    print: (line) => output.push(String(line)),
    printErr: (line) => diagnostics.push(String(line)),
    arguments: ['-q'],
  });
  Module.FS.writeFile('data.n3', dataDocument(values));
  Module.FS.writeFile('rules.n3', RULES);
  Module.FS.writeFile('query.n3', QUERY);
  const args = [
    '--nope',
    '--quiet',
    '--restricted',
    '--tactic',
    'limited-answer',
    String(answerCap),
    './data.n3',
    './rules.n3',
    '--query',
    './query.n3',
  ];
  queryOnce(Module, 'main', args);
  if (diagnostics.length !== 0) {
    throw new Error(`eye_diagnostics:${diagnostics.join(' | ').slice(0, 512)}`);
  }
  return { output: output.join('\n') + (output.length ? '\n' : ''), args };
}

function decodeRelations(text) {
  const parser = new Parser({ format: 'text/n3' });
  const quads = parser.parse(text);
  const rows = [];
  for (const quad of quads) {
    if (quad.subject.termType !== 'NamedNode' || quad.subject.value !== RESULT) continue;
    if (quad.predicate.termType !== 'NamedNode' || !quad.predicate.value.startsWith(NS)) continue;
    if (quad.object.termType !== 'Literal') throw new Error('g1_output_not_literal');
    rows.push([quad.predicate.value.slice(NS.length), quad.object.value]);
  }
  rows.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  return rows;
}

async function main() {
  try {
    const request = exactRequest(await readStdin(131_072));
    const result = await runEye(request.values, request.answer_cap);
    emit({
      schema: RECEIPT_SCHEMA,
      ok: true,
      case_ref: request.case_ref,
      eye_args: result.args,
      rules_sha256: sha256Hex(RULES),
      query_sha256: sha256Hex(QUERY),
      relations: decodeRelations(result.output),
    });
  } catch (error) {
    emit(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: error instanceof Error ? error.message : 'p2_g1_bridge_error',
      },
      65,
    );
  }
}

await main();
