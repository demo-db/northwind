// The stored-value check of scripts/lib/meaning.mjs (valueCoverageProblems) reads a meaning file by its own format:
// the bound column is `property:` in meaning/draft-1 and `field:` in meaning/draft-2, and a file of any other
// format is reported instead of being passed unread. The graphs here are made in memory.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { indexConcepts, loadMeaningDir, valueCoverageProblems } from './lib/meaning.mjs';

const noResolve = () => ({ error: 'no other repository in these tests' });
const kinds = { 'meaning/draft-1': 'attribute', 'meaning/draft-2': 'property' };
const keys = { 'meaning/draft-1': 'property', 'meaning/draft-2': 'field' };

// A one-file graph: a list of known values (an entity in draft-1, a value set in draft-2) and a property that
// holds them through the column `Status.state`.
function graph(format, { fieldKey = keys[format], listKind = format === 'meaning/draft-1' ? 'entity' : 'value-set' } = {}) {
  const doc = {
    format,
    id: 'orders',
    name: 'Orders',
    description: 'Test graph.',
    concepts: [
      { id: 'state-list', kind: listKind, labels: { en: 'State' }, description: 'States.', values: [{ id: 'open', labels: { en: 'Open' } }, { id: 'shipped', labels: { en: 'Shipped' }, aliases: { en: ['S'] } }] },
      { id: 'state', kind: kinds[format] ?? 'property', labels: { en: 'state' }, description: 'The state of an order.', 'values-of': 'state-list', bindings: [{ model: 'modelspec:///orders.Status', role: 'value', [fieldKey]: 'state' }] },
    ],
  };
  return indexConcepts([{ path: 'orders.meaning.yaml', doc }]);
}
const data = (...states) => ({ Status: states.map((state) => ({ state })) });
const check = (local, rows) => valueCoverageProblems({ local, resolve: noResolve, data: rows });

test('meaning/draft-1: a stored value that names a known value passes, and one that does not is reported through property:', () => {
  assert.deepEqual(check(graph('meaning/draft-1'), data('Open', 'S', null)), []);
  assert.deepEqual(check(graph('meaning/draft-1'), data('Open', 'lost')), ['orders.meaning.yaml: concept state: Status.state value "lost" matches no value']);
});

test('meaning/draft-2: the bound column is read from field:, so a stored value that names no known value is reported', () => {
  assert.deepEqual(check(graph('meaning/draft-2'), data('Open', 'S', null)), []);
  assert.deepEqual(check(graph('meaning/draft-2'), data('Open', 'lost')), ['orders.meaning.yaml: concept state: Status.state value "lost" matches no value']);
});

test('each format reads only its own key: property: in a draft-2 file and field: in a draft-1 file name no column', () => {
  assert.deepEqual(check(graph('meaning/draft-2', { fieldKey: 'property' }), data('lost')), []);
  assert.deepEqual(check(graph('meaning/draft-1', { fieldKey: 'field' }), data('lost')), []);
});

test('a file of an unknown format is reported once and its bindings are not checked', () => {
  const problem = (shown) => `orders.meaning.yaml: format must be meaning/draft-1 or meaning/draft-2, got ${shown}; its bindings are not checked`;
  for (const [format, shown] of [['meaning/draft-3', '"meaning/draft-3"'], [undefined, 'no format'], [['meaning/draft-1'], '["meaning/draft-1"]'], ['__proto__', '"__proto__"']]) {
    const local = graph('meaning/draft-2');
    local.files[0].doc.format = format;
    assert.deepEqual(check(local, data('lost')), [problem(shown)], `format ${shown}`);
  }
  const empty = indexConcepts([{ path: 'empty.meaning.yaml', doc: null }]);
  assert.deepEqual(check(empty, {}), ['empty.meaning.yaml: format must be meaning/draft-1 or meaning/draft-2, got no format; its bindings are not checked']);
});

test('the files of a graph are read each by its own format', () => {
  const one = graph('meaning/draft-1').files[0];
  const two = graph('meaning/draft-2').files[0];
  two.path = 'orders2.meaning.yaml';
  two.doc.concepts = two.doc.concepts.map((concept) => ({ ...concept, id: `${concept.id}-two`, 'values-of': concept['values-of'] && `${concept['values-of']}-two` }));
  const local = indexConcepts([one, two]);
  assert.deepEqual(check(local, data('lost')), [
    'orders.meaning.yaml: concept state: Status.state value "lost" matches no value',
    'orders2.meaning.yaml: concept state-two: Status.state value "lost" matches no value',
  ]);
});

test("this repository's own meaning file is meaning/draft-1 and passes with no data", () => {
  const local = loadMeaningDir(fileURLToPath(new URL('../model', import.meta.url)));
  assert.equal(local.files.length, 1);
  assert.equal(local.files[0].doc.format, 'meaning/draft-1');
  assert.deepEqual(check(local, {}), []);
});
