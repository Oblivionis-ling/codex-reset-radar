# Legacy V1 runtime data

This directory contains the local V1 database and runtime logs.

- It is not used by the V2 runtime.
- It is intentionally ignored by Git except for this README.
- Do not delete or modify it until V1-to-V2 migration and historical review are complete.
- V2 opens the legacy SQLite database in read-only mode when the migration tool is run.
