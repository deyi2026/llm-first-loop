import { createHash } from 'node:crypto';
import { SwiplEye, queryOnce } from 'eyereasoner';
import { Parser } from 'n3';

const RECEIPT_SCHEMA = 'smc.p2_g2_eye_bridge_receipt.v0.1';
const NS = 'urn:smc:p2:g2#';
const CASE = 'urn:smc:p2:g2:case';
const RESULT = 'urn:smc:p2:g2:result';
const MAX_SCOPE_NODES = 1024;
const MAX_SCOPE_DEPTH = 32;

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

function exactNullableString(value, field) {
  if (value === null) return null;
  if (typeof value !== 'string' || !value) throw new Error(`${field}_invalid`);
  return value;
}

function exactRequest(raw) {
  const value = JSON.parse(raw);
  if (
    value === null ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).sort().join(',') !==
      'answer_cap,case_ref,request_scope,scope_nodes,target_scope'
  ) {
    throw new Error('request_fields_mismatch');
  }
  if (typeof value.case_ref !== 'string' || !value.case_ref) throw new Error('case_ref_required');
  if (!Number.isSafeInteger(value.answer_cap) || value.answer_cap < 1 || value.answer_cap > 256) {
    throw new Error('answer_cap_out_of_range');
  }
  if (!Array.isArray(value.scope_nodes) || value.scope_nodes.length > MAX_SCOPE_NODES) {
    throw new Error('scope_nodes_invalid');
  }
  const seen = new Set();
  const scopeNodes = value.scope_nodes.map((rawNode) => {
    if (
      rawNode === null ||
      typeof rawNode !== 'object' ||
      Array.isArray(rawNode) ||
      Object.keys(rawNode).sort().join(',') !== 'kind,parent_scope_ref,scope_ref'
    ) {
      throw new Error('scope_node_fields_mismatch');
    }
    const scopeRef = exactNullableString(rawNode.scope_ref, 'scope_ref');
    if (scopeRef === null) throw new Error('scope_ref_required');
    const kind = exactNullableString(rawNode.kind, 'kind');
    if (kind === null) throw new Error('kind_required');
    const parentScopeRef = exactNullableString(rawNode.parent_scope_ref, 'parent_scope_ref');
    if (seen.has(scopeRef)) throw new Error('duplicate_scope_ref');
    seen.add(scopeRef);
    return { scope_ref: scopeRef, parent_scope_ref: parentScopeRef, kind };
  });
  return {
    answer_cap: value.answer_cap,
    case_ref: value.case_ref,
    request_scope: exactNullableString(value.request_scope, 'request_scope'),
    target_scope: exactNullableString(value.target_scope, 'target_scope'),
    scope_nodes: scopeNodes,
  };
}

function validateGraph(nodes) {
  const parents = new Map(nodes.map((node) => [node.scope_ref, node.parent_scope_ref]));
  for (const start of parents.keys()) {
    const seen = new Set([start]);
    let current = start;
    let depth = 0;
    while (true) {
      const parent = parents.get(current);
      if (parent === null || parent === undefined || !parents.has(parent)) break;
      depth += 1;
      if (depth > MAX_SCOPE_DEPTH) {
        return { status: 'rejected', reason: 'max_scope_depth_exceeded' };
      }
      if (seen.has(parent)) return { status: 'rejected', reason: 'scope_graph_cycle' };
      seen.add(parent);
      current = parent;
    }
  }
  return { status: 'accepted', reason: null };
}

function lit(value) {
  return JSON.stringify(value);
}

function dataDocument(request) {
  const rows = [];
  const sortedNodes = [...request.scope_nodes].sort((left, right) =>
    left.scope_ref.localeCompare(right.scope_ref),
  );
  for (let index = 0; index < sortedNodes.length; index += 1) {
    const node = sortedNodes[index];
    const subject = `urn:smc:p2:g2:node:${index}`;
    rows.push(`<${subject}> <${NS}scopeRef> ${lit(node.scope_ref)}.`);
    rows.push(`<${subject}> <${NS}kind> ${lit(node.kind)}.`);
    if (node.parent_scope_ref !== null) {
      rows.push(`<${subject}> <${NS}parentScopeRef> ${lit(node.parent_scope_ref)}.`);
    }
  }
  const observed = new Set(request.scope_nodes.map((node) => node.scope_ref));
  rows.push(
    `<${CASE}> <${NS}requestObserved> ${lit(
      request.request_scope !== null && observed.has(request.request_scope) ? 'true' : 'false',
    )}.`,
  );
  rows.push(
    `<${CASE}> <${NS}targetObserved> ${lit(
      request.target_scope !== null && observed.has(request.target_scope) ? 'true' : 'false',
    )}.`,
  );
  if (request.request_scope !== null) {
    rows.push(`<${CASE}> <${NS}requestScope> ${lit(request.request_scope)}.`);
  }
  if (request.target_scope !== null) {
    rows.push(`<${CASE}> <${NS}targetScope> ${lit(request.target_scope)}.`);
  }
  return `${rows.join('\n')}\n`;
}

