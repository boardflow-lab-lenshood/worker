# Worker CLI and input integration checks

## Offline version query

`docker run --rm --network none <worker-image> --version` emits exactly
`{"service":"worker","version":"arena-seven-20261103"}` followed by a newline
and exits 0. The entry point handles this argument before reading database
configuration, constructing connections, resolving Redis or creating tables.
Invoking the image without arguments retains the normal worker behavior.

After building the checkout, run:

```sh
python3 tests/version.py --image worker-input-validation:test --evidence-dir /tmp/worker-version-evidence --owner-card <card-id>
```

The CLI tests use labeled, read-only containers with `--network none`, a private
16 MiB `/tmp` tmpfs required by the .NET runtime, no services and either missing
or deliberately invalid database configuration. They assert
exact stdout, empty stderr and process exit 0 with a 15-second command limit.
JSON evidence includes the actual command, image ID, network configuration,
output and exit codes. Owned containers are removed on success or failure.

## Default worker compatibility

Run from the repository root with Docker (BuildKit/buildx), Python 3.10+, and access to the public .NET, Redis and PostgreSQL images:

```sh
docker buildx build --load --progress=plain -t worker-input-validation:test .
python3 tests/integration.py --image worker-input-validation:test --evidence-dir /tmp/worker-input-validation-evidence --owner-card <card-id>
```

`--image` must point to an image built from the checkout being tested. The runner does not use a shared application environment or pre-existing databases. It creates a unique internal Docker network, Redis 7, PostgreSQL 15, and the worker, with no published ports. Database credentials are generated per run and supplied through environment variables. Each external command and readiness wait has a timeout. Class cleanup removes the owned containers, their anonymous volumes and the network, including on assertion failure. The built worker image is retained for reuse.

The test suite exercises:

- Malformed and empty JSON, invalid escaped Unicode in field values and names, trailing content, non-object JSON, missing fields, each non-string JSON field type, blank and overlong voter IDs (including Unicode), PostgreSQL-incompatible NUL IDs, and all invalid vote categories. Each rejection checks the database remains empty, the worker stays alive, and the log contains only the rejection event and reason, with no canary payload.
- Valid `a` and `b` messages following rejected input.
- One-character and 255-character voter IDs, including non-BMP Unicode, date-shaped strings, and IDs with surrounding whitespace whose exact value must be preserved.
- An existing voter changing from `a` to `b`, retaining exactly one row.
- A real PostgreSQL check-constraint failure on a valid `b` vote. The worker must exit with status 1, emit the database exception and SQLSTATE `23514`, and avoid misclassifying the failure as rejected input. This deliberate fault occurs only in the disposable database and runs last.

Evidence is saved under `--evidence-dir`: `tests.log` (unittest results), `worker.log` (actual worker output), `invalid-cases.json` (passing invalid cases), `legacy-vote.json` (real rows before/after an old-format vote update and drained queue), `fixture.json`, `container-config.json` and `network-config.json` (ownership and isolation), and `cleanup.txt` (removed resource names). A nonzero exit means the suite or fixture failed; review the saved logs before reporting success. No queue, table or vote/result API changes are required.
