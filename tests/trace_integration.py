"""Trace storage checks plus the existing real worker input regression suite."""

import argparse
import json
from pathlib import Path
import unittest

from integration import CANARY, WorkerIntegrationTests, docker, wait_for


def invalid_traces() -> list[tuple[str, object, str]]:
    cases = [(name, value, "InvalidTraceIdType") for name, value in [
        ("null", None), ("integer", 42), ("decimal", 1.5), ("boolean", True),
        ("array", []), ("object", {}),
    ]]
    cases.extend((name, value, "InvalidTraceId") for name, value in [
        ("empty", ""), ("65-characters", "a" * 65), ("unicode", "追踪"),
        ("unicode-digit", "١"), ("unicode-letter", "é"), ("nul", "a\0b"),
        ("leading-dot", ".abc"), ("leading-underscore", "_abc"),
        ("leading-colon", ":abc"), ("leading-hyphen", "-abc"),
        ("space", "a b"), ("leading-space", " a"), ("trailing-space", "a "),
        ("tab", "a\tb"), ("newline", "a\nb"), ("trailing-newline", "abc\n"),
        ("carriage-return", "abc\r"), ("slash", "a/b"), ("plus", "a+b"),
        ("backslash", "a\\b"), ("emoji", "a😀"),
    ])
    return cases


