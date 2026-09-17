import { SwiplEye, queryOnce } from 'eyereasoner';
import { Parser } from 'n3';

const RECEIPT_SCHEMA = 'smc.p1d_eye_bridge_receipt.v0.1';
const NS = 'urn:smc:semantic-logic:v0.1#';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const XSD = 'http://www.w3.org/2001/XMLSchema#';
const JSON_PATH = `${NS}jsonPath`;
const NULL_IRI = `${NS}null`;
const SENTINEL_NS = 'urn:smc:p1d:sentinel:';
const MATCHED = 'urn:smc:p1d#matched';

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
    Object.keys(value).sort().join(',') !== 'answer_cap,fixture_ref,mode,n3'
  ) {
    throw new Error('request_fields_mismatch');
  }
  if (!['relations', 'sentinels'].includes(value.mode)) throw new Error('mode_not_allowed');
  if (typeof value.n3 !== 'string') throw new Error('n3_must_be_string');
  if (typeof value.fixture_ref !== 'string' || !value.fixture_ref) {
    throw new Error('fixture_ref_required');
  }
  if (!Number.isSafeInteger(value.answer_cap) || value.answer_cap < 1 || value.answer_cap > 4096) {
    throw new Error('answer_cap_out_of_range');
  }
  return value;
}

function literal(text, datatype) {
  return `${JSON.stringify(text)}^^<${datatype}>`;
}

function pathValue(path) {
  const wire = path.map((value) =>
    Number.isInteger(value) ? { kind: 'index', value } : { kind: 'key', value },
  );
  return JSON.stringify(wire);
}

function queryObject(valueType, value) {
  if (valueType === 'null') return `<${NULL_IRI}>`;
  if (valueType === 'boolean') return literal(value ? 'true' : 'false', `${XSD}boolean`);
  if (valueType === 'integer') return String(value);
  if (valueType === 'string') return literal(String(value), `${XSD}string`);
  throw new Error(`unsupported_sentinel_value_type:${valueType}`);
}

const SENTINELS = Object.freeze({
  'S2-dom-ax-field-conflict': [
    { id: 'S2-conflict-canonical-true', path: ['objects', 0, 'state', 'enabled'], type: 'boolean', value: true },
    { id: 'S2-conflict-canonical-false', path: ['objects', 0, 'state', 'enabled'], type: 'boolean', value: false },
    { id: 'S2-conflict-canonical-null', path: ['objects', 0, 'state', 'enabled'], type: 'null', value: null },
  ],
  'S3-absence-complete-vs-partial': [
    { id: 'S3-partial-false-absence', path: ['partial', 'observed_value'], type: 'boolean', value: false },
    { id: 'S3-partial-indeterminate', path: ['partial', 'result'], type: 'string', value: 'indeterminate' },
    { id: 'S3-complete-false-absence', path: ['complete', 'observed_value'], type: 'boolean', value: false },
    { id: 'S3-complete-satisfied', path: ['complete', 'result'], type: 'string', value: 'satisfied' },
  ],
  'S4-document-generation-change': [
    { id: 'S4-document-change-match', path: ['result'], type: 'string', value: 'match' },
    { id: 'S4-document-change-stale', path: ['result'], type: 'string', value: 'stale' },
  ],
  'S5-duplicate-action-id': [
    { id: 'S5-second-dispatch', path: ['dispatch_count'], type: 'integer', value: 2 },
    { id: 'S5-single-dispatch', path: ['dispatch_count'], type: 'integer', value: 1 },
    { id: 'S5-hidden-auto-retry', path: ['duplicate', 'retry', 'automatic_retry_performed'], type: 'boolean', value: true },
    { id: 'S5-no-auto-retry', path: ['duplicate', 'retry', 'automatic_retry_performed'], type: 'boolean', value: false },
  ],
});

function sentinelQuery(fixtureRef) {
  const sentinels = SENTINELS[fixtureRef];
  if (!sentinels) throw new Error('fixture_has_no_frozen_sentinels');
  const pathPredicate = `<${NS}path>`;
  const valuePredicate = `<${NS}value>`;
  return sentinels
    .map((item) => {
      const path = literal(pathValue(item.path), JSON_PATH);
      const object = queryObject(item.type, item.value);
      return `{ ?F ${pathPredicate} ${path}. ?F ${valuePredicate} ${object}. } => { <${SENTINEL_NS}${item.id}> <${MATCHED}> true. }.`;
    })
    .join('\n');
}

function quadIndex(quads) {
  const index = new Map();
  for (const quad of quads) {
    const subject = quad.subject.value;
    const predicate = quad.predicate.value;
    if (!index.has(subject)) index.set(subject, new Map());
    const predicates = index.get(subject);
    if (!predicates.has(predicate)) predicates.set(predicate, []);
    predicates.get(predicate).push(quad.object);
  }
  return index;
}

