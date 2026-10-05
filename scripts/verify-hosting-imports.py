#!/usr/bin/env python3
"""Verify D1-compatible SQLite SQL offline and optionally verify a PostgreSQL import."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal
from collections import defaultdict
from pathlib import Path

from hosting_imports import ROOT, SOURCE, OUT, checksums, objects, quote
from pg_connection import libpq_environment


def source_state() -> tuple[sqlite3.Connection, list[dict], list[dict], dict]:
    db = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    tables, views = objects(db)
    expected = {"sourceSha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "tables": checksums(tables), "views": {v["name"]: db.execute(f"SELECT count(*) FROM {quote(v['name'])}").fetchone()[0] for v in views}, "viewColumns": {v["name"]: v["columns"] for v in views}}
    return db, tables, views, expected


def verify_d1() -> dict:
    db, tables, views, expected = source_state()
    try:
        with tempfile.TemporaryDirectory(prefix="northwind-d1-verify-") as directory:
            target = sqlite3.connect(Path(directory) / "d1-import.sqlite")
            target.execute("PRAGMA foreign_keys=ON")
            target.executescript((OUT / "d1.sql").read_text())
            source_objects = {(kind, name) for kind, name, _ in db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")}
            imported_objects = {(kind, name) for kind, name, _ in target.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")}
            assert source_objects == imported_objects, "D1 table/view objects differ from the pinned SQLite source"
            actual_tables = []
            for table in tables:
                columns = [c["name"] for c in table["columns"]]
                rows = target.execute(f"SELECT * FROM {quote(table['name'])} ORDER BY " + ", ".join(quote(c["name"]) for c in sorted((c for c in table["columns"] if c["pk"]), key=lambda c: c["pk"]))).fetchall()
                actual_tables.append({"name": table["name"], "columns": table["columns"], "rows": rows})
                assert len(rows) == expected["tables"][table["name"]]["rows"], f"{table['name']}: row count differs"
            assert checksums(actual_tables) == expected["tables"], "D1 logical table checksums differ from the source"
            assert target.execute("PRAGMA foreign_key_check").fetchall() == [], "D1 import has foreign-key violations"
            for table in tables:
                pk = [(r[1], r[5]) for r in target.execute(f"PRAGMA table_info({quote(table['name'])})") if r[5]]
                source_pk = [(c["name"], c["pk"]) for c in table["columns"] if c["pk"]]
                assert pk == source_pk, f"{table['name']}: primary key/order differs"
                fks = target.execute(f"PRAGMA foreign_key_list({quote(table['name'])})").fetchall()
                fk_shape = lambda items: sorted((r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in items)
                assert fk_shape(fks) == fk_shape(table["foreignKeys"]), f"{table['name']}: foreign key columns/targets/actions differ"
                def index_shape(connection: sqlite3.Connection) -> list[tuple]:
                    result = []
                    for _, index_name, unique, origin, partial in connection.execute(f"PRAGMA index_list({quote(table['name'])})"):
                        cols = tuple(r[2] for r in connection.execute(f"PRAGMA index_info({quote(index_name)})"))
                        result.append((unique, origin, partial, cols))
                    return sorted(result)
                assert index_shape(target) == index_shape(db), f"{table['name']}: index shape differs"
            for view in views:
                count = target.execute(f"SELECT count(*) FROM {quote(view['name'])}").fetchone()[0]
                assert count == expected["views"][view["name"]], f"{view['name']}: view query count differs"
                columns = [column[0] for column in target.execute(f"SELECT * FROM {quote(view['name'])} LIMIT 0").description]
                assert columns == expected["viewColumns"][view["name"]], f"{view['name']}: view column names/order differs"
            assert target.execute('SELECT COUNT(*) FROM "Invoices" WHERE "Salesperson" != 0 OR "Salesperson" IS NULL').fetchone()[0] == 0, "D1 Invoices SQLite '+' behavior changed"
            assert target.execute('SELECT COUNT(*) FROM "Order Details Extended"').fetchone()[0] == 2155
            target.close()
    finally:
        db.close()
    return {"tables": len(tables), "views": len(views), "sourceSha256": expected["sourceSha256"], "foreignKeyViolations": 0}


def verify_generated_postgres_sql() -> dict:
    sql = (OUT / "postgres.sql").read_text()
    table_ddl = sql.index('CREATE TABLE "Territories"')
    first_fk = sql.index('ALTER TABLE "CustomerCustomerDemo" ADD CONSTRAINT')
    assert table_ddl < first_fk, "PostgreSQL foreign keys must be added after all tables exist"
    assert sum(line.startswith("CREATE TABLE ") for line in sql.splitlines()) == 14, "13 source tables plus import manifest table expected"
    assert sum(line.startswith("ALTER TABLE ") for line in sql.splitlines()) == 13, "every source foreign key must be declared after table creation"
    assert '"Order Details"' in sql and 'PRIMARY KEY ("OrderID", "ProductID")' in sql, "quoted composite key was not translated"
    assert '"Picture" BYTEA' in sql and "decode(" in sql, "BLOB data must use PostgreSQL bytea literals"
    assert '"OrderDate" TEXT' in sql and '"BirthDate" TEXT' in sql, "source dates must retain their source text"
    assert '"UnitPrice" NUMERIC' in sql and '"Discount" DOUBLE PRECISION' in sql, "declared numeric types must be mapped explicitly"
    assert 'CAST("Order Details"."UnitPrice" AS DOUBLE PRECISION)' in sql, "SQLite numeric/REAL view arithmetic translation missing"
    assert '"Discontinued") = \'0\'' in sql and '"Discontinued"  <> \'1\'' in sql, "SQLite TEXT affinity comparisons were not translated"
    assert '0 AS "Salesperson"' in sql and "DATETIME(" not in sql, "legacy Invoices/date view behavior translation changed"
    assert 'AS "CategorySales"' in sql and 'AS "Subtotal"' in sql and 'AS "SaleAmount"' in sql, "SQLite view output names must retain case"
    assert "GREATEST(COALESCE(MAX(" in sql and "pg_get_serial_sequence" in sql, "identity sequences must advance beyond imported IDs"
    view_positions = {name: sql.index(f"CREATE VIEW {quote(name)}") for name in ("Product Sales for 1997", "Category Sales for 1997", "Order Details Extended", "Sales by Category", "Order Subtotals", "Sales Totals by Amount")}
    assert view_positions["Product Sales for 1997"] < view_positions["Category Sales for 1997"], "view dependency order changed"
    assert view_positions["Order Details Extended"] < view_positions["Sales by Category"], "view dependency order changed"
    assert view_positions["Order Subtotals"] < view_positions["Sales Totals by Amount"], "view dependency order changed"
    return {"foreignKeysDeferredUntilTablesExist": 13, "quotedNamesCompositeKeysBlobsDatesNumericAndViews": "checked"}


def assert_view_rows_equal(name: str, columns: list[str], source_rows: list[tuple], target_rows: list[tuple]) -> None:
    """Compare a view's complete row multiset with a tight numeric tolerance."""
    assert len(source_rows) == len(target_rows), f"{name}: view row count differs"

    def group_key(row: tuple) -> tuple:
        key = []
        for value in row:
            if isinstance(value, (int, float, Decimal)):
                key.append(("number",))
            elif isinstance(value, bytes):
                key.append(("bytes", value.hex()))
            else:
                key.append((type(value).__name__, value))
        return tuple(key)

    def numeric_sort(row: tuple) -> tuple:
        return tuple(Decimal(str(value)) for value in row if isinstance(value, (int, float, Decimal)))

    def groups(rows: list[tuple]) -> dict[tuple, list[tuple]]:
        result: dict[tuple, list[tuple]] = defaultdict(list)
        for row in rows:
            result[group_key(row)].append(row)
        for group in result.values():
            group.sort(key=numeric_sort)
        return result

    source_groups, target_groups = groups(source_rows), groups(target_rows)
    assert source_groups.keys() == target_groups.keys(), f"{name}: view values differ"
    for key, expected_rows in source_groups.items():
        actual_rows = target_groups[key]
        assert len(expected_rows) == len(actual_rows), f"{name}: duplicate view row count differs"
        for expected, actual in zip(expected_rows, actual_rows):
            for column, left, right in zip(columns, expected, actual):
                if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
                    left_number, right_number = Decimal(str(left)), Decimal(str(right))
                    assert abs(left_number - right_number) <= max(Decimal("1e-9"), abs(left_number) * Decimal("1e-12")), f"{name}.{column}: numeric view value differs ({left} != {right})"
                else:
                    assert left == right, f"{name}.{column}: view value differs"


