// scripts/generate-public-manifest.mjs reads the publisher manifest ovdb.yaml in either of its two forms
// (ovdb-manifest/draft-1: a list of names and recordset_entities; ovdb-manifest/draft-2: items with record_type and
// columns). It is a script, so each case runs it in a scratch copy of the files it reads, with this repository's
// node_modules linked in, and reads what it wrote.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml';

const repo = fileURLToPath(new URL('..', import.meta.url));
const scratch = mkdtempSync(join(tmpdir(), 'public-manifest-'));
after(() => rmSync(scratch, { recursive: true, force: true }));
let count = 0;

// A scratch root with the files the generator reads, `ovdb.yaml` replaced by `provider` (an object) when given.
function fixture(provider) {
  const root = join(scratch, String(count++));
  mkdirSync(join(root, 'scripts/lib'), { recursive: true });
  mkdirSync(join(root, 'metadata'));
  mkdirSync(join(root, 'schemas'));
  for (const file of ['scripts/generate-public-manifest.mjs', 'scripts/lib/manifest-mapping.mjs', 'manifest.json', 'ovdb.yaml', 'metadata/schema.json', 'metadata/checksums.json', 'schemas/ovdb-database-draft-1.schema.json']) cpSync(join(repo, file), join(root, file));
  symlinkSync(join(repo, 'node_modules'), join(root, 'node_modules'));
  if (provider) writeFileSync(join(root, 'ovdb.yaml'), stringifyYaml(provider));
  return root;
}
const providerOf = () => parseYaml(readFileSync(join(repo, 'ovdb.yaml'), 'utf8'));
const run = (root, ...args) => execFileSync(process.execPath, [join(root, 'scripts/generate-public-manifest.mjs'), ...args], { stdio: 'pipe' }).toString();
const failure = (root) => { try { run(root); } catch (error) { return String(error.stderr); } return null; };
const output = (root) => ({ descriptor: readFileSync(join(root, 'ovdb-database.json'), 'utf8'), checksums: readFileSync(join(root, 'metadata/checksums.json'), 'utf8') });

// Today's manifest in the second form: Order Details is the one recordset whose record type differs from its name.
function draft2() {
  const provider = providerOf();
  provider.format = 'ovdb-manifest/draft-2';
  provider.recordsets = provider.recordsets.map((name) => (provider.recordset_entities[name] ? { name, record_type: provider.recordset_entities[name] } : name));
  delete provider.recordset_entities;
  return provider;
}
const modelEntities = (root) => run(root) && Object.fromEntries(JSON.parse(output(root).descriptor).recordsets.map((recordset) => [recordset.name, recordset.modelEntity]));

test("today's manifest (ovdb-manifest/draft-1 with recordset_entities) gives the committed descriptor and checksums, byte for byte", () => {
  assert.equal(providerOf().format, 'ovdb-manifest/draft-1');
  const root = fixture();
  run(root);
  const committed = { descriptor: readFileSync(join(repo, 'ovdb-database.json'), 'utf8'), checksums: readFileSync(join(repo, 'metadata/checksums.json'), 'utf8') };
  assert.deepEqual(output(root), committed);
  assert.match(run(root, '--check'), /Validated schema/);
});

test('the same manifest written as ovdb-manifest/draft-2 gives the same bytes, and its columns mapping is read without changing them', () => {
  const plain = fixture();
  run(plain);
  const root = fixture(draft2());
  run(root);
  assert.deepEqual(output(root), output(plain));
  const mapped = draft2();
  mapped.recordsets = mapped.recordsets.map((item) => (item.name === 'Order Details' ? { ...item, columns: { Quantity: { field: 'Quantity' }, Discount: { field: 'Discount' } } } : item));
  const withColumns = fixture(mapped);
  run(withColumns);
  assert.deepEqual(output(withColumns), output(plain));
});

test('draft-2: the record_type of an item is the record type of the recordset, and a bare name has the record type of its own name', () => {
  const provider = draft2();
  provider.recordsets = provider.recordsets.map((item) => (item.name === 'Order Details' ? { ...item, record_type: 'Lines' } : item));
  const entities = modelEntities(fixture(provider));
  assert.equal(entities['Order Details'], 'Lines');
  assert.equal(entities.Orders, 'Orders');
});

test('draft-1: a recordset_entities pair is the record type, and a recordset it does not list keeps the generated metadata', () => {
  const provider = providerOf();
  provider.recordset_entities = { 'Order Details': 'Lines' };
  const entities = modelEntities(fixture(provider));
  assert.equal(entities['Order Details'], 'Lines');
  assert.equal(entities.Orders, 'Orders');
  delete provider.recordset_entities;
  assert.equal(modelEntities(fixture(provider))['Order Details'], 'OrderDetails');
});

test('a manifest it cannot read in one form is refused, not half read', () => {
  const cases = [
    ['an unknown format', (p) => { p.format = 'ovdb-manifest/draft-3'; }, /format must be ovdb-manifest\/draft-1 or ovdb-manifest\/draft-2/],
    ['no format', (p) => { delete p.format; }, /format must be/],
    ['a map item under draft-1', (p) => { p.recordsets[6] = { name: 'Order Details', record_type: 'OrderDetails' }; delete p.recordset_entities; }, /recordsets item 7 is a map, but ovdb-manifest\/draft-1 lists recordsets by name only/],
    ['recordset_entities beside a map item under draft-2', (p) => { Object.assign(p, draft2(), { recordset_entities: { 'Order Details': 'OrderDetails' } }); }, /recordset_entities and record_type both state the mapping/],
    ['recordset_entities alone under draft-2', (p) => { Object.assign(p, draft2(), { recordsets: providerOf().recordsets, recordset_entities: { 'Order Details': 'OrderDetails' } }); }, /recordset_entities is not read under format: ovdb-manifest\/draft-2/],
    ['a column written as text', (p) => { Object.assign(p, draft2()); p.recordsets[6] = { name: 'Order Details', record_type: 'OrderDetails', columns: { Quantity: 'Quantity' } }; }, /column "Quantity" must be a map with field:/],
    ['two recordsets of one record type', (p) => { Object.assign(p, draft2()); p.recordsets[0] = { name: 'Categories', record_type: 'Orders' }; }, /both have the record type Orders/],
    ['an item with an unknown key', (p) => { Object.assign(p, draft2()); p.recordsets[0] = { name: 'Categories', columnz: {} }; }, /an item reads only name, record_type and columns/],
  ];
  for (const [label, change, message] of cases) {
    const provider = providerOf();
    change(provider);
    const stderr = failure(fixture(provider));
    assert.ok(stderr, `${label}: the generator must stop`);
    assert.match(stderr, message, label);
    assert.match(stderr, /northwind: ovdb\.yaml: /, label);
  }
});

test('a recordset that is not a generated table is still refused in both forms', () => {
  const one = providerOf();
  one.recordsets[0] = 'Nothing';
  assert.match(failure(fixture(one)), /served recordset "Nothing" is not a generated table/);
  const two = draft2();
  two.recordsets[0] = { name: 'Nothing' };
  assert.match(failure(fixture(two)), /served recordset "Nothing" is not a generated table/);
});
