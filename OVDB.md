# OpenVaultDB publisher contract

[`ovdb.yaml`](ovdb.yaml) publishes Northwind as a read-only SQLite database under its Northwind database identity. Its canonical URL is `https://northwind.demodb.dev/ovdb/dbs/northwind`; discovery is served from `https://northwind.demodb.dev/.well-known/openvaultdb` and points to the OpenVaultDB service deployment.

The explicit recordsets are the 13 native table names. ModelSpec requires published entity identifiers without spaces, so the manifest's `recordset_entities` maps native `Order Details` to ModelSpec entity `OrderDetails`; the canonical SQLite table and every DemoDB site URL keep the upstream name. Views remain available in DemoDB schema metadata and SQLite downloads. Query/read capability is advertised after the OpenVaultDB service mounts this exact pinned fixture.