def psql(sql: str, *, csv_output: bool = False) -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set for PostgreSQL verification")
    try:
        env = libpq_environment(database_url)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    args = ["psql", "--no-psqlrc", "--set", "ON_ERROR_STOP=1"]
    args += ["--csv", "--tuples-only"] if csv_output else ["--tuples-only", "--no-align"]
    args += ["--command", sql]
    proc = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    if proc.returncode:
        raise RuntimeError(f"PostgreSQL verification query failed (psql exit {proc.returncode}); connection details were suppressed")
    return proc.stdout.strip()


def verify_postgres() -> dict:
    source_db, tables, views, expected = source_state()
    manifest_rows = json.loads(psql('SELECT row_to_json(m)::text FROM northwind."_import_manifest" m'))
    assert manifest_rows["version"] == 1 and manifest_rows["source_sha256"] == expected["sourceSha256"], "PostgreSQL import provenance differs"
    pg_manifest = manifest_rows["manifest_json"]
    if isinstance(pg_manifest, str):
        pg_manifest = json.loads(pg_manifest)
    assert pg_manifest["tables"] == expected["tables"], "PostgreSQL recorded source checksums differ"

    # Verify row values independently by streaming each source table as JSON.
    for table in tables:
        pk = [c["name"] for c in sorted((c for c in table["columns"] if c["pk"]), key=lambda c: c["pk"])]
        query = "SELECT row_to_json(t)::text FROM northwind." + quote(table["name"]) + " t ORDER BY " + ", ".join("t." + quote(c) for c in pk)
        parsed = []
        raw = psql(query, csv_output=True)
        if raw:
            for fields in csv.reader(raw.splitlines()):
                row = json.loads(fields[0], parse_float=Decimal, parse_int=int)
                values = []
                for column in table["columns"]:
                    value = row[column["name"]]
                    if "BLOB" in column["type"].upper() and isinstance(value, str) and value.startswith("\\x"):
                        value = bytes.fromhex(value[2:])
                    values.append(value)
                parsed.append(tuple(values))
        target_table = {"name": table["name"], "columns": table["columns"], "rows": parsed}
        assert len(parsed) == expected["tables"][table["name"]]["rows"], f"PostgreSQL {table['name']}: row count differs"
        assert checksums([target_table])[table["name"]] == expected["tables"][table["name"]], f"PostgreSQL {table['name']}: canonical row checksum differs"

    key_rows = json.loads(psql("""SELECT COALESCE(json_agg(json_build_object('table', c.relname, 'columns', p.columns)), '[]'::json)
FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
CROSS JOIN LATERAL (SELECT json_agg(a.attname ORDER BY u.ordinality) AS columns FROM unnest(k.conkey) WITH ORDINALITY u(attnum, ordinality) JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=u.attnum) p
WHERE k.contype='p' AND c.relnamespace='northwind'::regnamespace"""))
    actual_pks = {row["table"]: row["columns"] for row in key_rows}
    expected_pks = {t["name"]: [c["name"] for c in sorted((c for c in t["columns"] if c["pk"]), key=lambda c: c["pk"])] for t in tables}
    assert actual_pks == expected_pks, "PostgreSQL primary-key columns/order differ"

    fk_rows = json.loads(psql("""SELECT COALESCE(json_agg(json_build_object('table', src.relname, 'columns', p.src_columns, 'target', dst.relname, 'targetColumns', p.dst_columns, 'onUpdate', k.confupdtype, 'onDelete', k.confdeltype)), '[]'::json)
FROM pg_constraint k JOIN pg_class src ON src.oid=k.conrelid JOIN pg_class dst ON dst.oid=k.confrelid
CROSS JOIN LATERAL (SELECT json_agg(sa.attname ORDER BY u.ordinality) AS src_columns,
 json_agg(da.attname ORDER BY u.ordinality) AS dst_columns
 FROM unnest(k.conkey, k.confkey) WITH ORDINALITY u(srcnum, dstnum, ordinality)
 JOIN pg_attribute sa ON sa.attrelid=src.oid AND sa.attnum=u.srcnum
 JOIN pg_attribute da ON da.attrelid=dst.oid AND da.attnum=u.dstnum) p
WHERE k.contype='f' AND src.relnamespace='northwind'::regnamespace"""))
    actual_fks = {(r["table"], tuple(r["columns"]), r["target"], tuple(r["targetColumns"]), r["onUpdate"], r["onDelete"]) for r in fk_rows}
    action_code = {"NO ACTION": "a", "RESTRICT": "r", "CASCADE": "c", "SET NULL": "n", "SET DEFAULT": "d"}
    expected_fks = {(t["name"], (fk[3],), fk[2], (fk[4],), action_code[fk[5].upper()], action_code[fk[6].upper()]) for t in tables for fk in t["foreignKeys"]}
    assert actual_fks == expected_fks, "PostgreSQL foreign-key columns, targets or actions differ"
    index_counts = json.loads(psql("""SELECT json_build_object('primaryIndexes', count(*) FILTER (WHERE i.indisprimary), 'views', (SELECT count(*) FROM pg_class c WHERE c.relnamespace='northwind'::regnamespace AND c.relkind='v'))::text
FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid WHERE c.relnamespace='northwind'::regnamespace"""))
    assert index_counts["primaryIndexes"] == len(tables), "PostgreSQL primary-key indexes are missing"
    assert index_counts["views"] == len(views), "PostgreSQL view count differs"
    for view in views:
        actual_count = int(psql(f"SELECT count(*) FROM northwind.{quote(view['name'])}"))
        assert actual_count == expected["views"][view["name"]], f"PostgreSQL {view['name']}: view row count differs"
        actual_columns = json.loads(psql("SELECT COALESCE(json_agg(column_name ORDER BY ordinal_position), '[]'::json)::text FROM information_schema.columns WHERE table_schema='northwind' AND table_name=" + "'" + view["name"].replace("'", "''") + "'"))
        assert actual_columns == expected["viewColumns"][view["name"]], f"PostgreSQL {view['name']}: view column names/order differs"
        target_rows = []
        raw = psql(f"SELECT row_to_json(t)::text FROM northwind.{quote(view['name'])} t", csv_output=True)
        if raw:
            for fields in csv.reader(raw.splitlines()):
                data = json.loads(fields[0], parse_float=Decimal, parse_int=int)
                target_rows.append(tuple(data[column] for column in view["columns"]))
        source_rows = source_db.execute(f"SELECT * FROM {quote(view['name'])}").fetchall()
        assert_view_rows_equal(view["name"], view["columns"], source_rows, target_rows)
    salesperson_bad = int(psql('SELECT count(*) FROM northwind."Invoices" WHERE "Salesperson" <> 0 OR "Salesperson" IS NULL'))
    assert salesperson_bad == 0, "PostgreSQL Invoices SQLite '+' behavior changed"
    assert int(psql('SELECT count(*) FROM northwind."Order Details Extended"')) == 2155
    source_db.close()
    return {"tables": len(tables), "views": len(views), "primaryIndexes": index_counts["primaryIndexes"], "foreignKeys": len(actual_fks), "viewRowsAndColumns": "matched (numeric tolerance rel 1e-12, abs 1e-9)", "sourceSha256": expected["sourceSha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true", help="also verify the live northwind schema using psql and DATABASE_URL")
    args = parser.parse_args()
    if not (OUT / "d1.sql").is_file():
        raise SystemExit("generated hosting imports missing; run python3 scripts/hosting_imports.py first")
    d1 = verify_d1()
    report = {"d1SqliteReimport": d1, "postgresGeneratedSql": verify_generated_postgres_sql()}
    if args.postgres:
        report["postgres"] = verify_postgres()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, sqlite3.Error) as error:
        print(f"Hosting import verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
