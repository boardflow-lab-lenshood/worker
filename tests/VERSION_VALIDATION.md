# Offline worker version acceptance

Card: `f312973006e748058646b4729f18c7aa` (七卡 F). Execution:
`ea5c6bd748e14690bb25e10f646bb39c`, DEVELOP, delivery round 1, baseline epoch 1.
Spec revision: `137f4ab0435b4ddfa8bf8a1b95d98079`.

Only worker is changed. The dedicated branch is
`codex/f3129730-worker-offline-version`, based on the fixed worker SHA
`c955288f250cfc4edf74675e106859aff56c6c60`. Its PR targets
`codex/arena-seven-20261103-latest`. No integration branch or actual main was
updated during development.

## Implementation

`Main` recognizes the sole `--version` argument before reading environment
configuration, constructing either connection, doing DNS lookup or executing
schema SQL. It serializes the required service/version JSON, writes one newline
and returns 0. The existing no-argument path and vote processing are retained.

## Actual build

Evidence is committed under [evidence/f3129730](evidence/f3129730).
The newly built acceptance image is `worker-f3129730:offline-version`, image ID
`sha256:f8e7991e25c954ebb277ed6691999378e9ae397f6b7ea6bf88abc9ce2925df1f`.
`source-hashes.json` records SHA-256 hashes of the exact Program.cs and project
file compiled; these were checked against the final checkout.

The local Docker CLI has no buildx plugin. The first buildx command failed before
compilation. The legacy builder also cannot automatically supply BuildKit's
platform argument; declaring it explicitly reached restore but the container
could not resolve/access NuGet (`NU1301`). That owned restore container was
removed. These failed attempts and their actual exit codes remain in
`build*.log` / `build*-exit-code.txt`.

The successful real multi-stage build used `Dockerfile.offline-build`, the cached
.NET 7 SDK, the project's unchanged NuGet package versions and public dependency
packages downloaded on the host. `package-downloads.json` records their public
URLs, versions and hashes. `dotnet restore -a arm64 --source /packages` and
`dotnet publish -c release -o /app -a arm64 --self-contained false --no-restore`
both succeeded with the Docker build network disabled. The published output
was copied onto the exact baseline's cached .NET runtime image, replacing its
worker binaries. See `build-offline-command.txt`, `build-offline.log`, and
`build-offline-exit-code.txt` (0). The production Dockerfile is unchanged; the
acceptance build uses the recorded local recipe rather than claiming buildx ran.

## Offline CLI: 2 passed

The actual command is recorded in `test-commands.json`. Both missing and
intentionally invalid database configuration were tested in fresh containers
with `--network none`, read-only root filesystem, dropped capabilities, and a
private 16 MiB `/tmp` tmpfs. No PostgreSQL or Redis exists in their network.
The invalid connection string would fail immediately if Npgsql initialization
were attempted first.

Both invocations produced exactly:

```json
{"service":"worker","version":"arena-seven-20261103"}
```

Each stdout ends with exactly one newline; stderr is empty; the Docker command
and process exit codes are 0. Actual image ID, command, network configuration,
stdout and exit codes are in `version-with-tmpfs/*.json`, with the passing
unittest log and cleanup record alongside them.

The initial read-only CLI fixture omitted writable `/tmp` and CoreCLR failed
before entering application code (`0x8007000E`, exit 137). Those failures remain
in `version/`. Giving the runtime its private tmpfs fixed this fixture while
retaining complete network isolation; the final test runner includes it.

## Default path: 5 passed, including 44 invalid-input cases

`tests/integration.py` actually started the new image without CLI arguments on a
unique internal network alongside exclusive Redis 7 and PostgreSQL 15. Every
resource carries this card's ownership label and no ports are published.

The passing regression covers existing message rejection and privacy behavior,
valid a/b messages following invalid input, exact ID boundaries, vote replacement
and propagation of a real database constraint error. The deliberate constraint
failure occurred only in this test's owned PostgreSQL fixture.

`integration/legacy-vote.json` records real legacy messages containing only
`voter_id` and `vote`, the initial `a` row, replacement `b` row, drained queue
(length 0), and the worker still running after processing. No trace field or
upstream service is needed. See `integration/tests.log`, `invalid-cases.json`,
`worker.log`, `container-config.json`, `network-config.json` and `fixture.json`.
The five tests passed in 72.424 seconds.

## Cleanup and other checks

Both CLI runs and the integration suite removed their owned containers, anonymous
volumes and network. `cleanup-verification.json` records the final card-label
query returning no containers or networks; the built image is retained as
acceptance evidence. `git diff --check`, test-runner Python syntax checks and
fixed-base ancestry checks also passed. This invocation's required_checks list
is empty; the behavior checks above implement the card's actual acceptance.
