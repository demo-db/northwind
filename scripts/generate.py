#!/usr/bin/env python3
"""Generate the versioned DemoDB contract and portable table exports from source.sqlite."""
import base64, csv, hashlib, json, os, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'manifest.json').read_text())
db_path = ROOT / manifest['dataFile']
expected_db_hash = manifest['source']['databaseSha256']
actual_db_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
if actual_db_hash != expected_db_hash:
    raise SystemExit(f'Pinned imported SQLite hash mismatch: {actual_db_hash}')
out = ROOT / 'artifacts'
data_dir = out / 'data'
data_dir.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
db.row_factory = sqlite3.Row
q = lambda value: '"' + value.replace('"', '""') + '"'
objects = db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END,name").fetchall()
tables = []
exports = []
for obj in objects:
    name, kind = obj['name'], obj['type']
    cols = db.execute(f'PRAGMA table_info({q(name)})').fetchall() if kind == 'table' else db.execute(f'SELECT * FROM {q(name)} LIMIT 0').description
    if kind == 'table':
        columns = [{'name': c['name'], 'type': c['type'] or 'TEXT', 'nullable': not bool(c['notnull']) and not bool(c['pk']), 'primaryKey': bool(c['pk']), 'primaryKeyOrder': c['pk'], 'defaultValue': c['dflt_value']} for c in cols]
        fks = [{'column': f['from'], 'table': f['table'], 'referencedColumn': f['to']} for f in db.execute(f'PRAGMA foreign_key_list({q(name)})')]
        count = db.execute(f'SELECT count(*) FROM {q(name)}').fetchone()[0]
        sample = db.execute(f'SELECT * FROM {q(name)} LIMIT 12').fetchall()
        csv_path = data_dir / f'{name}.csv'
        with csv_path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, lineterminator='\n'); writer.writerow([c['name'] for c in columns])
            cursor = db.execute(f'SELECT * FROM {q(name)}')
            json_rows = []
            for row in cursor:
                writer.writerow([base64.b64encode(v).decode() if isinstance(v, bytes) else v for v in row])
                json_rows.append({key: (base64.b64encode(value).decode() if isinstance(value, bytes) else value) for key, value in dict(row).items()})
        json_path = data_dir / f'{name}.json'
        json_path.write_text(json.dumps(json_rows, ensure_ascii=False, indent=2) + '\n')
        exports.extend([{'table': name, 'format': 'csv', 'path': f'artifacts/data/{name}.csv', 'bytes': csv_path.stat().st_size}, {'table': name, 'format': 'json', 'path': f'artifacts/data/{name}.json', 'bytes': json_path.stat().st_size}])
    else:
        columns = [{'name': c[0], 'type': c[1] or 'TEXT', 'nullable': True, 'primaryKey': False, 'defaultValue': None} for c in cols]
        fks, count, sample = [], db.execute(f'SELECT count(*) FROM {q(name)}').fetchone()[0], db.execute(f'SELECT * FROM {q(name)} LIMIT 12').fetchall()
    def safe(row):
        return {key: (base64.b64encode(value).decode() if isinstance(value, bytes) else value) for key, value in dict(row).items()}
    tables.append({'name': name, 'modelEntity': 'OrderDetails' if name == 'Order Details' else name, 'kind': kind, 'description': '', 'columns': columns, 'foreignKeys': fks, 'rowCount': count, 'viewSql': obj['sql'] if kind == 'view' else None, 'rows': [safe(r) for r in sample]})

sqlite_copy = out / f'{manifest["id"]}.sqlite'
sqlite_copy.write_bytes(db_path.read_bytes())
exports.insert(0, {'table': None, 'format': 'sqlite', 'path': f'artifacts/{manifest["id"]}.sqlite', 'bytes': sqlite_copy.stat().st_size})
sql_path = out / f'{manifest["id"]}.sql'
sql_path.write_text('\n'.join(db.iterdump()) + '\n')
exports.insert(1, {'table': None, 'format': 'sql', 'path': f'artifacts/{manifest["id"]}.sql', 'bytes': sql_path.stat().st_size})
schema = {'contractVersion': manifest['contractVersion'], 'database': {'id': manifest['id'], 'name': manifest['name']}, 'source': manifest['source'], 'tables': tables}
(ROOT / 'metadata').mkdir(exist_ok=True)
(ROOT / 'metadata/schema.json').write_text(json.dumps(schema, indent=2, ensure_ascii=False) + '\n')
contract = {'contractVersion': manifest['contractVersion'], 'manifest': manifest, 'schema': schema, 'exports': exports}
payload = json.dumps(contract, indent=2, ensure_ascii=False) + '\n'
(ROOT / 'metadata/contract.json').write_text(payload)

# Publish storage-neutral ModelSpec and a small, resolvable MeaningGraph file.
def model_type(sql_type):
    t = (sql_type or '').upper()
    if 'INT' in t: return 'int'
    if any(x in t for x in ('REAL', 'FLOA', 'DOUB', 'NUM', 'DEC')): return 'decimal'
    if 'DATE' in t or 'TIME' in t: return 'datetime' if 'TIME' in t else 'date'
    if 'BLOB' in t: return 'document'
    return 'string'

