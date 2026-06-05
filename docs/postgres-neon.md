# PostgreSQL / Neon database mode

This project still defaults to SQLite through `DATABASE_PATH`. For third-party
database deployments such as Neon, set `DATABASE_URL` to a PostgreSQL URL before
starting the app:

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require
```

## Behavior

- Empty `DATABASE_URL`: keeps the existing SQLite behavior.
- `postgres://...` or `postgresql://...`: routes `sqlite3.connect(...)` through a
  PostgreSQL compatibility adapter.
- `sqlite://...`, `sqlite3://...`, or `file:`: ignored so the current SQLite path
  remains active.
- Any other scheme: startup fails early with a clear configuration error.

## Notes for Neon

- Neon requires TLS for most hosted connections, so keep `sslmode=require` in
  the URL unless your Neon project says otherwise.
- On first startup, the app creates the same application tables in PostgreSQL.
- This does not automatically copy data from an existing SQLite database. Export
  or migrate data separately before switching production traffic.

## Compatibility scope

The adapter translates the SQLite patterns used by the current application,
including `?` parameters, `INSERT OR IGNORE`, settings upserts, basic `PRAGMA`
table inspection, `BEGIN IMMEDIATE`, and common SQLite schema fragments.

This is intended as the first third-party database support path. If future
schema work grows beyond the compatibility adapter, the next step should be a
proper migration layer such as Alembic.
