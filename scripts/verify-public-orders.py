#!/usr/bin/env python3
"""Compare the complete public Northwind Orders table with this pinned provider.

This proves the 830 projected Orders rows at observation time. It does not
inspect the hosted PostgreSQL import manifest, other tables, or API rights.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hosting_imports import ROOT, SOURCE, OUT, checksums

FIELDS = (
    "OrderID", "CustomerID", "EmployeeID", "OrderDate", "RequiredDate",
    "ShippedDate", "ShipVia", "Freight", "ShipName", "ShipAddress",
    "ShipCity", "ShipRegion", "ShipPostalCode", "ShipCountry",
)
DATES = frozenset(("OrderDate", "RequiredDate", "ShippedDate"))
INTEGERS = frozenset(("OrderID", "EmployeeID", "ShipVia"))
UPSTREAM_REVISION = "4f56e7f5906dfd23b25244c5bfe8fb5da6402efd"
SOURCE_SHA256 = "279b34136771aee75d802094b3329515a2b01da65d2a20a4a9e3b58c29b4fd20"
ORDERS_SHA256 = "8c35e5cf83673ba9cc782fb0c3e2a6b9875b011a841e147db5b7393ef4afa636"
NOTICE_SHA256 = "c28e204be6418b87ae1c83127096aad9c9e1a218c365f8f4d630e84d8ba96c47"
PG_COLLECTION = "pg1_AAAACW5vcnRod2luZAAAAAZPcmRlcnM"
SOURCES = {
    "sqlite": ("https://demodb.dev/ovdb/v1/databases/northwind/dtql", "{name: Orders}", "northwind", "Orders"),
    "postgresql": ("https://cloud.openvaultdb.com/v1/databases/northwind-postgresql/dtql", "{schema: northwind, name: Orders}", "northwind-postgresql", PG_COLLECTION),
}
ORIGINS = ("https://datatug.app", "http://localhost:4200")
MAX_RESPONSE_BYTES = 1_000_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def query(from_clause: str, *, small: bool = False) -> str:
    fields = ("OrderID",) if small else FIELDS
    return (f"from: {from_clause}\norderBy: [{{field: OrderID}}]\n"
            "columns: [" + ", ".join(f"{{field: {field}}}" for field in fields) + "]\n"
            f"limit: {1 if small else 1000}\n")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError(f"unexpected HTTP redirect {code} to {newurl}")


OPENER = urllib.request.build_opener(NoRedirect())


def request(url: str, *, method: str, body: bytes | None = None, origin: str | None = None):
    headers = {"User-Agent": "curl/8.7.1", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if origin:
        headers["Origin"] = origin
    if method == "OPTIONS":
        headers["Access-Control-Request-Method"] = "POST"
        headers["Access-Control-Request-Headers"] = "content-type"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    for attempt in range(3):
        try:
            with OPENER.open(req, timeout=45) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"{url}: response exceeds {MAX_RESPONSE_BYTES} bytes")
                return response.status, response.headers, raw
        except urllib.error.HTTPError as error:
            if error.code in (502, 503, 504) and attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise ValueError(f"{url}: HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise ValueError(f"{url}: network failure: {error.reason}") from error
    raise AssertionError("retry loop ended without a response")


def normalize(row: dict) -> list:
    if not isinstance(row, dict) or set(row) != set(FIELDS):
        raise ValueError("Orders projection must contain exactly all 14 fields")
    result = []
    for field in FIELDS:
        value = row[field]
        if value is None:
            result.append(None)
        elif field in DATES:
            if not isinstance(value, str) or (len(value) != 10 and (len(value) != 20 or value[10:] != "T00:00:00Z")):
                raise ValueError(f"{field}: unsupported date representation")
            date = value[:10]
            if len(date) != 10 or dt.date.fromisoformat(date).isoformat() != date:
                raise ValueError(f"{field}: invalid date")
            result.append(date)
        elif field == "Freight":
            if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
                raise ValueError("Freight: invalid numeric value")
            try:
                number = Decimal(str(value))
            except InvalidOperation as error:
                raise ValueError("Freight: invalid decimal value") from error
            if not number.is_finite():
                raise ValueError("Freight: non-finite numeric value")
            result.append(format(number.normalize(), "f"))
        elif field in INTEGERS:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field}: expected integer")
            result.append(value)
        elif isinstance(value, str):
            result.append(value)
        else:
            raise ValueError(f"{field}: expected text or null")
    return result


def canonical_sha256(rows: list[list]) -> str:
    return sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def provider_state() -> tuple[list[list], list[dict]]:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    import_manifest = json.loads((OUT / "manifest.json").read_text())
    source = manifest["source"]
    if (source["repository"], source["revision"], source["path"], source["license"],
        source["licenseFile"], source["databaseSha256"]) != (
        "https://github.com/jpwhite3/northwind-SQLite3", UPSTREAM_REVISION,
        "src/create.sql + src/update.sql", "MIT", "data-source/LICENSE.md", SOURCE_SHA256,
    ):
        raise ValueError("provider source and MIT declaration differ from the pinned baseline")
    if sha256(SOURCE.read_bytes()) != SOURCE_SHA256 or import_manifest["sourceSha256"] != SOURCE_SHA256:
        raise ValueError("pinned source fixture SHA-256 mismatch")
    if sha256((ROOT / source["licenseFile"]).read_bytes()) != NOTICE_SHA256:
        raise ValueError("pinned MIT notice SHA-256 mismatch")
    if import_manifest["tables"]["Orders"] != {"rows": 830, "sha256": ORDERS_SHA256}:
        raise ValueError("published Orders checksum differs from the pinned baseline")
    with closing(sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)) as db:
        columns = [{"name": r[1], "type": r[2], "pk": r[5]} for r in db.execute('PRAGMA table_info("Orders")')]
        if [col["name"] for col in columns] != list(FIELDS):
            raise ValueError("pinned Orders schema differs")
        db.row_factory = sqlite3.Row
        records = [dict(r) for r in db.execute('SELECT * FROM "Orders" ORDER BY "OrderID"')]
    if len(records) != 830 or checksums([{"name": "Orders", "columns": columns,
                                       "rows": [tuple(r[field] for field in FIELDS) for r in records]}])["Orders"]["sha256"] != ORDERS_SHA256:
        raise ValueError("pinned Orders rows do not match the published provider checksum")
    return [normalize(row) for row in records], columns


def verify_response(raw: bytes, label: str, columns: list[dict], pinned_rows: list[list]) -> dict:
    try:
        response = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}: invalid UTF-8 JSON") from error
    if not isinstance(response, dict) or response.get("complete") is not True or response.get("nextCursor") is not None:
        raise ValueError(f"{label}: incomplete or continued response")
    records = response.get("records")
    if not isinstance(records, list) or len(records) != 830:
        raise ValueError(f"{label}: expected exactly 830 records")
    if response.get("columns") is not None and response["columns"] != list(FIELDS):
        raise ValueError(f"{label}: projection columns differ")
    rows = [normalize(r.get("data") if isinstance(r, dict) else None) for r in records]
    ids = [row[0] for row in rows]
    if ids != sorted(ids) or len(set(ids)) != 830:
        raise ValueError(f"{label}: OrderID order or uniqueness differs")
    if rows != pinned_rows:
        raise ValueError(f"{label}: one or more Orders row fields differ from the pinned source")
    expected_database, expected_collection = SOURCES[label][2:]
    execution = response.get("execution")
    if label == "postgresql" and not isinstance(execution, dict):
        raise ValueError("postgresql: execution metadata missing")
    if execution is not None:
        if (not isinstance(execution, dict) or execution.get("rowsReturned") != 830 or
            execution.get("sources") != [{"database": expected_database, "collection": expected_collection}]):
            raise ValueError(f"{label}: execution source identity or count differs")
    elif label == "postgresql":
        raise ValueError("postgresql: execution source identity missing")
    if label == "postgresql" and response.get("columns") != list(FIELDS):
        raise ValueError("postgresql: projection columns missing")
    provider_rows = []
    for row in rows:
        values = []
        for field, value in zip(FIELDS, row):
            values.append(Decimal(value) if field == "Freight" and value is not None else value)
        provider_rows.append(tuple(values))
    checksum = checksums([{"name": "Orders", "columns": columns, "rows": provider_rows}])["Orders"]["sha256"]
    if checksum != ORDERS_SHA256:
        raise ValueError(f"{label}: provider Orders checksum mismatch")
    return {
        "complete": True, "rows": 830, "fields": list(FIELDS),
        "canonicalRowsSha256": canonical_sha256(rows), "providerOrdersSha256": checksum,
        "responseKeys": sorted(response),
        "executionSourcesPresent": execution is not None,
        "executionRowsReturned": execution["rowsReturned"] if execution else None,
        "executionSources": execution["sources"] if execution else None,
        "rawResponseSha256": sha256(raw), "responseBytes": len(raw),
    }


def cors(url: str, from_clause: str) -> dict:
    result = {}
    body = json.dumps({"query": query(from_clause, small=True)}, separators=(",", ":")).encode()
    for origin in ORIGINS:
        pre_status, pre_headers, _ = request(url, method="OPTIONS", origin=origin)
        post_status, post_headers, _ = request(url, method="POST", body=body, origin=origin)
        def allowed(value):
            return value in ("*", origin)
        pre_methods = {part.strip().lower() for part in pre_headers.get("Access-Control-Allow-Methods", "").split(",")}
        pre_request_headers = {part.strip().lower() for part in pre_headers.get("Access-Control-Allow-Headers", "").split(",")}
        result[origin] = {
            "preflightStatus": pre_status, "preflightAllowOrigin": pre_headers.get("Access-Control-Allow-Origin"),
            "preflightAllowsPostContentType": pre_status == 204 and "post" in pre_methods and "content-type" in pre_request_headers,
            "postStatus": post_status, "postAllowOrigin": post_headers.get("Access-Control-Allow-Origin"),
            "browserAllowed": (pre_status == 204 and post_status == 200 and
                               "post" in pre_methods and "content-type" in pre_request_headers and
                               allowed(pre_headers.get("Access-Control-Allow-Origin")) and
                               allowed(post_headers.get("Access-Control-Allow-Origin"))),
        }
    if not result["https://datatug.app"]["browserAllowed"]:
        raise ValueError(f"{url}: production DataTug CORS admission failed")
    return result


def run() -> dict:
    pinned_rows, columns = provider_state()
    result = {}
    for label, (url, from_clause, database, collection) in SOURCES.items():
        dtql = query(from_clause)
        status, _, raw = request(url, method="POST", body=json.dumps({"query": dtql}, separators=(",", ":")).encode())
        if status != 200:
            raise ValueError(f"{label}: HTTP {status}")
        result[label] = {
            "endpoint": url, "expectedDatabase": database, "expectedCollection": collection,
            "query": dtql, "querySha256": sha256(dtql.encode()),
            **verify_response(raw, label, columns, pinned_rows),
            "cors": cors(url, from_clause),
        }
    if result["sqlite"]["canonicalRowsSha256"] != result["postgresql"]["canonicalRowsSha256"]:
        raise ValueError("public SQLite and PostgreSQL Orders rows differ")
    return {
        "format": "demodb-public-orders-evidence/v1",
        "observedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "Complete projected Orders rows only, at observation time; not all database objects or a signed live API rights assertion.",
        "provider": {
            "repository": "https://github.com/demo-db/northwind",
            "sourcePath": "data-source/source.sqlite", "sourceSha256": SOURCE_SHA256,
            "importManifestPath": "artifacts/hosting-imports/manifest.json",
            "ordersRows": 830, "ordersSha256": ORDERS_SHA256,
            "rights": {"origin": "provider-declared-upstream-MIT", "upstreamRepository": "https://github.com/jpwhite3/northwind-SQLite3",
                       "upstreamRevision": UPSTREAM_REVISION, "recipePath": "src/create.sql + src/update.sql",
                       "license": "MIT", "noticePath": "data-source/LICENSE.md", "noticeSha256": NOTICE_SHA256},
        },
        "sources": result,
        "equivalentToPinnedOrders": True,
        "limitations": [
            "The public API does not sign or return a source-rights declaration or the PostgreSQL import manifest.",
            "SQLite full-projection execution.sources may be absent; this verifier uses endpoint identity plus complete row equivalence.",
            "Public row equivalence cannot prove private hosting configuration, future immutability, or tables other than Orders.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the timestamped receipt to this path instead of stdout")
    args = parser.parse_args()
    try:
        receipt = json.dumps(run(), indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(receipt, encoding="utf-8")
        else:
            print(receipt, end="")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"public Orders verification failed: {error}", file=sys.stderr)
        sys.exit(1)
