# Validation recorded 2026-11-02

Card: `0ccc299aefe347138d6c8748be05eb25`  
Execution: `99f3f4f4acbb43bebb42a052e0c2e264`  
Worker baseline: `63b108d38ff3f829fd1f1291d4e431cdae55700c`  
PR base: `codex/arena-three-20261102-latest`

The final disposable Redis 7 → worker (.NET 7) → PostgreSQL 15 suite passed all five tests in 157.589 seconds. All 44 invalid-input cases passed. Valid `a` and `b` votes after rejection, exact voter-ID boundaries, and the existing-voter `a` → `b` update passed. A deliberately installed database CHECK constraint produced SQLSTATE `23514`, an Npgsql exception stack, and worker exit code 1, proving that a database error is not swallowed as an input rejection.

The suite removed all four owned resources (worker, Redis, PostgreSQL including anonymous volumes, and the internal network); subsequent Docker inspection confirmed they were absent. A separate failure probe used an unavailable worker image with `--pull=never`: the suite failed as expected, log collection also failed, and all owned resource names were verified absent afterward. An evidence-counter probe deliberately failed one rejection-reason assertion and confirmed `total=1`, `passed=0`, and `cases=[]`.

The initial 42-case suite passed before adding the NUL-ID and malformed property-name cases. The final 44-case run used the rebuilt final application sources.

## Build environment

The installed Docker CLI did not have buildx; a public standalone buildx v0.38.1 binary was downloaded into the task workspace. Direct NuGet restore in Docker failed because the container could not resolve/reach `api.nuget.org`, while the host could reach the public NuGet feed.

For the successful build, the host downloaded the declared public packages and their transitive dependencies into a local feed. A temporary build context copied the exact final `Program.cs` and `Worker.csproj`; its Dockerfile retained the repository's build stages and commands, except for copying that feed and adding `--source /offline-feed` to `dotnet restore`. The repository Dockerfile was not modified. The resulting restore, Release publish, and runtime-image build succeeded with zero warnings and zero errors. This records the local workaround rather than claiming the original online restore succeeded.

Commands executed from the task workspace (with the worktree under `output/card-0ccc299a-worker`):

```sh
python3 output/prepare-worker-offline-build.py
output/tools/buildx-v0.38.1.darwin-arm64 build --progress=plain --load -t card-0ccc299a-worker:validation output/card-0ccc299a-offline-build
python3 output/card-0ccc299a-worker/tests/integration.py --image card-0ccc299a-worker:validation --evidence-dir output/card-0ccc299a-evidence/final
git -C output/card-0ccc299a-worker diff --check
```

Application source SHA-256 values were verified against the built snapshot after testing:

```text
Program.cs     e2f9462436a3b7e2463dcdd258e491595652c8df9cd6f32080e09cf341527c44
Worker.csproj  6ab1e2091d485ba24e1297b1ac18b31b0a8190886981aada46dda716493d22d5
Image ID       sha256:02d97e82959e33c2bb7824ede05a5c909f17ee50b560818b7632444c65227b0d
```

Full command logs, package hashes, final test output, per-case JSON, worker output and cleanup records remain in the task workspace under `output/card-0ccc299a-*`. The immutable development input specified no additional required checks. Hosted CI and branch-protection decisions remain with the repository.
