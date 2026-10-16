#!/usr/bin/env python3
"""Admission checks for the bounded public Orders receipt verifier."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("verify_public_orders", SCRIPTS / "verify-public-orders.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class PublicOrdersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pinned, cls.columns = verifier.provider_state()

    def response(self, label, *, iso_dates=False):
        rows = []
        for values in self.pinned:
            record = dict(zip(verifier.FIELDS, values))
            if iso_dates:
                for field in verifier.DATES:
                    if record[field] is not None:
                        record[field] += "T00:00:00Z"
            else:
                if record["Freight"] is not None:
                    record["Freight"] = str(record["Freight"])
            rows.append({"data": record})
        result = {"complete": True, "records": rows}
        if label == "postgresql":
            result["columns"] = list(verifier.FIELDS)
            result["execution"] = {"rowsReturned": 830, "sources": [{
                "database": "northwind-postgresql", "collection": verifier.PG_COLLECTION,
            }]}
        return result

    def check(self, label, response):
        raw = json.dumps(response, separators=(",", ":")).encode()
        return verifier.verify_response(raw, label, self.columns, self.pinned)

    def test_pinned_source_and_both_valid_response_shapes(self):
        self.assertEqual(len(self.pinned), 830)
        sqlite = self.check("sqlite", self.response("sqlite", iso_dates=True))
        postgres = self.check("postgresql", self.response("postgresql"))
        self.assertFalse(sqlite["executionSourcesPresent"])
        self.assertTrue(postgres["executionSourcesPresent"])
        self.assertEqual(sqlite["providerOrdersSha256"], verifier.ORDERS_SHA256)
        self.assertEqual(sqlite["canonicalRowsSha256"], postgres["canonicalRowsSha256"])

    def test_wrong_postgres_collection_fails(self):
        response = self.response("postgresql")
        response["execution"]["sources"][0]["collection"] = "Orders"
        with self.assertRaisesRegex(ValueError, "source identity"):
            self.check("postgresql", response)

    def test_incomplete_or_continued_response_fails(self):
        for change in ({"complete": False}, {"nextCursor": "remaining"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "incomplete or continued"):
                self.check("sqlite", self.response("sqlite") | change)

    def test_full_row_parity_detects_field_changes(self):
        response = self.response("postgresql")
        response["records"][329]["data"]["ShipAddress"] = "changed address"
        with self.assertRaisesRegex(ValueError, "fields differ"):
            self.check("postgresql", response)

    def test_truncation_and_extra_projection_fail(self):
        response = self.response("sqlite")
        response["records"].pop()
        with self.assertRaisesRegex(ValueError, "830 records"):
            self.check("sqlite", response)
        response = self.response("sqlite")
        response["records"][0]["data"]["unexpected"] = 1
        with self.assertRaisesRegex(ValueError, "all 14 fields"):
            self.check("sqlite", response)

    def test_query_is_ordered_and_bounded(self):
        for _, from_clause, _, _ in verifier.SOURCES.values():
            query = verifier.query(from_clause)
            self.assertIn("orderBy: [{field: OrderID}]", query)
            self.assertIn("limit: 1000", query)
            self.assertEqual(query.count("{field:"), 15)


if __name__ == "__main__":
    unittest.main()
