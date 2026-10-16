#!/usr/bin/env python3
"""Local, fail-closed checks for the public SQLite aggregate admission."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("verify_country_count", ROOT / "scripts/verify-public-shipping-country-count.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class ShippingCountryCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = verifier.local_counts()
        cls.sidecar = json.loads(verifier.OUTPUT.read_text())

    def response(self):
        return {
            "columns": ["ShipCountry", "orders"], "complete": True,
            "execution": {"route": "database", "rowsReturned": 21, "sources": [{"database": "northwind", "collection": "Orders"}]},
            "records": [{"data": {"ShipCountry": country, "orders": count}} for country, count in self.expected],
        }

    def check(self, value):
        return verifier.verify_result(json.dumps(value, separators=(",", ":")).encode(), self.expected)

    def test_sidecar_binds_saved_query_original_rights_and_full_aggregate(self):
        sidecar = self.sidecar
        full_bytes = (ROOT / verifier.RIGHTS_PIN["path"]).read_bytes()
        original = json.loads(full_bytes)
        descriptor = json.loads((ROOT / "ovdb-database.json").read_text())
        self.assertEqual(hashlib.sha256(full_bytes).hexdigest(), sidecar["rightsPin"]["sha256"])
        self.assertEqual(len(full_bytes), sidecar["rightsPin"]["bytes"])
        self.assertEqual(sidecar["sourceRights"], original["sourceRights"])
        self.assertEqual(sidecar["usedSourceIds"], original["usedSourceIds"])
        self.assertEqual(sidecar["sourceRights"][0]["source"]["serverId"], descriptor["serverId"])
        self.assertEqual(sidecar["savedQuery"], verifier.QUERY_PIN)
        self.assertEqual(sidecar["savedQuery"]["sha256"], hashlib.sha256(verifier.QUERY.encode()).hexdigest())
        self.assertEqual(sidecar["admission"]["query"], verifier.QUERY)
        self.assertEqual(sidecar["admission"]["endpoint"], verifier.ENDPOINT)
        self.assertEqual(sidecar["admission"]["canonicalRowsSha256"], verifier.canonical_sha256(self.expected))
        self.assertEqual(sidecar["admission"]["rows"], len(self.expected))
        self.assertEqual(sidecar["admission"]["totalOrders"], sum(count for _, count in self.expected))
        self.assertEqual(sidecar["admission"]["executionSource"], {"database": descriptor["localId"], "collection": "Orders"})

    def test_complete_exact_21_groups_pass(self):
        self.assertEqual(self.check(self.response()), self.expected)

    def test_incomplete_limited_or_wrong_source_fails(self):
        for mutation in (
            lambda r: r.update(complete=False),
            lambda r: r.update(truncated=True),
            lambda r: r["execution"].update(sources=[{"database": "northwind-postgresql", "collection": "Orders"}]),
            lambda r: r["execution"].update(rowsReturned=20),
        ):
            response = self.response()
            mutation(response)
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.check(response)

    def test_partial_duplicate_invalid_and_changed_counts_fail(self):
        for mutation in (
            lambda r: r["records"].pop(),
            lambda r: r["records"][0]["data"].update(orders=17),
            lambda r: r["records"][0]["data"].update(orders=True),
            lambda r: r["records"][0]["data"].update(orders=-1),
            lambda r: r["records"][0]["data"].update(ShipCountry=None),
            lambda r: r["records"][1]["data"].update(ShipCountry="Argentina"),
        ):
            response = self.response()
            mutation(response)
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.check(response)


if __name__ == "__main__":
    unittest.main()
