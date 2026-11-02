"""Run the built worker CLI without network, Redis or PostgreSQL."""

import argparse
import json
from pathlib import Path
import subprocess
import unittest
import uuid


class WorkerVersionTests(unittest.TestCase):
    image: str
    evidence_dir: Path
    owner_card: str

    def assert_offline_version(self, database_configuration: str | None) -> None:
        name = f"worker-version-{uuid.uuid4().hex[:12]}"
        command = [
            "docker", "create", "--pull=never", "--name", name,
            "--label", f"boardflow.card_id={self.owner_card}",
            "--network", "none", "--read-only", "--cap-drop=ALL",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        ]
        if database_configuration is not None:
            command.extend(["-e", f"DATABASE_CONNECTION_STRING={database_configuration}"])
        command.extend([self.image, "--version"])
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        self.addCleanup(self.remove_container, name)

        result = subprocess.run(["docker", "start", "-a", name],
                                capture_output=True, text=True, timeout=15)
        inspection = json.loads(subprocess.run(
            ["docker", "inspect", name], check=True, capture_output=True,
            text=True, timeout=30).stdout)[0]
        evidence = {
            "command": command,
            "start_command": ["docker", "start", "-a", name],
            "image_id": inspection["Image"],
            "network_mode": inspection["HostConfig"]["NetworkMode"],
            "networks": inspection["NetworkSettings"]["Networks"],
            "read_only": inspection["HostConfig"]["ReadonlyRootfs"],
            "tmpfs": inspection["HostConfig"]["Tmpfs"],
            "owner_card": inspection["Config"]["Labels"]["boardflow.card_id"],
            "stdout": result.stdout,
            "stderr": result.stderr,
            "docker_exit_code": result.returncode,
            "process_exit_code": inspection["State"]["ExitCode"],
            "running": inspection["State"]["Running"],
        }
        self.evidence_dir.joinpath(f"{self._testMethodName}.json").write_text(
            json.dumps(evidence, indent=2) + "\n")
        self.assertEqual(0, result.returncode)
        self.assertFalse(evidence["running"])
        self.assertEqual(0, evidence["process_exit_code"])
        self.assertEqual("none", evidence["network_mode"])
        self.assertEqual("", result.stderr)
        self.assertEqual('{"service":"worker","version":"arena-seven-20261103"}\n',
                         result.stdout)
        self.assertEqual({"service": "worker", "version": "arena-seven-20261103"},
                         json.loads(result.stdout))

    def remove_container(self, name: str) -> None:
        subprocess.run(["docker", "rm", "-f", "-v", name], check=True,
                       capture_output=True, text=True, timeout=30)
        with self.evidence_dir.joinpath("cleanup.txt").open("a") as output:
            output.write(f"Removed {name}\n")

    def test_reports_version_when_database_configuration_is_missing(self) -> None:
        self.assert_offline_version(None)

    def test_reports_version_when_database_configuration_is_invalid(self) -> None:
        # Npgsql would reject this immediately if dependency initialization ran first.
        self.assert_offline_version("invalid-configuration-before-any-connection")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--owner-card", default="local-worker-version")
    args = parser.parse_args()
    WorkerVersionTests.image = args.image
    WorkerVersionTests.evidence_dir = args.evidence_dir.resolve()
    WorkerVersionTests.owner_card = args.owner_card
    WorkerVersionTests.evidence_dir.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(WorkerVersionTests)
    with WorkerVersionTests.evidence_dir.joinpath("tests.log").open("w") as output:
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
