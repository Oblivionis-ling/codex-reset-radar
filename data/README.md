# Data policy

Git stores schemas, migration code, and small sanitized fixtures only.

Real runtime databases, large post corpora, browser diagnostics, notification delivery logs, and raw analysis exports do not belong in the repository. The V1 runtime database remains under backend/data as a local read-only migration source.