const RULES = `{
  ?C <${NS}scopeRef> ?Child.
  ?C <${NS}parentScopeRef> ?Parent.
} => {
  ?C <${NS}descendantRef> ?Parent.
}.
{
  ?C <${NS}descendantRef> ?Middle.
  ?M <${NS}scopeRef> ?Middle.
  ?M <${NS}parentScopeRef> ?Ancestor.
} => {
  ?C <${NS}descendantRef> ?Ancestor.
}.
{
  <${CASE}> <${NS}requestObserved> "true".
  <${CASE}> <${NS}targetObserved> "true".
  <${CASE}> <${NS}requestScope> ?Scope.
  <${CASE}> <${NS}targetScope> ?Scope.
} => {
  <${CASE}> <${NS}scopeRelation> "match".
  <${CASE}> <${NS}scopeReason> "exact_scope".
}.
{
  <${CASE}> <${NS}requestObserved> "true".
  <${CASE}> <${NS}targetObserved> "true".
  <${CASE}> <${NS}requestScope> ?Request.
  <${CASE}> <${NS}targetScope> ?Target.
  ?Request <http://www.w3.org/2000/10/swap/log#notEqualTo> ?Target.
} => {
  <${CASE}> <${NS}scopeRelation> "mismatch".
  <${CASE}> <${NS}scopeReason> "target_scope_mismatch".
}.
{
  <${CASE}> <${NS}requestObserved> "false".
} => {
  <${CASE}> <${NS}scopeRelation> "indeterminate".
  <${CASE}> <${NS}scopeReason> "scope_unobserved".
}.
{
  <${CASE}> <${NS}targetObserved> "false".
} => {
  <${CASE}> <${NS}scopeRelation> "indeterminate".
  <${CASE}> <${NS}scopeReason> "scope_unobserved".
}.`;

const QUERY = `{
  ?C <${NS}scopeRef> ?Child.
  ?C <${NS}descendantRef> ?Ancestor.
} => {
  ?C <${NS}queryScopeRef> ?Child.
  ?C <${NS}queryDescendantRef> ?Ancestor.
}.
{
  <${CASE}> <${NS}scopeRelation> ?Value.
} => {
  <${RESULT}> <${NS}scopeRelation> ?Value.
}.
{
  <${CASE}> <${NS}scopeReason> ?Value.
} => {
  <${RESULT}> <${NS}scopeReason> ?Value.
}.`;

async function runEye(request) {
  const output = [];
  const diagnostics = [];
  const Module = await SwiplEye({
    print: (line) => output.push(String(line)),
    printErr: (line) => diagnostics.push(String(line)),
    arguments: ['-q'],
  });
  Module.FS.writeFile('data.n3', dataDocument(request));
  Module.FS.writeFile('rules.n3', RULES);
  Module.FS.writeFile('query.n3', QUERY);
  const args = [
    '--nope',
    '--quiet',
    '--restricted',
    '--tactic',
    'limited-answer',
    String(request.answer_cap),
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

function decode(text) {
  const parser = new Parser({ format: 'text/n3' });
  const quads = parser.parse(text);
  const relations = [];
  const scopeBySubject = new Map();
  const ancestorsBySubject = new Map();
  for (const quad of quads) {
    if (quad.object.termType !== 'Literal') throw new Error('g2_output_not_literal');
    if (quad.subject.termType === 'NamedNode' && quad.subject.value === RESULT) {
      if (!quad.predicate.value.startsWith(NS)) continue;
      const predicate = quad.predicate.value.slice(NS.length);
      if (predicate === 'scopeRelation' || predicate === 'scopeReason') {
        relations.push([predicate, quad.object.value]);
      }
      continue;
    }
    if (quad.subject.termType !== 'NamedNode' || !quad.predicate.value.startsWith(NS)) continue;
    const predicate = quad.predicate.value.slice(NS.length);
    if (predicate === 'queryScopeRef') scopeBySubject.set(quad.subject.value, quad.object.value);
    if (predicate === 'queryDescendantRef') {
      const values = ancestorsBySubject.get(quad.subject.value) || [];
      values.push(quad.object.value);
      ancestorsBySubject.set(quad.subject.value, values);
    }
  }
  const descendants = [];
  for (const [subject, child] of scopeBySubject.entries()) {
    for (const ancestor of ancestorsBySubject.get(subject) || []) {
      descendants.push([child, ancestor]);
    }
  }
  const uniqueRows = (rows) =>
    [...new Map(rows.map((row) => [JSON.stringify(row), row])).values()].sort((left, right) =>
      JSON.stringify(left).localeCompare(JSON.stringify(right)),
    );
  return { relations: uniqueRows(relations), descendants: uniqueRows(descendants) };
}

async function main() {
  try {
    const request = exactRequest(await readStdin(262_144));
    const validation = validateGraph(request.scope_nodes);
    if (validation.status === 'rejected') {
      emit({
        schema: RECEIPT_SCHEMA,
        ok: true,
        case_ref: request.case_ref,
        validation_status: validation.status,
        validation_reason: validation.reason,
        eye_args: [],
        rules_sha256: sha256Hex(RULES),
        query_sha256: sha256Hex(QUERY),
        relations: [],
        descendants: [],
      });
      return;
    }
    const result = await runEye(request);
    const decoded = decode(result.output);
    emit({
      schema: RECEIPT_SCHEMA,
      ok: true,
      case_ref: request.case_ref,
      validation_status: 'accepted',
      validation_reason: null,
      eye_args: result.args,
      rules_sha256: sha256Hex(RULES),
      query_sha256: sha256Hex(QUERY),
      relations: decoded.relations,
      descendants: decoded.descendants,
    });
  } catch (error) {
    emit(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: error instanceof Error ? error.message : 'p2_g2_bridge_error',
      },
      65,
    );
  }
}

await main();