class TraceIntegrationTests(WorkerIntegrationTests):
    @classmethod
    def trace_rows(cls) -> list[dict]:
        return json.loads(cls.sql("SELECT COALESCE(json_agg(t), '[]'::json) "
                                  "FROM (SELECT id, vote, trace_id FROM votes ORDER BY id) t"))

    def save_snapshot(self, name: str) -> None:
        self.evidence_dir.joinpath(name + ".json").write_text(json.dumps({
            "rows": self.trace_rows(),
            "queue_length": int(docker("exec", self.redis, "redis-cli", "LLEN", "votes")),
        }, indent=2))

    def test_migrates_existing_data_when_worker_starts(self) -> None:
        evidence = json.loads(self.evidence_dir.joinpath("migration.json").read_text())
        self.assertEqual({"id": "pre-migration", "vote": "b", "trace_id": None}, evidence[1])
        self.assertEqual("character varying|64|YES", self.sql(
            "SELECT data_type, character_maximum_length, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'votes' AND column_name = 'trace_id'"))

    def test_preserves_data_when_worker_restarts_twice(self) -> None:
        self.enqueue(json.dumps({"voter_id": "restart-voter", "vote": "b", "trace_id": "B.restart:1"}))
        expected = [{"id": "restart-voter", "vote": "b", "trace_id": "B.restart:1"}]
        wait_for(lambda: self.trace_rows() == expected, "vote before repeated startup")
        for index in range(2):
            docker("restart", self.worker)
            marker = f"restart-marker-{index}"
            self.enqueue(json.dumps({"voter_id": marker, "vote": "a"}))
            wait_for(lambda: any(row["id"] == marker for row in self.trace_rows()),
                     "consumption after repeated migration")
            self.sql(f"DELETE FROM votes WHERE id = '{marker}'")
            self.assertEqual(expected, self.trace_rows())
        self.save_snapshot("repeated-startup")

    def test_stores_exact_trace_when_ascii_contract_is_valid(self) -> None:
        traces = ["A", "0", "a" * 64, "Zz09._:-", "A." + "z" * 62]
        for index, trace in enumerate(traces):
            with self.subTest(trace=trace):
                expected = {"id": f"valid-trace-{index}", "vote": "a", "trace_id": trace}
                self.enqueue(json.dumps({"voter_id": expected["id"], "vote": "a", "trace_id": trace}))
                wait_for(lambda: expected in self.trace_rows(), "exact trace persistence")
        self.assertEqual(len(traces), len(self.trace_rows()))
        self.save_snapshot("valid-traces")

    def test_rejects_trace_without_writing_when_present_value_is_invalid(self) -> None:
        passed = []
        for name, value, reason in invalid_traces():
            with self.subTest(trace=name):
                before = len(self.rejections())
                self.enqueue(json.dumps({"voter_id": "bad-trace-" + name, "vote": "a",
                                         "trace_id": value, "private": CANARY}))
                wait_for(lambda: len(self.rejections()) == before + 1, "invalid trace rejection")
                self.assertEqual([], self.trace_rows())
                self.assertEqual({"event": "vote_rejected", "reason": reason}, self.rejections()[-1])
                self.assertNotIn(CANARY, self.logs())
                self.assert_alive()
                passed.append(name)
        self.evidence_dir.joinpath("invalid-traces.json").write_text(json.dumps({
            "total": len(invalid_traces()), "passed": len(passed), "cases": passed,
        }, indent=2))

    def test_rejects_trace_when_escaped_unicode_is_invalid(self) -> None:
        before = len(self.rejections())
        self.enqueue('{"voter_id":"bad-unicode-trace","vote":"a","trace_id":"\\ud800"}')
        wait_for(lambda: len(self.rejections()) == before + 1, "malformed trace rejection")
        self.assertEqual({"event": "vote_rejected", "reason": "InvalidJson"}, self.rejections()[-1])
        self.assertEqual([], self.trace_rows())
        self.assert_alive()

    def test_replaces_current_trace_when_same_voter_changes_vote(self) -> None:
        for vote, trace in [("a", "Trace.old"), ("b", "Trace.new"), ("b", "Trace.same-vote")]:
            self.enqueue(json.dumps({"voter_id": "trace-change", "vote": vote, "trace_id": trace}))
            wait_for(lambda: self.trace_rows() == [
                {"id": "trace-change", "vote": vote, "trace_id": trace}], "current trace replacement")
        self.save_snapshot("trace-replacement")

    def test_clears_trace_when_legacy_message_changes_vote(self) -> None:
        self.enqueue(json.dumps({"voter_id": "legacy-change", "vote": "a", "trace_id": "Trace.old"}))
        wait_for(lambda: self.trace_rows() == [
            {"id": "legacy-change", "vote": "a", "trace_id": "Trace.old"}], "tracked vote")
        self.enqueue(json.dumps({"voter_id": "legacy-change", "vote": "b"}))
        wait_for(lambda: self.trace_rows() == [
            {"id": "legacy-change", "vote": "b", "trace_id": None}], "legacy trace clearing")
        self.save_snapshot("legacy-clearing")

    def test_keeps_existing_vote_when_trace_update_is_invalid(self) -> None:
        expected = [{"id": "unchanged", "vote": "a", "trace_id": "Trace.original"}]
        self.enqueue(json.dumps({"voter_id": "unchanged", "vote": "a", "trace_id": "Trace.original"}))
        wait_for(lambda: self.trace_rows() == expected, "original tracked vote")
        before = len(self.rejections())
        self.enqueue(json.dumps({"voter_id": "unchanged", "vote": "b", "trace_id": None}))
        wait_for(lambda: len(self.rejections()) == before + 1, "invalid update rejection")
        self.assertEqual(expected, self.trace_rows())
        self.save_snapshot("invalid-update-preserves-row")

    def test_stores_trace_when_valid_message_follows_invalid_trace(self) -> None:
        self.enqueue(json.dumps({"voter_id": "bad", "vote": "a", "trace_id": "bad\n"}))
        self.enqueue(json.dumps({"voter_id": "after-bad-trace", "vote": "b", "trace_id": "Trace.after"}))
        wait_for(lambda: self.trace_rows() == [
            {"id": "after-bad-trace", "vote": "b", "trace_id": "Trace.after"}], "continued consumption")
        self.assert_alive()
        self.save_snapshot("continuation")

    def test_stores_null_trace_when_legacy_message_inserts_vote(self) -> None:
        self.enqueue(json.dumps({"voter_id": "legacy-insert", "vote": "a"}))
        wait_for(lambda: self.trace_rows() == [
            {"id": "legacy-insert", "vote": "a", "trace_id": None}], "legacy insertion")
        self.save_snapshot("legacy-insert")

    def test_zz_reports_infrastructure_error_when_redis_queue_has_wrong_type(self) -> None:
        # The inherited database-failure check intentionally exits the worker first.
        self.sql("ALTER TABLE votes DROP CONSTRAINT fixture_failure")
        docker("start", self.worker)
        self.enqueue(json.dumps({"voter_id": "redis-ready", "vote": "a"}))
        wait_for(lambda: len(self.trace_rows()) == 1, "worker recovery after database error")
        self.sql("TRUNCATE votes")
        before = len(self.rejections())
        docker("exec", self.redis, "redis-cli", "SET", "votes", "fixture-wrong-type")
        wait_for(lambda: docker("inspect", "--format", "{{.State.Running}}", self.worker) == "false",
                 "Redis failure reaching global handler")
        self.assertEqual("1", docker("inspect", "--format", "{{.State.ExitCode}}", self.worker))
        self.assertIn("WRONGTYPE", self.logs())
        self.assertIn("RedisServerException", self.logs())
        self.assertEqual(before, len(self.rejections()))
        self.assertEqual([], self.trace_rows())
        self.evidence_dir.joinpath("infrastructure-failure.json").write_text(json.dumps({
            "fault": "owned Redis votes key changed from list to string", "worker_exit_code": 1,
            "rejection_count_before": before, "rejection_count_after": len(self.rejections()),
            "rows": self.trace_rows(),
        }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    TraceIntegrationTests.image = args.image
    TraceIntegrationTests.evidence_dir = args.evidence_dir.resolve()
    TraceIntegrationTests.evidence_dir.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TraceIntegrationTests)
    with (TraceIntegrationTests.evidence_dir / "tests.log").open("w") as output:
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
