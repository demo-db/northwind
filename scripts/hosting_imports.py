#!/usr/bin/env python3
"""Build deterministic D1 and PostgreSQL imports from the pinned SQLite seed."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data-source/source.sqlite"
OUT = ROOT / "artifacts/hosting-imports"
MAX_D1_STATEMENT_BYTES = 100_000
IMPORT_VERSION = 1


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sqlite_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("SQLite TEXT containing NUL cannot be represented in SQL literals")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            return "CAST(X'" + value.encode("utf-8").hex() + "' AS TEXT)"
        return sql_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")


def postgres_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "decode(" + sql_string(value.hex()) + ", 'hex')"
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("PostgreSQL TEXT cannot contain NUL")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            return "convert_from(decode(" + sql_string(value.encode("utf-8").hex()) + ", 'hex'), 'UTF8')"
        return sql_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")


def pg_type(declared: str) -> str:
    upper = (declared or "").upper().strip()
    if "BLOB" in upper:
        return "BYTEA"
    if "DATETIME" in upper or upper == "DATE" or "TIME" in upper:
        return "TEXT"
    if any(token in upper for token in ("INT", "BOOL")):
        return "BIGINT"
    if any(token in upper for token in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if any(token in upper for token in ("NUM", "DEC")):
        return "NUMERIC"
    return "TEXT"


def objects(db: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = db.execute("""SELECT type, name, sql FROM sqlite_master
      WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'
      ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name""").fetchall()
    tables: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    for kind, name, create_sql in rows:
        if kind == "table":
            cols = db.execute(f"PRAGMA table_info({quote(name)})").fetchall()
            fks = db.execute(f"PRAGMA foreign_key_list({quote(name)})").fetchall()
            records = db.execute(f"SELECT * FROM {quote(name)}").fetchall()
            tables.append({
                "name": name,
                "createSql": create_sql,
                "columns": [{"name": c[1], "type": c[2] or "", "notNull": bool(c[3]), "default": c[4], "pk": c[5]} for c in cols],
                "foreignKeys": fks,
                "rows": records,
            })
        else:
            columns = [column[0] for column in db.execute(f"SELECT * FROM {quote(name)} LIMIT 0").description]
            views.append({"name": name, "createSql": create_sql, "columns": columns})
    return tables, views


def row_order_sql(table: dict[str, Any]) -> str:
    keys = [c["name"] for c in sorted(table["columns"], key=lambda c: c["pk"]) if c["pk"]]
    names = keys or [c["name"] for c in table["columns"]]
    return ", ".join(quote(name) for name in names)


def insertion_order(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put referenced tables before dependents; break self/cyclic references safely."""
    by_name = {table["name"]: table for table in tables}
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []

    def visit(name: str, stack: set[str]) -> None:
        if name in seen or name in stack:
            return
        stack.add(name)
        for fk in by_name[name]["foreignKeys"]:
            target = fk[2]
            if target in by_name and target != name:
                visit(target, stack)
        stack.remove(name)
        seen.add(name)
        ordered.append(by_name[name])

    for table in tables:
        visit(table["name"], set())
    return ordered


