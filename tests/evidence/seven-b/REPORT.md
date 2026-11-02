# B storage integration evidence

Card: `5c9d713506a0481c9987c941f5725862`
Execution: `cdc40638b9134bdbae567b9265a7bc80`
Specification: `3836c777a2c64a07b0f6c9766b838d39`, delivery round 1, baseline epoch 1.

Worker base: `c955288f250cfc4edf74675e106859aff56c6c60`.
Tested source/build recipe commit: `6eae382ed28b95a1398b3825ea8335de1cf79abf`.
Branch: `codex/seven-b-trace-5c9d7135`.
Integration target: `codex/arena-seven-20261103-latest`.
The evidence-only commit following the tested source does not change the program,
build recipes or test runners. The external PR/Issue handoff records the final
head and its verification. No vote/result/delivery repository is modified.

## Commands actually executed

Commands ran from the Agent workspace, with the checkout under
`cards/5c9d713506a0481c9987c941f5725862/worker`:

```sh
DOCKER_BUILDKIT=0 docker build -f cards/5c9d713506a0481c9987c941f5725862/worker/tests/Dockerfile.offline -t worker-seven-b:5c9d7135 cards/5c9d713506a0481c9987c941f5725862/worker
python3 cards/5c9d713506a0481c9987c941f5725862/worker/tests/trace_integration.py --image worker-seven-b:5c9d7135 --evidence-dir cards/5c9d713506a0481c9987c941f5725862/evidence/integration-run-1
git -C cards/5c9d713506a0481c9987c941f5725862/worker merge-base --is-ancestor c955288f250cfc4edf74675e106859aff56c6c60 HEAD
git -C cards/5c9d713506a0481c9987c941f5725862/worker diff --check
```

Committed outputs normalize terminal carriage returns and trailing whitespace;
original raw files remain in the Agent workspace evidence directory.
Actual build output: `build-offline.log` ends with successful image creation.
Image: `sha256:455a8a6b478a652cfd53fbc396e47ec6803140ebfdca3989d513f8c8a95c9986`.
Actual runner output: `tests.log`, **16 tests passed in 128.441 seconds**.
`invalid-traces.json`: **27/27** invalid trace values rejected.
`invalid-cases.json`: **44/44** existing invalid input cases rejected.
Malformed escaped trace Unicode is covered separately.
The supplied `required_checks` list is empty; the real integration suite is the
change-specific self-test. No code-hosting CI check result is asserted here.

## Database, queue and error observations

- `migration.json` preserves the old `pre-migration` row and its `b` vote with
  NULL trace, alongside a consumed old-format readiness vote. The test asserts
  the new column is nullable `character varying(64)`.
- `repeated-startup.json` retains the same tracked row after two worker restarts.
- `valid-traces.json` records exact accepted ASCII traces, including 1- and
  64-character boundaries, without conversion.
- `trace-replacement.json` records the newest trace for an existing voter,
  including a new trace with an unchanged vote choice.
- `legacy-insert.json` and `legacy-clearing.json` show NULL on old-format insert
  and on a later old-format update. The latter no longer belongs to the old trace.
- `invalid-update-preserves-row.json` shows an invalid trace update does not
  change the existing vote or trace.
- `continuation.json` records the legitimate traced vote after a bad trace.
- Normal storage snapshots include the real Redis queue length (0 after consumption).
- `worker.log` contains short JSON rejection events without the canary payload,
  a full `Npgsql.PostgresException` stack with SQLSTATE `23514` for the owned
  constraint fault, and a full `RedisServerException` stack for the owned queue
  `WRONGTYPE` fault. Both faults exit status 1; neither increments rejection count.
- `infrastructure-failure.json` captures the Redis fault outcome and unchanged
  rejection count (75 before/after). `cleanup.txt` lists all four owned resources
  removed with an empty error section. Anonymous PostgreSQL volumes are removed
  using `docker rm -f -v`. No ports or shared candidate services are used.

## Build limitation

This host has no Docker buildx (`build.log`). The legacy builder needs a global
platform argument (`build-legacy.log`); a temporary adjusted recipe reached
restore but NuGet failed with `NU1301` (`build-native.log`). The stalled owned
restore container was removed. `tests/Dockerfile.offline` successfully compiled
the current `Program.cs` using the cached SDK and the exact baseline image's
existing dependency assemblies, retaining its runtime configuration. It replaces
the old program with a newly compiled assembly. The current program was exercised
in real containers; a fresh download/restore of NuGet packages was not verified.
Production Dockerfile and package versions remain unchanged.

## C handoff boundary

A: https://github.com/boardflow-lab-lenshood/delivery/issues/51
B: https://github.com/boardflow-lab-lenshood/delivery/issues/52
C: https://github.com/boardflow-lab-lenshood/delivery/issues/53

B independently validates Redis -> worker -> PostgreSQL using the fixed A
message contract. C must read the real A/B PR handoffs, check out their tested
exact commits, and complete its own isolated HTTP joint validation before C is
reported complete. This report does not claim that C has completed that work.
Later source changes or baseline synchronization require refreshed evidence.