entities = {}
for table in tables:
    if table['kind'] != 'table': continue
    keys = [c['name'] for c in table['columns'] if c['primaryKey']]
    if not keys: keys = [c['name'] for c in table['columns'] if c['name'].lower().endswith('id')][:1]
    fks = {fk['column']: fk['table'] for fk in table['foreignKeys']}
    props = {}
    for c in table['columns']:
        value = {'required': (not c['nullable']) or c['primaryKey']}
        if c['name'] in fks: value['entity'] = fks[c['name']]
        else: value['type'] = model_type(c['type'])
        if not value['required']: value.pop('required')
        props[c['name']] = value
    entity_name = table['modelEntity']
    entities[entity_name] = {'key': keys, 'properties': props}
model = {'modelspec': '1.0-draft', 'module': {'id': 'github.com/demo-db/northwind/northwind', 'name': 'northwind', 'version': '0.1.0'}, 'entities': entities}
(ROOT / 'model').mkdir(exist_ok=True)
(ROOT / 'model/northwind.modelspec.json').write_text(json.dumps(model, indent=2, ensure_ascii=False) + '\n')
hcl = ['# Licence: MIT. Derived one-to-one from the pinned Northwind SQLite schema.', '# ModelSpec 1.0-draft; OrderDetails represents the native SQLite table "Order Details" (ModelSpec published entity names must be identifiers).']
for name, entity in entities.items():
    hcl += ['', f'entity {json.dumps(name, ensure_ascii=False)} {{', f'  key = {json.dumps(entity["key"], ensure_ascii=False)}']
    for prop, definition in entity['properties'].items():
        hcl += ['', f'  property {json.dumps(prop, ensure_ascii=False)} {{']
        for key, value in definition.items(): hcl.append(f'    {key} = {json.dumps(value, ensure_ascii=False)}')
        hcl.append('  }')
    hcl.append('}')
(ROOT / 'model/northwind.modelspec.hcl').write_text('\n'.join(hcl) + '\n')
core = 'meaning://github.com/meaninggraph/core/'
pin = 'cb97dbcd9e951b00e7d46cb2e0c4e120c24c8db7'
meaning = {
    'format': 'meaning/draft-1',
    'id': 'northwind',
    'name': 'Northwind',
    'description': 'Semantic concepts for the Northwind sample business database.',
    'license': 'CC0-1.0',
    'models': {'northwind': 'northwind.modelspec.hcl'},
    'concepts': [
        {'id': 'customer', 'kind': 'entity', 'description': 'A business that places Northwind orders.', 'labels': {'en': 'customer'}, 'extends': f'{core}customer?ref={pin}', 'bindings': [{'model': 'modelspec:///northwind.Customers', 'role': 'entity'}]},
        {'id': 'employee', 'kind': 'entity', 'description': 'An employee who manages or processes orders.', 'labels': {'en': 'employee'}, 'extends': f'{core}employee?ref={pin}', 'bindings': [{'model': 'modelspec:///northwind.Employees', 'role': 'entity'}]},
        {'id': 'order', 'kind': 'entity', 'description': "A customer's purchase order recorded by Northwind.", 'labels': {'en': 'sales order'}, 'extends': f'{core}invoice?ref={pin}', 'bindings': [{'model': 'modelspec:///northwind.Orders', 'role': 'entity'}]},
        {'id': 'order-line', 'kind': 'entity', 'description': 'A product and quantity included on an order.', 'labels': {'en': 'sales order line'}, 'extends': f'{core}invoice-line?ref={pin}', 'bindings': [{'model': 'modelspec:///northwind.OrderDetails', 'role': 'entity'}]},
        {'id': 'shipping-country', 'kind': 'attribute', 'description': 'The country to which the order is shipped.', 'labels': {'en': 'shipping country'}, 'values-of': f'{core}country?ref={pin}', 'bindings': [{'model': 'modelspec:///northwind.Orders', 'property': 'ShipCountry', 'role': 'value'}]}
    ]
}
(ROOT / 'model/northwind.meaning.yaml').write_text(json.dumps(meaning, indent=2, ensure_ascii=False) + '\n')
checksums = {}
for path in sorted(p for p in [ROOT / 'manifest.json', ROOT / 'metadata/contract.json', ROOT / 'metadata/schema.json', *out.rglob('*'), *(ROOT / 'model').rglob('*')] if p.is_file()):
    if path.name == 'checksums.json': continue
    checksums[path.relative_to(ROOT).as_posix()] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
(ROOT / 'metadata/checksums.json').write_text(json.dumps({'contractVersion': 1, 'files': checksums}, indent=2) + '\n')
print(f"Generated {len(tables)} tables/views and {len(exports)} exports for {manifest['id']}")