def view_insertion_order(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order views after their FROM/JOIN view dependencies, rejecting cycles."""
    by_name = {view["name"]: view for view in views}
    dependencies: dict[str, set[str]] = {name: set() for name in by_name}
    for name, view in by_name.items():
        sql = view["createSql"] or ""
        for dependency in by_name:
            if dependency == name:
                continue
            escaped = re.escape(dependency)
            patterns = [
                rf"\b(?:FROM|JOIN)\s+\[\s*{escaped}\s*\]",
                rf'\b(?:FROM|JOIN)\s+"{escaped}"',
                rf"\b(?:FROM|JOIN)\s+`{escaped}`",
            ]
            if " " not in dependency:
                patterns.append(rf"\b(?:FROM|JOIN)\s+{escaped}\b")
            if any(re.search(pattern, sql, flags=re.IGNORECASE) for pattern in patterns):
                dependencies[name].add(dependency)
    state: dict[str, int] = {}
    ordered: list[dict[str, Any]] = []
    path: list[str] = []

    def visit(name: str) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            cycle = " -> ".join(path + [name])
            raise ValueError(f"cycle in SQLite view dependencies: {cycle}")
        state[name] = 1
        path.append(name)
        for dependency in sorted(dependencies[name]):
            visit(dependency)
        path.pop()
        state[name] = 2
        ordered.append(by_name[name])

    for view in views:
        visit(view["name"])
    return ordered


def normalized(value: Any, declared_type: str) -> Any:
    if value is None:
        return ["null"]
    upper = declared_type.upper()
    if "BLOB" in upper:
        return ["blob", value.hex()]
    if any(token in upper for token in ("NUM", "DEC", "REAL", "FLOA", "DOUB")) and isinstance(value, (int, float, Decimal)):
        decimal = Decimal(str(value)).normalize()
        return ["number", format(decimal, "f")]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    if isinstance(value, float):
        return ["float64", value.hex()]
    if isinstance(value, int):
        return ["integer", str(value)]
    return ["text", str(value)]


def checksums(tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for table in tables:
        cols = table["columns"]
        records = sorted(table["rows"], key=lambda row: tuple("" if row[index] is None else str(row[index]) for index, col in enumerate(cols) if col["pk"]))
        digest = hashlib.sha256()
        for row in records:
            payload = [normalized(value, cols[index]["type"]) for index, value in enumerate(row)]
            digest.update(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        result[table["name"]] = {"rows": len(records), "sha256": digest.hexdigest()}
    return result


def d1_sql(tables: list[dict[str, Any]], views: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    statements: list[str] = ["-- Generated from data-source/source.sqlite. Do not edit by hand."]
    lengths: list[dict[str, Any]] = []
    # D1 applies each statement independently. All objects are created before
    # inserts, and parent tables are loaded before their dependents.
    for table in tables:
        statements.append(table["createSql"].strip())
    for table in insertion_order(tables):
        columns = ", ".join(quote(c["name"]) for c in table["columns"])
        # Keep the source rowid scan order so the SQLite/D1 copy also preserves
        # stable behavior for callers that happen to rely on rowid order.
        order = table["rows"]
        prefix = f"INSERT INTO {quote(table['name'])} ({columns}) VALUES "
        batch: list[str] = []
        for row in order:
            values = "(" + ", ".join(sqlite_literal(v) for v in row) + ")"
            candidate = prefix + ", ".join(batch + [values]) + ";"
            byte_count = len(candidate.encode("utf-8"))
            if batch and byte_count > MAX_D1_STATEMENT_BYTES:
                statement = prefix + ", ".join(batch) + ";"
                statements.append(statement)
                lengths.append({"table": table["name"], "bytes": len(statement.encode("utf-8"))})
                batch = [values]
                byte_count = len((prefix + values + ";").encode("utf-8"))
            else:
                batch.append(values)
            if byte_count > MAX_D1_STATEMENT_BYTES:
                raise ValueError(f"D1 statement too large for {table['name']}: {byte_count} bytes")
        if batch:
            statement = prefix + ", ".join(batch) + ";"
            statements.append(statement)
            lengths.append({"table": table["name"], "bytes": len(statement.encode("utf-8"))})
    # Views are created after all base tables/data so D1's schema compiler sees
    # every referenced object, including view-on-view dependencies.
    for view in view_insertion_order(views):
        statements.append(view["createSql"].strip())
    result = "\n\n".join(statement.rstrip(";") + ";" for statement in statements) + "\n"
    return result, lengths


def pg_table_ddl(table: dict[str, Any]) -> str:
    cols = table["columns"]
    create = table["createSql"] or ""
    definitions: list[str] = []
    pk_cols: list[tuple[int, str]] = []
    for col in cols:
        definition = f"  {quote(col['name'])} {pg_type(col['type'])}"
        if col["notNull"] or col["pk"]:
            definition += " NOT NULL"
        if col["default"] is not None:
            definition += f" DEFAULT {col['default']}"
        if "AUTOINCREMENT" in create.upper() and col["pk"]:
            definition += " GENERATED BY DEFAULT AS IDENTITY"
        definitions.append(definition)
        if col["pk"]:
            pk_cols.append((col["pk"], col["name"]))
    if pk_cols:
        definitions.append("  PRIMARY KEY (" + ", ".join(quote(name) for _, name in sorted(pk_cols)) + ")")
    # Preserve source CHECK expressions. Square-bracket identifiers are the
    # only non-PostgreSQL quoting form used in this pinned schema.
    for match in re.finditer(r"CHECK\s*\(((?:[^()]|\([^()]*\))*)\)", create, flags=re.IGNORECASE):
        expression = re.sub(r"\[([^\]]+)\]", lambda m: quote(m.group(1)), match.group(1))
        definitions.append(f"  CHECK ({expression})")
    return f"CREATE TABLE {quote(table['name'])} (\n" + ",\n".join(definitions) + "\n);"


def pg_fk_ddls(tables: list[dict[str, Any]]) -> list[str]:
    statements: list[str] = []
    for table_index, table in enumerate(tables):
        groups: dict[int, list[tuple[Any, ...]]] = {}
        for fk in table["foreignKeys"]:
            groups.setdefault(fk[0], []).append(fk)
        for fk_id, fk_rows in sorted(groups.items()):
            fk_rows.sort(key=lambda row: row[1])
            local = ", ".join(quote(row[3]) for row in fk_rows)
            remote = ", ".join(quote(row[4]) for row in fk_rows)
            target = quote(fk_rows[0][2])
            on_update = str(fk_rows[0][5]).upper()
            on_delete = str(fk_rows[0][6]).upper()
            constraint = quote(f"northwind_fk_{table_index:02d}_{fk_id:02d}")
            statements.append(f"ALTER TABLE {quote(table['name'])} ADD CONSTRAINT {constraint} FOREIGN KEY ({local}) REFERENCES {target} ({remote}) ON UPDATE {on_update} ON DELETE {on_delete} DEFERRABLE INITIALLY DEFERRED;")
    return statements


def pg_view_sql(view: dict[str, Any], tables: list[dict[str, Any]], views: list[dict[str, Any]]) -> str:
    statement = view["createSql"].strip().rstrip(";")
    statement = re.sub(r"\[([^\]]+)\]", lambda m: quote(m.group(1)), statement)
    # SQLite DATETIME('date') is an identity-style text conversion for these
    # source literals. Date columns are TEXT in PostgreSQL to retain source text.
    statement = re.sub(r"\bDATETIME\s*\(\s*('(?:''|[^'])*')\s*\)", r"\1", statement, flags=re.IGNORECASE)
    # This source expression uses SQLite's numeric '+' operator on two TEXT
    # names; SQLite returns integer zero. Preserve the observed result.
    statement = re.sub(r"\(Employees\.FirstName\s*\+\s*' '\s*\+\s*Employees\.LastName\)\s+AS\s+Salesperson", '0 AS "Salesperson"', statement, flags=re.IGNORECASE)
    # PostgreSQL folds unquoted identifiers to lower case. Quote every name
    # copied from the case-sensitive SQLite schema, including output names.
    identifiers = {table["name"] for table in tables}
    identifiers.update(column["name"] for table in tables for column in table["columns"])
    identifiers.update(v["name"] for v in views)
    identifiers.update(column for v in views for column in v["columns"])
    lookup = {name.casefold(): name for name in identifiers}
    token = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z0-9_]*")
    def quote_schema_name(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.startswith(("'", '\"')):
            return word
        original = lookup.get(word.casefold())
        return quote(original) if original else word
    statement = token.sub(quote_schema_name, statement)
    # SQLite's TEXT affinity converts these numeric literals to text before
    # comparison; PostgreSQL rejects text = integer rather than coercing it.
    statement = re.sub(r'((?:"Products"\s*\.\s*)?"Discontinued"[\s\)]*)\s*(<>|!=|=)\s*([01])\b', r"\1 \2 '\3'", statement, flags=re.IGNORECASE)
    # SQLite's arithmetic promotes NUMERIC values to binary floating point
    # when combined with the declared REAL Discount column. Keep the source
    # calculation's behavior while storing NUMERIC columns as PostgreSQL NUMERIC.
    statement = re.sub(r'("Order Details"\."UnitPrice")', r"CAST(\1 AS DOUBLE PRECISION)", statement, flags=re.IGNORECASE)
    return statement + ";"


def postgres_sql(tables: list[dict[str, Any]], views: list[dict[str, Any]], source_sha: str) -> str:
    marker = f"northwind-import:v{IMPORT_VERSION}:source-sha256:{source_sha}"
    statements = ["-- Generated from data-source/source.sqlite. Do not edit by hand.",
      "-- Run with scripts/import-postgres.py; the guarded schema DDL and load are one transaction.",
      "BEGIN;",
      "DO $northwind_guard$ DECLARE current_comment text; BEGIN "
      "SELECT obj_description(n.oid, 'pg_namespace') INTO current_comment FROM pg_namespace n WHERE n.nspname = 'northwind'; "
      "IF FOUND THEN "
      "IF current_setting('northwind.allow_replace', true) IS DISTINCT FROM 'on' THEN RAISE EXCEPTION 'schema northwind already exists; refusing overwrite'; END IF; "
      f"IF current_comment IS DISTINCT FROM {sql_string(marker)} THEN RAISE EXCEPTION 'schema northwind provenance does not match this pinned source; refusing overwrite'; END IF; "
      "IF to_regclass('northwind._import_manifest') IS NULL OR NOT EXISTS (SELECT 1 FROM northwind._import_manifest WHERE version = " + str(IMPORT_VERSION) + " AND source_sha256 = " + sql_string(source_sha) + ") THEN RAISE EXCEPTION 'schema northwind import manifest does not match this pinned source; refusing overwrite'; END IF; "
      "EXECUTE 'DROP SCHEMA northwind CASCADE'; END IF; "
      "EXECUTE 'CREATE SCHEMA northwind'; "
      f"EXECUTE {sql_string('COMMENT ON SCHEMA northwind IS ' + sql_string(marker))}; END $northwind_guard$;",
      "SET LOCAL search_path = northwind, pg_catalog;"]
    for table in tables:
        statements.append(pg_table_ddl(table))
    # Add all FKs after creating every table, so forward and cyclic references
    # (including Employees.ReportsTo) do not depend on object-name sort order.
    statements.extend(pg_fk_ddls(tables))
    for table in insertion_order(tables):
        columns = ", ".join(quote(c["name"]) for c in table["columns"])
        order = sorted(table["rows"], key=lambda row: tuple("" if row[index] is None else str(row[index]) for index, col in enumerate(table["columns"]) if col["pk"]))
        for row in order:
            values = ", ".join(postgres_literal(v) for v in row)
            statements.append(f"INSERT INTO {quote(table['name'])} ({columns}) VALUES ({values});")
    # Seed identity sequences past the imported explicit IDs.
    for table in tables:
        create = (table["createSql"] or "").upper()
        if "AUTOINCREMENT" not in create:
            continue
        identity = next((c["name"] for c in table["columns"] if c["pk"]), None)
        if identity:
            statements.append("SELECT setval(pg_get_serial_sequence(" + sql_string(f'"northwind"."{table["name"]}"') + ", " + sql_string(identity) + "), GREATEST(COALESCE(MAX(" + quote(identity) + "), 1), 1), COUNT(*) > 0) FROM " + quote(table["name"]) + ";")
    for view in view_insertion_order(views):
        statements.append(pg_view_sql(view, tables, views))
    manifest = {"version": IMPORT_VERSION, "sourceSha256": source_sha, "tables": checksums(tables)}
    statements.append("CREATE TABLE \"_import_manifest\" (\"version\" integer NOT NULL, \"source_sha256\" text NOT NULL, \"manifest_json\" jsonb NOT NULL);")
    statements.append("INSERT INTO \"_import_manifest\" VALUES (" + str(IMPORT_VERSION) + ", " + sql_string(source_sha) + ", " + sql_string(json.dumps(manifest, sort_keys=True, separators=(",", ":"))) + "::jsonb);")
    statements.append("COMMIT;")
    return "\n\n".join(statements) + "\n"


def generate(output: Path = OUT) -> dict[str, Any]:
    source_bytes = SOURCE.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    manifest_path = ROOT / "manifest.json"
    pinned = json.loads(manifest_path.read_text())["source"]["databaseSha256"]
    if source_sha != pinned:
        raise SystemExit(f"source database hash mismatch: expected {pinned}, got {source_sha}")
    db = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    tables, views = objects(db)
    summary = {
        "version": IMPORT_VERSION,
        "source": "data-source/source.sqlite",
        "sourceBytes": len(source_bytes),
        "sourceSha256": source_sha,
        "objects": {"tables": len(tables), "views": len(views)},
        "tables": checksums(tables),
        "views": {view["name"]: db.execute(f"SELECT count(*) FROM {quote(view['name'])}").fetchone()[0] for view in views},
    }
    d1_text, d1_lengths = d1_sql(tables, views)
    summary["d1"] = {"file": "d1.sql", "maxStatementBytes": max([len(table["createSql"].encode("utf-8")) for table in tables] + [len(view["createSql"].encode("utf-8")) for view in views] + [entry["bytes"] for entry in d1_lengths] + [0]), "maxAllowedStatementBytes": MAX_D1_STATEMENT_BYTES, "insertStatements": len(d1_lengths)}
    output.mkdir(parents=True, exist_ok=True)
    (output / "d1.sql").write_text(d1_text)
    (output / "postgres.sql").write_text(postgres_sql(tables, views, source_sha))
    (output / "manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    db.close()
    return summary


if __name__ == "__main__":
    summary = generate()
    print(f"Generated Northwind D1 and PostgreSQL imports ({summary['objects']['tables']} tables, {summary['objects']['views']} views; source {summary['sourceSha256']}).")
