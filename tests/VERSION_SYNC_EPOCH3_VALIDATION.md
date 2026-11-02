# Worker version — epoch 3 synchronization acceptance

Card `f312973006e748058646b4729f18c7aa`, execution
`49582800d7304bc1a93c578567d4cbde`, action `SYNC_MAIN`.
Delivery round 1, baseline epoch 3, spec revision
`137f4ab0435b4ddfa8bf8a1b95d98079`.

The original branch `codex/f3129730-worker-offline-version`, worktree and
non-draft [PR #5](https://github.com/boardflow-lab-lenshood/worker/pull/5) are reused.
The PR targets `codex/arena-seven-20261103-latest`.

## Exact fixed baseline synchronized

The fixed worker SHA `36d5f71fd38f9c194b0650fdd5268015e7377083` was fetched
and merged into the existing branch. Merge commit
`a667d8492575447d7a1378fee0abe6c72c61b160` has parents
`f7e775cfabe4b1546e6169f02f0420bc32776ec8` (original F branch) and the exact
fixed worker SHA. `git merge-base --is-ancestor` passed.

The test-fixture initialization conflict was resolved by preserving both the
baseline's old-table migration/data-preservation checks and F's actual Docker
configuration/ownership evidence. The trace runner gained the same optional
`--owner-card` argument as its inherited fixture. Assertions were retained.

Compared with that fixed baseline, application code adds only the early
`--version` branch. The baseline's trace validation, persistence, migration and
logging remain present. The F version path still emits exactly
`{"service":"worker","version":"arena-seven-20261103"}` plus one newline and
returns 0 before reading configuration or initializing dependencies.

## Actual synchronized source rebuilt

The successful build used the same established local offline recipe, copied to
[evidence/f3129730-epoch3/Dockerfile.offline-build](evidence/f3129730-epoch3/Dockerfile.offline-build).
`build-command.json`, `build.log` and `build-result.json` record the actual command
and exit 0. This is a real .NET 7 restore and publish of the synchronized source
with `docker build --network none`, using host-downloaded public NuGet packages
whose versions and SHA-256 hashes are in `public-packages.json`.

The cached `c955288f250cfc4edf74675e106859aff56c6c60` image supplies only the
.NET runtime; all published `/app` output is rebuilt from the epoch 3 merge.
It does not substitute that older application for the synchronized application.
The normal repository Dockerfile remains unchanged; local buildx/NuGet network
limitations from the original acceptance are handled by this recorded recipe.

The acceptance image is `worker-f3129730:epoch3`, ID
`sha256:360dbc094a9ba6e4601dd4ba36f661215937c4d72924988cf6b771a8d3ae68b6`.
`source-hashes.json` identifies the tested merge commit and exact Program.cs and
Worker.csproj hashes. These hashes were checked against the final checkout.
`image.json` and per-container inspections confirm the tested image identity.

## Real acceptance results

All commands and actual return codes are in
[evidence/f3129730-epoch3/test-runs.json](evidence/f3129730-epoch3/test-runs.json).
Each runner had a 240-second limit and finished without timing out.

| Suite | Result | Evidence |
| --- | --- | --- |
| Offline CLI | 2 passed, exit 0 | `version/tests.log`, per-case JSON |
| Default worker | 5 passed, exit 0; all 64 invalid-input cases passed | `integration/tests.log`, `integration/invalid-cases.json` |
| Trace regression | 16 passed, exit 0, including 5 inherited consumption tests | `trace/tests.log`, `trace/invalid-cases.json` |

There were 23 test executions in total. The trace suite intentionally reruns the
five inherited worker regressions alongside its trace-specific cases.

### Offline CLI

Both missing and deliberately invalid database configuration were tested with
`--network none`, read-only root filesystem, dropped capabilities and a private
16 MiB `/tmp` tmpfs required by .NET. There are no Redis/PostgreSQL services in
that network. Each result has the exact one-line JSON stdout, empty stderr and
actual process exit code 0. The container inspection records network mode `none`
and the same newly built image ID.

### Real vote consumption and migration

Each service suite owns a unique internal Docker network, Redis 7, PostgreSQL 15
and a worker started without arguments. Resources are labeled with this card;
no ports are published. Actual configuration and ownership are recorded in
`fixture.json`, `container-config.json` and `network-config.json`.

`integration/migration.json` records an existing old-format table row surviving
startup with nullable trace_id. `integration/legacy-vote.json` records an actual
old-format message writing choice `a`, then a second message for the same voter
replacing it with `b`, leaving one row, an empty queue and a live worker.
The queue/database tests also cover input/privacy rejection and exact ID bounds.

The trace suite verifies legacy messages, trace retention/replacement, clearing
trace with a legacy message, old-schema migration, valid trace boundaries,
invalid traces followed by a valid message, and data remaining across worker
restarts. The tests deliberately inject a database constraint failure and stop
only the suite's own Redis; the worker exits nonzero and emits the expected
failure evidence. These expected failure paths passed their assertions.

## Cleanup and remaining scope

All suites saved cleanup records. `verification.json` records actual final
card-label queries returning no owned containers or networks, passing test
counts and matching source hashes. Test-created anonymous volumes were removed
with their containers. The labeled built image is retained as evidence.

`git diff --check`, Python runner syntax checks and the exact fixed-base ancestry
check passed. This invocation's required_checks lists are empty; the real
behavior and synchronization checks above were performed for acceptance.
No new F-specific environment variables or schema changes are introduced. The
trace_id migration already belongs to the fixed baseline. The integration branch,
actual main and other service repositories were not updated by this development
execution.
