# Seven-card B: current vote trace ownership

B: https://github.com/boardflow-lab-lenshood/delivery/issues/52
(card `5c9d713506a0481c9987c941f5725862`).
A producer: https://github.com/boardflow-lab-lenshood/delivery/issues/51
(card `054b8ac1afd8488d8acc87777ee51679`).
C consumer: https://github.com/boardflow-lab-lenshood/delivery/issues/53
(card `c25bff7ada4f467395a7981132dee8f4`).

Fixed worker baseline: `c955288f250cfc4edf74675e106859aff56c6c60` on
`codex/arena-seven-20261103-latest`. Only worker changes are included.

The existing Redis `votes` list accepts JSON objects containing `voter_id`,
`vote`, and optionally `trace_id`. A present trace must be a string matching
`[A-Za-z0-9][A-Za-z0-9._:-]{0,63}` in full, using ASCII characters only.
Missing means legacy; explicit null is rejected. No normalization or truncation
is performed. Existing voter and vote validation remains in force.

Startup retains the existing table and rows, adding nullable
`votes.trace_id VARCHAR(64)` with `ADD COLUMN IF NOT EXISTS`. Existing rows
receive NULL. Inserts and updates store the current message's trace; an update
from a legacy message clears the previous trace to NULL, including when the
choice itself is unchanged. The unique `id` and `vote` columns retain their
original semantics. Only the unique-key SQL error enters the existing update
path; other database/infrastructure errors reach the global handler with a
stack trace. Bad message logs contain only a rejection event and reason.

## Reproduce B's isolated storage validation

Build the current checkout, then run:

```sh
docker buildx build --load --progress=plain -t worker-seven-b:test .
python3 tests/trace_integration.py --image worker-seven-b:test --evidence-dir /tmp/worker-seven-b-evidence
```

When buildx is unavailable, the legacy builder also requires declaring
`ARG BUILDPLATFORM` before the first `FROM`. Generate a temporary recipe (the
service Dockerfile and compiled source remain the same):

```sh
python3 -c 'from pathlib import Path; Path("/tmp/worker-seven-b.Dockerfile").write_text("ARG BUILDPLATFORM\n" + Path("Dockerfile").read_text())'
DOCKER_BUILDKIT=0 docker build -f /tmp/worker-seven-b.Dockerfile --build-arg BUILDPLATFORM=linux/arm64 --build-arg TARGETPLATFORM=linux/arm64 --build-arg TARGETARCH=arm64 -t worker-seven-b:test .
```

The trace runner inherits every existing input validation test and adds old
schema/data migration, repeated startups, ASCII boundaries, invalid traces,
exact persistence, trace replacement, legacy clearing, invalid-update
preservation and continued processing. Its final fault checks use only the
owned PostgreSQL check constraint and an owned Redis queue key with the wrong
type. Both errors must exit with status 1 and must not count as rejected votes.
No shared service or environment is modified. The runner creates a unique
internal Docker network without published ports, generates an ephemeral
password via environment variables, bounds commands and readiness waits, and
removes its own containers, volumes and network in cleanup.

Evidence includes real unittest output, migration rows, queue length and stored
rows at key checkpoints, invalid case names, complete worker logs, and cleanup
receipts. See the actual PR/Issue handoff for the tested commit and execution
output. B's storage validation does not claim C's HTTP joint validation: C must
read the real A/B PRs, check out their tested exact commits, and independently
complete the isolated HTTP chain before reporting C complete. Any later source
change or baseline synchronization requires refreshed testing and references.