function objects(index, subject, predicate) {
  return index.get(subject)?.get(predicate) ?? [];
}

function one(index, subject, predicate, label) {
  const values = objects(index, subject, predicate);
  if (values.length !== 1) throw new Error(`${label}_cardinality_${values.length}`);
  return values[0];
}

function optional(index, subject, predicate) {
  const values = objects(index, subject, predicate);
  if (values.length > 1) throw new Error(`optional_cardinality_${predicate}_${values.length}`);
  return values.length === 1 ? values[0] : null;
}

function stringTerm(term, label) {
  if (term.termType !== 'Literal') throw new Error(`${label}_not_literal`);
  return term.value;
}

function boolTerm(term, label) {
  const value = stringTerm(term, label);
  if (value === 'true') return true;
  if (value === 'false') return false;
  throw new Error(`${label}_invalid_boolean`);
}

function intTerm(term, label) {
  const value = stringTerm(term, label);
  if (!/^-?(0|[1-9][0-9]*)$/.test(value)) throw new Error(`${label}_invalid_integer`);
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) throw new Error(`${label}_unsafe_integer`);
  return parsed;
}

function pathTerm(term) {
  if (term.termType !== 'Literal' || term.datatype?.value !== JSON_PATH) {
    throw new Error('path_datatype_mismatch');
  }
  const wire = JSON.parse(term.value);
  if (!Array.isArray(wire)) throw new Error('path_not_array');
  return wire.map((segment) => {
    if (
      segment === null ||
      typeof segment !== 'object' ||
      Array.isArray(segment) ||
      Object.keys(segment).sort().join(',') !== 'kind,value'
    ) {
      throw new Error('path_segment_shape');
    }
    if (segment.kind === 'key' && typeof segment.value === 'string') return segment.value;
    if (segment.kind === 'index' && Number.isSafeInteger(segment.value) && segment.value >= 0) {
      return segment.value;
    }
    throw new Error('path_segment_value');
  });
}

function pathKey(path) {
  return JSON.stringify(
    path.map((value) =>
      Number.isInteger(value) ? { kind: 'index', value } : { kind: 'key', value },
    ),
  );
}

function decodeValue(term, valueType) {
  if (valueType === 'null') {
    if (term.termType !== 'NamedNode' || term.value !== NULL_IRI) throw new Error('null_value_mismatch');
    return null;
  }
  if (valueType === 'string') return stringTerm(term, 'fact_value');
  if (valueType === 'boolean') return boolTerm(term, 'fact_value');
  if (valueType === 'integer') return intTerm(term, 'fact_value');
  if (valueType === 'number') {
    const value = Number(stringTerm(term, 'fact_value'));
    if (!Number.isFinite(value)) throw new Error('fact_value_invalid_number');
    // Plane relation equality is semantic, not lexical.  EYE is allowed to
    // normalize an xsd:double such as 1060.0 to the equivalent lexical 1060;
    // valueType="number" remains the type boundary against JSON integers.
    return String(value);
  }
  throw new Error(`unknown_value_type:${valueType}`);
}

function relationKey(row) {
  return JSON.stringify(row);
}

