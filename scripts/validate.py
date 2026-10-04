#!/usr/bin/env python3
"""Check generated Northwind contract, SQLite integrity, keys, relationships and downloads."""
import csv, gzip, hashlib, json, sqlite3, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
contract = json.loads((ROOT / 'metadata/contract.json').read_text())
manifest = json.loads((ROOT / 'manifest.json').read_text())
db_path = ROOT / manifest['dataFile']
db = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
db.row_factory = sqlite3.Row
assert hashlib.sha256(db_path.read_bytes()).hexdigest() == manifest['source']['databaseSha256'], 'pinned imported SQLite hash differs'
schema = contract['schema']
objects = {(r['type'], r['name']) for r in db.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")}
expected = {(t['kind'], t['name']) for t in schema['tables']}
assert objects == expected, f'schema objects differ: expected {expected ^ objects}'
tables = {t['name']: t for t in schema['tables']}
for name, meta in tables.items():
    quoted = '"' + name.replace('"', '""') + '"'
    columns = db.execute(f'PRAGMA table_info({quoted})').fetchall() if meta['kind'] == 'table' else db.execute(f'SELECT * FROM {quoted} LIMIT 0').description
    names = [c['name'] if meta['kind'] == 'table' else c[0] for c in columns]
    assert names == [c['name'] for c in meta['columns']], f'{name}: column order differs'
    count = db.execute(f'SELECT count(*) FROM {quoted}').fetchone()[0]
    assert count == meta['rowCount'], f'{name}: row count differs ({count} != {meta["rowCount"]})'
    if meta['kind'] != 'table': continue
    pk = [(c['name'], c['pk']) for c in columns if c['pk']]
    assert pk == [(c['name'], c['primaryKeyPosition']) for c in meta['columns'] if c['primaryKey']], f'{name}: primary key order differs'
    fks = [{'column': r['from'], 'table': r['table'], 'referencedColumn': r['to'], 'constraint': r['id'], 'position': r['seq']} for r in db.execute(f'PRAGMA foreign_key_list({quoted})')]
    assert fks == meta['foreignKeys'], f'{name}: foreign keys differ'
    csv_file = ROOT / 'artifacts/data' / f'{name}.csv'
    with csv_file.open(newline='', encoding='utf-8') as f:
        assert sum(1 for _ in csv.reader(f)) == count + 1, f'{name}: CSV record count differs'
    json_rows = json.loads((ROOT / 'artifacts/data' / f'{name}.json').read_text())
    assert len(json_rows) == count, f'{name}: JSON record count differs'

detail = tables['Order Details']
assert [c['name'] for c in sorted(detail['columns'], key=lambda c: c['primaryKeyOrder']) if c['primaryKey']] == ['OrderID', 'ProductID']
concepts = {concept['id']: concept for concept in json.loads((ROOT / 'model/northwind.meaning.yaml').read_text())['concepts']}
core_pin = '982916d73f0a35ff2558b0062f58aa3ac4f24d97'
assert concepts['order']['extends'] == f'meaning://github.com/meaninggraph/core/order?ref={core_pin}'
assert concepts['order-line']['of'] == 'order'
assert concepts['order-line']['extends'] == f'meaning://github.com/meaninggraph/core/order-line?ref={core_pin}'
assert manifest['semantics']['tableConcepts']['Orders'] == ['order']
assert manifest['semantics']['tableConcepts']['Order Details'] == ['order-line', 'commercial-line-item']
assert any(fk['table'] == 'Employees' and fk['column'] == 'ReportsTo' for fk in tables['Employees']['foreignKeys'])
assert any(c['type'] == 'BLOB' for c in tables['Categories']['columns'])
assert tables['CustomerCustomerDemo']['rowCount'] == tables['CustomerDemographics']['rowCount'] == 0
assert sum(t['kind'] == 'view' for t in schema['tables']) == 17
assert db.execute('SELECT COUNT(*) FROM Orders').fetchone()[0] == 830
assert db.execute('SELECT COUNT(*) FROM "Order Details"').fetchone()[0] == 2155
assert db.execute('SELECT COUNT(*) FROM Invoices').fetchone()[0] > 0
assert db.execute('SELECT COUNT(*) FROM "Order Details" WHERE ProductID IS NULL').fetchone()[0] == 0
copy_path = ROOT / 'artifacts/northwind.sqlite'
assert hashlib.sha256(db_path.read_bytes()).digest() == hashlib.sha256(copy_path.read_bytes()).digest()
for rel, data in json.loads((ROOT / 'metadata/checksums.json').read_text())['files'].items():
    path = ROOT / rel
    assert path.stat().st_size == data['bytes'], f'{rel}: byte size changed'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == data['sha256'], f'{rel}: checksum changed'
public = json.loads((ROOT / 'ovdb-database.json').read_text())
assert public['format'] == 'ovdb-database/draft-1'
assert public['id'] == 'https://demodb.dev/northwind/'
assert public['id'] == manifest['capabilities']['ovdb']['canonicalUrl']
assert public['localId'] == 'northwind' and public['serverId'] == 'https://demodb.dev/ovdb'
assert public['serverDbBaseUrl'] == 'https://demodb.dev/ovdb/db/northwind/'
assert public['apiUrl'] == 'https://demodb.dev/ovdb/v1/databases/northwind'
assert public['capabilities'] == {'read': True, 'query': True, 'write': False}
assert {r['name'] for r in public['recordsets']} == {name for kind, name in objects if kind == 'table'}
assert all(r['kind'] == 'table' and 'rows' not in r and 'viewSql' not in r for r in public['recordsets'])
detail_public = next(r for r in public['recordsets'] if r['name'] == 'Order Details')
assert detail_public['modelEntity'] == 'OrderDetails'
for recordset in public['recordsets']:
    meta = tables[recordset['name']]
    assert recordset['columns'] == [{key: column[key] for key in ('name', 'type', 'nullable', 'primaryKey', 'primaryKeyPosition', 'defaultValue')} for column in meta['columns']]
    assert recordset['primaryKey'] == meta['primaryKey']
    assert recordset['foreignKeys'] == meta['foreignKeys']
contract_checksums = json.loads((ROOT / 'metadata/checksums.json').read_text())['files']
assert contract_checksums['schemas/ovdb-database-draft-1.schema.json']['sha256'] == '2424ef00acd462ab5a8abc546fe2d1fffbbb5397e312332aedc77b3e73109488'
dump = ROOT / 'artifacts/northwind.sql'
probe = sqlite3.connect(':memory:')
probe.executescript(dump.read_text())
assert probe.execute('SELECT COUNT(*) FROM "Order Details"').fetchone()[0] == 2155
assert probe.execute('SELECT COUNT(*) FROM "Order Details Extended"').fetchone()[0] == 2155
db.close(); probe.close()
with tempfile.TemporaryDirectory(prefix='northwind-rebuild-') as directory:
    rebuilt_path = Path(directory) / 'rebuilt.sqlite'
    rebuilt = sqlite3.connect(rebuilt_path)
    for item in manifest['source']['recipe']:
        packed = (ROOT / item['path']).read_bytes()
        assert hashlib.sha256(packed).hexdigest() == item['sha256'], f'{item["path"]}: archive hash differs'
        sql = gzip.decompress(packed)
        assert hashlib.sha256(sql).hexdigest() == item['sourceSha256'], f'{item["path"]}: upstream source hash differs'
        rebuilt.executescript(sql.decode('utf-8'))
    rebuilt.commit()
    original = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    objects = original.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    assert objects == rebuilt.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    for kind, name in objects:
        q = '"' + name.replace('"', '""') + '"'
        assert original.execute(f'SELECT count(*) FROM {q}').fetchone()[0] == rebuilt.execute(f'SELECT count(*) FROM {q}').fetchone()[0], f'rebuilt row count differs for {name}'
        if kind == 'table':
            assert original.execute(f'SELECT * FROM {q}').fetchall() == rebuilt.execute(f'SELECT * FROM {q}').fetchall(), f'rebuilt values differ for {name}'
    original.close(); rebuilt.close()
print('Validated 13 tables, 17 views, schema keys/FKs/rows, CSV/JSON/SQLite/SQL exports, source hash and generated checksums.')
