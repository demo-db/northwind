---
ovdb: 1
publish: [./ovdb.yaml, ./ovdb-database.json]
---

# OpenVaultDB publisher contract

[`ovdb.yaml`](ovdb.yaml) publishes the legacy publisher contract, and [`ovdb-database.json`](ovdb-database.json) publishes the typed public database descriptor. Northwind's canonical database identity and human page are `https://demodb.dev/northwind/`. The descriptor is served at both `https://demodb.dev/northwind/ovdb-database.json` and `https://demodb.dev/ovdb/db/northwind/ovdb-database.json`; these locations contain identical bytes. Its shared server identity is `https://demodb.dev/ovdb`, and discovery is served from `https://demodb.dev/.well-known/openvaultdb`.

The explicit recordsets are the 13 native table names. ModelSpec requires published entity identifiers without spaces, so the manifest's `recordset_entities` maps native `Order Details` to ModelSpec entity `OrderDetails`; the canonical SQLite table and every DemoDB site URL keep the upstream name. Views remain available in DemoDB schema metadata and SQLite downloads. Query/read capability is advertised after the OpenVaultDB service mounts this exact pinned fixture.
