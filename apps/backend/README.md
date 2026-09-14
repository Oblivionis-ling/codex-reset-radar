# V2 Backend

The active V2 Backend is a small FastAPI application backed by a new SQLite database under runtime/data. It does not start a GitHub Mirror task, publish public-data, or depend on Pages.

Run all commands from the repository root. See docs/v2/local-development.md.

The legacy_v1 directory is retained as transitional source reference and migration context. It is not imported by the V2 startup path.