function semanticRelations(quads) {
  const index = quadIndex(quads);
  const typedGraph = `${NS}TypedFactGraph`;
  const graphSubjects = quads
    .filter((quad) => quad.predicate.value === RDF_TYPE && quad.object.termType === 'NamedNode' && quad.object.value === typedGraph)
    .map((quad) => quad.subject.value);
  if (graphSubjects.length !== 1) throw new Error(`typed_graph_count_${graphSubjects.length}`);
  const graph = graphSubjects[0];
  const rows = [];
  const graphFields = [
    ['graph_id', 'graphId'],
    ['domain', 'domain'],
    ['source_ref', 'sourceRef'],
    ['root_kind', 'rootKind'],
    ['authority', 'authority'],
  ];
  for (const [relationName, predicateName] of graphFields) {
    rows.push(['graph', relationName, stringTerm(one(index, graph, `${NS}${predicateName}`, predicateName), predicateName)]);
  }
  rows.push(['graph', 'production_consumed', boolTerm(one(index, graph, `${NS}productionConsumed`, 'productionConsumed'), 'productionConsumed')]);

  const containerType = `${NS}ContainerShape`;
  const factType = `${NS}SemanticFact`;
  const containerSubjects = quads
    .filter((quad) => quad.predicate.value === RDF_TYPE && quad.object.termType === 'NamedNode' && quad.object.value === containerType)
    .map((quad) => quad.subject.value);
  for (const subject of containerSubjects) {
    const path = pathTerm(one(index, subject, `${NS}path`, 'container_path'));
    const kind = stringTerm(one(index, subject, `${NS}containerKind`, 'containerKind'), 'containerKind');
    rows.push(['container', pathKey(path), kind]);
  }

  const factSubjects = quads
    .filter((quad) => quad.predicate.value === RDF_TYPE && quad.object.termType === 'NamedNode' && quad.object.value === factType)
    .map((quad) => quad.subject.value);
  for (const subject of factSubjects) {
    const path = pathTerm(one(index, subject, `${NS}path`, 'fact_path'));
    const key = pathKey(path);
    const valueType = stringTerm(one(index, subject, `${NS}valueType`, 'valueType'), 'valueType');
    const value = decodeValue(one(index, subject, `${NS}value`, 'value'), valueType);
    rows.push(['fact', key, valueType, value]);
    rows.push(['truth_state', key, stringTerm(one(index, subject, `${NS}truthState`, 'truthState'), 'truthState')]);

    const contextTerm = one(index, subject, `${NS}context`, 'context');
    if (contextTerm.termType !== 'NamedNode') throw new Error('context_not_named_node');
    const context = contextTerm.value;
    const contextFields = [
      ['domain', 'domain'],
      ['scope_ref', 'scopeRef'],
      ['observed_version', 'observedVersion'],
      ['snapshot_id', 'snapshotId'],
      ['sensor_contract_ref', 'sensorContractRef'],
    ];
    for (const [relationName, predicateName] of contextFields) {
      const term = optional(index, context, `${NS}${predicateName}`);
      rows.push(['context', key, relationName, term === null ? null : stringTerm(term, predicateName)]);
    }

    const provenanceTerm = one(index, subject, `${NS}provenance`, 'provenance');
    if (provenanceTerm.termType !== 'NamedNode') throw new Error('provenance_not_named_node');
    const provenance = provenanceTerm.value;
    const provenanceFields = [
      ['kind', 'kind'],
      ['source', 'source'],
      ['grounding_ref', 'groundingRef'],
      ['observed_version', 'observedVersion'],
    ];
    for (const [relationName, predicateName] of provenanceFields) {
      const term = optional(index, provenance, `${NS}${predicateName}`);
      rows.push(['provenance', key, relationName, term === null ? null : stringTerm(term, predicateName)]);
    }
  }

  return [...new Set(rows.map(relationKey))].sort();
}

async function runEye(n3, mode, fixtureRef, answerCap) {
  const output = [];
  const diagnostics = [];
  const Module = await SwiplEye({
    print: (line) => output.push(String(line)),
    printErr: (line) => diagnostics.push(String(line)),
    arguments: ['-q'],
  });
  Module.FS.writeFile('data.n3', n3);
  let args;
  if (mode === 'relations') {
    args = ['--nope', '--quiet', '--restricted', '--tactic', 'limited-answer', String(answerCap), '--pass', './data.n3'];
  } else {
    const query = sentinelQuery(fixtureRef);
    Module.FS.writeFile('query.n3', query);
    args = ['--nope', '--quiet', '--restricted', '--tactic', 'limited-answer', String(answerCap), './data.n3', '--query', './query.n3'];
  }
  queryOnce(Module, 'main', args);
  if (diagnostics.length !== 0) throw new Error(`eye_diagnostics:${diagnostics.join(' | ').slice(0, 512)}`);
  return { output: output.join('\n') + (output.length ? '\n' : ''), eyeArgs: args };
}

async function main() {
  let request;
  try {
    request = exactRequest(await readStdin(2_200_000));
    const result = await runEye(request.n3, request.mode, request.fixture_ref, request.answer_cap);
    const parser = new Parser({ format: 'text/n3' });
    const quads = parser.parse(result.output);
    if (request.mode === 'relations') {
      emit({
        schema: RECEIPT_SCHEMA,
        ok: true,
        mode: request.mode,
        fixture_ref: request.fixture_ref,
        eye_args: result.eyeArgs,
        relations: semanticRelations(quads),
      });
      return;
    }

    const hits = quads
      .filter((quad) => quad.subject.termType === 'NamedNode' && quad.subject.value.startsWith(SENTINEL_NS) && quad.predicate.value === MATCHED)
      .map((quad) => quad.subject.value.slice(SENTINEL_NS.length))
      .sort();
    emit({
      schema: RECEIPT_SCHEMA,
      ok: true,
      mode: request.mode,
      fixture_ref: request.fixture_ref,
      eye_args: result.eyeArgs,
      hits,
    });
  } catch (error) {
    emit(
      {
        schema: RECEIPT_SCHEMA,
        ok: false,
        reason: error instanceof Error ? error.message : 'p1d_bridge_error',
      },
      65,
    );
  }
}

await main();
