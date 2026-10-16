# Public Northwind Orders evidence

The [timestamped receipt](public-orders-evidence-2026-10-16.json) records a
bounded read-only comparison of all 830 `Orders` rows and all 14 fields from
the public SQLite and PostgreSQL DTQL endpoints against this provider's pinned
`data-source/source.sqlite`. The [verifier](https://github.com/demo-db/northwind/blob/de7f81c591abccc30fb9a0a58f44be9fd7265cd6/scripts/verify-public-orders.py)
builds and records both exact queries, compares every normalized value, checks
the published provider `Orders` checksum and the PostgreSQL execution source,
and probes CORS for DataTug production and local browser origins.

Run from the provider root with Python 3.10 or newer and public network access:

```sh
python3 scripts/verify-public-orders.py
python3 -m unittest scripts/test-public-orders.py
```

To refresh the committed receipt after reviewing the live result, run:

```sh
python3 scripts/verify-public-orders.py \
  --output artifacts/hosting-imports/public-orders-evidence-YYYY-MM-DD.json
```

This receipt verifies the public `Orders` values **at its observation time**.
The public PostgreSQL response names collection
`pg1_AAAACW5vcnRod2luZAAAAAZPcmRlcnM` and reports `complete: true`; the
full SQLite projection reports `complete: true` but currently omits
`execution.sources`. Its source identity is inferred from the endpoint and
complete equality with the pinned fixture. Consumers must check the response
shape of each actual query.

The MIT attribution and notice come from the provider's pinned upstream
revision in `manifest.json` and `data-source/LICENSE.md`. The live API does not
return a signed rights statement. Equality of `Orders` does not prove the
PostgreSQL import manifest, other tables, or future hosted state. The local
PostgreSQL browser origin `http://localhost:4200` lacked CORS admission when
the receipt was made; anonymous command-line requests and
`https://datatug.app` browser requests were admitted.

The [DemoDB SQLite Orders rights declaration](source-rights.json) covers only
`ovdb:demodb.dev/northwind/Orders`. It binds the MIT notice and pinned provider
files to the receipt's complete 830-row digest. A browser must independently
verify a fresh, complete SQLite response against that digest and exact query
before using the declaration. The SQLite response does not provide
`execution.sources`; the declaration identifies DemoDB's own endpoint and
recordset. It does not declare rights for the separately owned PostgreSQL API.

This provider repository stores the reproducible evidence. The matching DemoDB
website build publishes byte-verified copies of this README, its receipt, and
the SQLite declaration at
`https://northwind.demodb.dev/evidence/public-orders/` when that build is
deployed. The provider repository remains the source of the pinned files.
