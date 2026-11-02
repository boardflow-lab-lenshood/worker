"""Real Redis -> worker -> PostgreSQL tests using disposable Docker resources."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import traceback
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
CANARY = "private-payload-canary-do-not-log"


def docker(*args: str, input_text: str | None = None,
           env: dict[str, str] | None = None, timeout: int = 30) -> str:
    result = subprocess.run(
        ["docker", *args], input=input_text, text=True, capture_output=True,
        env=env, timeout=timeout, check=True,
    )
    return result.stdout.strip()


def wait_for(predicate, description: str, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {description}")


def invalid_messages() -> list[tuple[str, str, str]]:
    cases = [
        ("broken-object", '{"' + CANARY + '":', "InvalidJson"),
        ("empty-input", "", "InvalidJson"),
        ("whitespace-input", " \t\n", "InvalidJson"),
        ("trailing-value", '{} {}', "InvalidJson"),
        ("trailing-comma", '{"voter_id":"x","vote":"a",}', "InvalidJson"),
        ("comment", '{/*comment*/"voter_id":"x","vote":"a"}', "InvalidJson"),
        ("unpaired-high-surrogate", '{"voter_id":"\\ud800","vote":"a"}', "InvalidJson"),
        ("unpaired-low-surrogate", '{"voter_id":"x","vote":"\\udc00"}', "InvalidJson"),
        ("unpaired-property-surrogate", '{"voter_id":"ok","vote":"a","voter_i\\ud800":"x"}',
         "InvalidJson"),
    ]
    for name, value in [("null", None), ("array", [CANARY]), ("string", CANARY),
                        ("number", 42), ("boolean", True)]:
        cases.append((f"non-object-{name}", json.dumps(value), "NonObject"))
    for name, value, reason in [
        ("missing-both", {}, "MissingVoterId"),
        ("missing-id", {"vote": "a"}, "MissingVoterId"),
        ("missing-vote", {"voter_id": "missing-vote"}, "MissingVote"),
    ]:
        cases.append((name, json.dumps({**value, "private": CANARY}), reason))
    wrong_types = [("null", None), ("number", 42), ("decimal", 1.5),
                   ("boolean", False), ("array", []), ("object", {})]
    for field, reason in [("voter_id", "InvalidVoterIdType"), ("vote", "InvalidVoteType")]:
        for name, value in wrong_types:
            message = {"voter_id": f"bad-{field}-{name}", "vote": "a", "private": CANARY}
            message[field] = value
            cases.append((f"{field}-type-{name}", json.dumps(message), reason))
    for name, value in [("empty", ""), ("spaces", "   "), ("tabs", "\t\r\n"),
                        ("unicode-whitespace", " 　"),
                        ("256-ascii", "x" * 256), ("256-unicode", "😀" * 256),
                        ("nul", "bad" + chr(0) + "id")]:
        cases.append((f"id-{name}", json.dumps({"voter_id": value, "vote": "a", "private": CANARY}),
                      "InvalidVoterId"))
    for name, value in [("empty", ""), ("space", " "), ("uppercase-a", "A"),
                        ("uppercase-b", "B"), ("other", "c"), ("multiple", "ab"),
                        ("leading-space", " a"), ("trailing-space", "a ")]:
        cases.append((f"vote-{name}", json.dumps({"voter_id": f"bad-vote-{name}", "vote": value,
                                                "private": CANARY}), "InvalidVote"))
    return cases


class WorkerIntegrationTests(unittest.TestCase):
    image: str
    evidence_dir: Path
    owner_card: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.prefix = f"worker-input-test-{uuid.uuid4().hex[:12]}"
        cls.network = cls.prefix + "-network"
        cls.pg = cls.prefix + "-db"
        cls.redis = cls.prefix + "-redis"
        cls.worker = cls.prefix + "-worker"
        cls.containers: list[str] = []
        cls.addClassCleanup(cls.cleanup)
        cls.labels = ["--label", f"boardflow.card_id={cls.owner_card}"]
        docker("network", "create", "--internal", *cls.labels, cls.network)
        cls.evidence_dir.joinpath("fixture.json").write_text(json.dumps({
            "owner_card": cls.owner_card, "network": cls.network, "internal": True,
            "postgres": cls.pg, "redis": cls.redis, "worker": cls.worker,
            "worker_image": cls.image, "worker_arguments": [], "published_ports": [],
        }, indent=2) + "\n")
        password = secrets.token_urlsafe(24)
        fixture_env = {**os.environ, "POSTGRES_PASSWORD": password,
                       "DATABASE_CONNECTION_STRING":
                       f"Host=db;Username=postgres;Password={password};Database=votes"}
        for name, alias, image, options in [
            (cls.pg, "db", "postgres:15-alpine", ["-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB=votes"]),
            (cls.redis, "redis", "redis:7-alpine", []),
        ]:
            cls.containers.append(name)
            docker("run", "-d", "--name", name, *cls.labels, "--network", cls.network,
                   "--network-alias", alias, *options, image, env=fixture_env, timeout=120)
        wait_for(lambda: subprocess.run(
            ["docker", "exec", cls.pg, "pg_isready", "-U", "postgres", "-d", "votes"],
            capture_output=True, timeout=30).returncode == 0, "PostgreSQL readiness")
        wait_for(lambda: subprocess.run(
            ["docker", "exec", cls.redis, "redis-cli", "ping"], text=True,
            capture_output=True, timeout=30).stdout.strip() == "PONG", "Redis readiness")
        cls.containers.append(cls.worker)
        docker("run", "--pull=never", "-d", "--name", cls.worker, *cls.labels, "--network", cls.network,
               "-e", "DATABASE_CONNECTION_STRING", cls.image, env=fixture_env)
        cls.enqueue(json.dumps({"voter_id": "fixture-ready", "vote": "a"}))
        wait_for(lambda: "Found redis" in cls.logs(), "worker Redis connection")
        wait_for(lambda: cls.rows() == [{"id": "fixture-ready", "vote": "a"}],
                 "initial real end-to-end vote")
        inspections = json.loads(docker("inspect", *cls.containers))
        cls.evidence_dir.joinpath("container-config.json").write_text(json.dumps([
            {"name": item["Name"], "image_id": item["Image"],
             "entrypoint": item["Config"]["Entrypoint"], "cmd": item["Config"]["Cmd"],
             "labels": item["Config"]["Labels"],
             "network_mode": item["HostConfig"]["NetworkMode"],
             "port_bindings": item["HostConfig"]["PortBindings"]}
            for item in inspections
        ], indent=2) + "\n")
        cls.evidence_dir.joinpath("network-config.json").write_text(
            docker("network", "inspect", cls.network) + "\n")

    @classmethod
    def cleanup(cls) -> None:
        failures = []
        removed = []
        try:
            cls.evidence_dir.mkdir(parents=True, exist_ok=True)
            if cls.worker in cls.containers:
                cls.evidence_dir.joinpath("worker.log").write_text(cls.logs() + "\n")
        except (OSError, subprocess.SubprocessError):
            failures.append(traceback.format_exc())
        commands = [["rm", "-f", "-v", name] for name in reversed(cls.containers)]
        commands.append(["network", "rm", cls.network])
        for command in commands:
            try:
                docker(*command)
                removed.append(command[-1])
            except (OSError, subprocess.SubprocessError):
                failures.append(traceback.format_exc())
        cls.evidence_dir.joinpath("cleanup.txt").write_text(
            "Removed resources:\n" + "\n".join(removed) + "\nErrors:\n" + "\n".join(failures))
        if failures:
            raise AssertionError("Fixture cleanup failed: " + "\n".join(failures))

    @classmethod
    def sql(cls, query: str) -> str:
        return docker("exec", cls.pg, "psql", "-U", "postgres", "-d", "votes", "-At",
                      "-v", "ON_ERROR_STOP=1", "-c", query)

    @classmethod
    def rows(cls) -> list[dict[str, str]]:
        return json.loads(cls.sql("SELECT COALESCE(json_agg(t), '[]'::json) "
                                  "FROM (SELECT id, vote FROM votes ORDER BY id) t"))

    @classmethod
    def enqueue(cls, payload: str) -> None:
        docker("exec", "-i", cls.redis, "redis-cli", "-x", "RPUSH", "votes", input_text=payload)

    @classmethod
    def logs(cls) -> str:
        result = subprocess.run(["docker", "logs", cls.worker], text=True,
                                capture_output=True, timeout=30, check=True)
        return result.stdout + result.stderr

    @classmethod
    def rejections(cls) -> list[dict[str, str]]:
        return [json.loads(line) for line in cls.logs().splitlines() if line.startswith('{"event":"vote_rejected"')]

    def setUp(self) -> None:
        self.sql("TRUNCATE votes")

    def assert_alive(self) -> None:
        self.assertEqual("true", docker("inspect", "--format", "{{.State.Running}}", self.worker))

    def test_rejects_without_writing_or_exiting_when_message_is_invalid(self) -> None:
        passed = []
        for name, payload, reason in invalid_messages():
            with self.subTest(message=name):
                before = len(self.rejections())
                self.enqueue(payload)
                wait_for(lambda: len(self.rejections()) == before + 1, f"rejection of {name}")
                self.assertEqual([], self.rows())
                self.assert_alive()
                self.assertEqual({"event": "vote_rejected", "reason": reason}, self.rejections()[-1])
                self.assertNotIn(CANARY, self.logs())
                if CANARY in payload:
                    self.assertNotIn(payload, self.logs())
                passed.append(name)
        self.evidence_dir.joinpath("invalid-cases.json").write_text(json.dumps(
            {"total": len(invalid_messages()), "passed": len(passed), "cases": passed}, indent=2))

    def test_stores_both_choices_when_valid_votes_follow_invalid_messages(self) -> None:
        self.enqueue('{"private":"' + CANARY + '","vote":"A","voter_id":"bad-before-valid"}')
        self.enqueue(json.dumps({"voter_id": "after-invalid-a", "vote": "a"}))
        self.enqueue(json.dumps({"voter_id": "after-invalid-b", "vote": "b"}))
        expected = [{"id": "after-invalid-a", "vote": "a"}, {"id": "after-invalid-b", "vote": "b"}]
        wait_for(lambda: self.rows() == expected, "both choices after invalid input")
        self.assert_alive()

    def test_stores_exact_ids_when_strings_meet_length_and_whitespace_rules(self) -> None:
        ids = ["x", "x" * 255, "😀" * 255, "2026-11-02T00:00:00Z", " padded-id "]
        for voter_id in ids:
            with self.subTest(length=len(voter_id), prefix=voter_id[:8]):
                self.enqueue(json.dumps({"voter_id": voter_id, "vote": "a"}))
                wait_for(lambda: {"id": voter_id, "vote": "a"} in self.rows(), "boundary voter id")
        self.assertEqual(len(ids), len(self.rows()))

    def test_updates_existing_vote_when_same_voter_changes_from_a_to_b(self) -> None:
        self.enqueue(json.dumps({"voter_id": "change-voter", "vote": "a"}))
        wait_for(lambda: self.rows() == [{"id": "change-voter", "vote": "a"}], "initial a vote")
        initial_rows = self.rows()
        self.enqueue(json.dumps({"voter_id": "change-voter", "vote": "b"}))
        wait_for(lambda: self.rows() == [{"id": "change-voter", "vote": "b"}], "updated b vote")
        self.assert_alive()
        queue_length = docker("exec", self.redis, "redis-cli", "LLEN", "votes")
        self.assertEqual("0", queue_length)
        self.evidence_dir.joinpath("legacy-vote.json").write_text(json.dumps({
            "messages": [{"voter_id": "change-voter", "vote": "a"},
                         {"voter_id": "change-voter", "vote": "b"}],
            "initial_rows": initial_rows, "updated_rows": self.rows(),
            "queue_length": int(queue_length), "worker_running": True,
        }, indent=2) + "\n")

    def test_z_reports_database_error_when_valid_vote_violates_database_constraint(self) -> None:
        self.sql("ALTER TABLE votes ADD CONSTRAINT fixture_failure CHECK (vote <> 'b')")
        before = len(self.rejections())
        self.enqueue(json.dumps({"voter_id": "database-fault", "vote": "b"}))
        wait_for(lambda: docker("inspect", "--format", "{{.State.Running}}", self.worker) == "false",
                 "database error reaching global handler")
        self.assertEqual("1", docker("inspect", "--format", "{{.State.ExitCode}}", self.worker))
        self.assertIn("23514", self.logs())
        self.assertIn("Npgsql.PostgresException", self.logs())
        self.assertEqual(before, len(self.rejections()))
        self.assertEqual([], self.rows())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Worker image built from this checkout")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--owner-card", default="local-worker-input")
    args = parser.parse_args()
    WorkerIntegrationTests.owner_card = args.owner_card
    WorkerIntegrationTests.image = args.image
    WorkerIntegrationTests.evidence_dir = args.evidence_dir.resolve()
    WorkerIntegrationTests.evidence_dir.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(WorkerIntegrationTests)
    with (WorkerIntegrationTests.evidence_dir / "tests.log").open("w") as output:
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
