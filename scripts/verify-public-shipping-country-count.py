#!/usr/bin/env python3
"""Verify the saved Northwind SQLite country-count query against pinned Orders.

The provider declares terms for its own SQLite endpoint. This observation does
not assert rights for the separately owned PostgreSQL endpoint or future rows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("verify_public_orders", SCRIPTS / "verify-public-orders.py")
orders = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orders)

ENDPOINT = "https://demodb.dev/ovdb/v1/databases/northwind/dtql"
ORIGIN = "https://datatug.app"
QUERY = (
    "from: {name: Orders}\n"
    "groupBy: [{field: ShipCountry}]\n"
    "orderBy: [{field: ShipCountry}]\n"
    "columns: [{field: ShipCountry}, {aggregate: {function: count, args: [{star: true}]}, as: orders}]\n"
    "limit: 100\n"
)
QUERY_PIN = {
    "id": "northwind-shipping-country-count-sqlite",
    "repository": "https://github.com/datatug/datatug-demo-project",
    "revision": "d65384f3fbd99047e2955d92636a134f4b01e851",
    "path": "demo-project-1/queries/demodb/northwind-shipping-country-count-sqlite.query.dtql",
    "sha256": "2e320d487d7bbe7dbfc53abc55c08d12eb80a2e79b34cfe15a2148fa362acc9a",
    "bytes": 194,
}
RIGHTS_PIN = {
    "repository": "https://github.com/demo-db/northwind",
    "revision": "83ea600a7eae8b35ad33bf4c53bab6440d697850",
    "path": "artifacts/hosting-imports/source-rights.json",
    "sha256": "50454d5f30db615178fcd0c6a846854f9434f4f93bb44835cc75fdad4af52e30",
    "bytes": 4447,
}
OUTPUT = ROOT / "artifacts/hosting-imports/shipping-country-count-rights.json"
MAX_AGGREGATE_BYTES = 64 * 1024
CANONICALIZATION = "UTF-8 JSON array of [ShipCountry, orders] pairs in ascending ShipCountry order, without whitespace; orders are positive safe integers."


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_counts() -> list[list]:
    rows, _ = orders.provider_state()  # checks the full 830-row provider checksum
    index = orders.FIELDS.index("ShipCountry")
    countries = [row[index] for row in rows]
    if len(countries) != 830 or any(not isinstance(value, str) or not value or value.strip() != value for value in countries):
        raise ValueError("pinned Orders contain a null or blank shipping country")
    counts = Counter(countries)
    grouped = [[country, counts[country]] for country in sorted(counts)]
    if len(grouped) != 21 or sum(count for _, count in grouped) != 830:
        raise ValueError("pinned Orders country groups changed")
    return grouped


def canonical_sha256(rows: list[list]) -> str:
    return sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def verify_result(raw: bytes, expected: list[list]) -> list[list]:
    if len(raw) > MAX_AGGREGATE_BYTES:
        raise ValueError("aggregate response exceeds byte bound")
    result = json.loads(raw)
    if not isinstance(result, dict) or set(result) != {"columns", "complete", "execution", "records"}:
        raise ValueError("aggregate response has unsupported or limited shape")
    if result["complete"] is not True or result["columns"] != ["ShipCountry", "orders"]:
        raise ValueError("aggregate result is incomplete or has changed columns")
    execution = result["execution"]
    if not isinstance(execution, dict) or execution.get("rowsReturned") != 21 or execution.get("sources") != [{"database": "northwind", "collection": "Orders"}]:
        raise ValueError("aggregate execution source or count differs")
    records = result["records"]
    if not isinstance(records, list) or len(records) != 21:
        raise ValueError("aggregate must contain exactly 21 groups")
    actual = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"data"} or not isinstance(record["data"], dict) or set(record["data"]) != {"ShipCountry", "orders"}:
            raise ValueError("aggregate record has changed shape")
        country, count = record["data"]["ShipCountry"], record["data"]["orders"]
        if not isinstance(country, str) or not country or country.strip() != country or type(count) is not int or count <= 0 or count > 2**53 - 1:
            raise ValueError("aggregate has invalid country or count")
        actual.append([country, count])
    if actual != expected or sum(count for _, count in actual) != 830:
        raise ValueError("aggregate groups differ from pinned Orders")
    return actual


def live_counts(expected: list[list]) -> list[list]:
    status, headers, _ = orders.request(ENDPOINT, method="OPTIONS", origin=ORIGIN)
    if status != 204 or headers.get("Access-Control-Allow-Origin") != "*" or "POST" not in headers.get("Access-Control-Allow-Methods", "") or "content-type" not in headers.get("Access-Control-Allow-Headers", "").lower():
        raise ValueError("production browser origin lacks aggregate query preflight admission")
    body = json.dumps({"query": QUERY}, separators=(",", ":")).encode("utf-8")
    status, headers, raw = orders.request(ENDPOINT, method="POST", body=body, origin=ORIGIN)
    if status != 200 or headers.get("Access-Control-Allow-Origin") != "*":
        raise ValueError("production browser origin lacks aggregate response admission")
    return verify_result(raw, expected)


def expected_artifact(observed_at: str) -> dict:
    original_bytes = (ROOT / RIGHTS_PIN["path"]).read_bytes()
    if len(original_bytes) != RIGHTS_PIN["bytes"] or sha256(original_bytes) != RIGHTS_PIN["sha256"]:
        raise ValueError("original full-row rights artifact changed")
    query_bytes = QUERY.encode("utf-8")
    if len(query_bytes) != QUERY_PIN["bytes"] or sha256(query_bytes) != QUERY_PIN["sha256"]:
        raise ValueError("saved aggregate query text changed")
    original = json.loads(original_bytes)
    expected = local_counts()
    actual = live_counts(expected)
    return {
        "format": "demodb-observed-aggregate-rights/v1",
        "scope": "DemoDB publisher declaration for its Northwind SQLite Orders recordset, applied only to this complete shipping-country aggregate query after a fresh result digest check; no PostgreSQL or future-state rights assertion.",
        "observedAtUtc": observed_at,
        "savedQuery": QUERY_PIN,
        "rightsPin": RIGHTS_PIN,
        "admission": {
            "endpoint": ENDPOINT,
            "query": QUERY,
            "querySha256": QUERY_PIN["sha256"],
            "complete": True,
            "rows": 21,
            "fields": ["ShipCountry", "orders"],
            "totalOrders": 830,
            "canonicalRowsSha256": canonical_sha256(actual),
            "canonicalization": CANONICALIZATION,
            "executionSource": {"database": "northwind", "collection": "Orders"},
        },
        "observation": {"origin": ORIGIN, "corsAllowOrigin": "*"},
        "sourceRights": original["sourceRights"],
        "usedSourceIds": original["usedSourceIds"],
        "limitations": [
            "The live SQLite aggregate must be rechecked for complete=true, its exact 21 groups, safe integer counts summing to 830, source identity, and canonical digest before admitting the publisher declaration.",
            "This declaration does not cover the separately owned PostgreSQL API or an incomplete, truncated, limited, changed, or differently sourced future response."
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write a fresh observed sidecar after verifying the live query")
    args = parser.parse_args()
    observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    candidate = expected_artifact(observed_at)
    if args.write:
        OUTPUT.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
    else:
        published = json.loads(OUTPUT.read_text())
        candidate["observedAtUtc"] = published["observedAtUtc"]
        if candidate != published:
            raise ValueError("published aggregate sidecar differs from verified query and pinned provider")
    print(f"Verified 21 SQLite country groups, 830 orders, SHA-256 {candidate['admission']['canonicalRowsSha256']}")


if __name__ == "__main__":
    main()
