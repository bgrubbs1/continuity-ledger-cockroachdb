from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


from continuity_ledger.release import build_public_release  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PublicReleaseTests(unittest.TestCase):
    def build_in(
        self, parent: Path, name: str = "candidate"
    ) -> tuple[Path, dict[str, object]]:
        output = parent / name
        return output, build_public_release(ROOT, output)

    def test_candidate_contains_runtime_evidence_tests_and_ci(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self.build_in(Path(temporary))
            for relative in (
                ".github/workflows/public-release.yml",
                ".dockerignore",
                ".env.example",
                "LICENSE",
                "PRIVACY_BOUNDARY.md",
                "README.md",
                "pyproject.toml",
                "deployment/Dockerfile",
                "deployment/template.yaml",
                "artifacts/public/local-cockroach-contract.json",
                "docs/LOCAL_VERIFICATION_2026-08-09.md",
                "scripts/build_public_release.py",
                "scripts/smoke_lambda_container.py",
                "scripts/verify_local_cockroach.py",
                "src/continuity_ledger/release.py",
                "tests/test_release.py",
            ):
                self.assertTrue((output / relative).is_file(), relative)

    def test_candidate_excludes_owner_private_and_generated_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self.build_in(Path(temporary))
            files = {
                path.relative_to(output).as_posix()
                for path in output.rglob("*")
                if path.is_file()
            }
            for forbidden in (
                ".env",
                "DEVPOST_SUBMISSION_DRAFT.md",
                "FINAL_OWNER_HANDOFF.txt",
                "RUBRIC_AUDIT_DRAFT.md",
                "VIDEO_STORYBOARD.md",
                "1 - Official Devpost contest.url",
                "2 - CockroachDB Cloud signup.url",
                "3 - AWS Free Tier.url",
            ):
                self.assertNotIn(forbidden, files)
            self.assertFalse(any(path.startswith(".venv/") for path in files))
            self.assertFalse(any(path.startswith("build/") for path in files))
            self.assertFalse(any(path.startswith("artifacts/private/") for path in files))
            self.assertFalse(any("__pycache__" in path for path in files))
            self.assertFalse(any(".egg-info/" in path for path in files))

    def test_public_ci_verifies_clean_candidate_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self.build_in(Path(temporary))
            workflow = (output / ".github/workflows/public-release.yml").read_text(
                encoding="utf-8"
            )
            for required in (
                "python -m unittest discover -s tests -v",
                "python scripts/build_public_release.py",
                "RELEASE_MANIFEST.json",
                "docker build",
                "cloud_evidence_claimed",
                "functions/function/invocations",
                "python scripts/smoke_lambda_container.py",
                "ALLOW_LOCAL_SQLITE=true",
            ):
                self.assertIn(required, workflow)
            for forbidden in (
                "secrets.",
                "DATABASE_URL=",
                "COCKROACH_MCP_TOKEN=",
                "aws configure",
                "sam deploy",
            ):
                self.assertNotIn(forbidden, workflow)

    def test_candidate_contains_no_workspace_contact_or_private_network_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self.build_in(Path(temporary))
            text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.rglob("*")
                if path.is_file()
                and path.name != "RELEASE_MANIFEST.json"
                and path.suffix.casefold()
                in {".example", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
            )
            self.assertNotIn(str(ROOT).casefold(), text.casefold())
            self.assertIsNone(
                re.search(r"\b(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}\b", text)
            )
            self.assertIsNone(re.search(r"[a-z]:\\users\\[^\\\s]+", text, re.I))
            self.assertIsNone(
                re.search(
                    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
                    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
                    r"192\.168\.\d{1,3}\.\d{1,3})\b",
                    text,
                )
            )

    def test_manifest_hashes_exact_candidate_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, manifest = self.build_in(Path(temporary))
            records = manifest["files"]
            self.assertGreater(len(records), 15)
            for record in records:
                path = output / record["path"]
                self.assertEqual(path.stat().st_size, record["bytes"])
                self.assertEqual(sha256(path), record["sha256"])
            actual = {
                path.relative_to(output).as_posix()
                for path in output.rglob("*")
                if path.is_file() and path.name != "RELEASE_MANIFEST.json"
            }
            self.assertEqual(actual, {record["path"] for record in records})

    def test_two_builds_are_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            first, _ = self.build_in(parent, "first")
            second, _ = self.build_in(parent, "second")
            self.assertEqual(
                (first / "RELEASE_MANIFEST.json").read_bytes(),
                (second / "RELEASE_MANIFEST.json").read_bytes(),
            )

    def test_existing_destination_is_never_deleted_or_merged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate"
            output.mkdir()
            sentinel = output / "owner.txt"
            sentinel.write_text("preserve\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                build_public_release(ROOT, output)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")


if __name__ == "__main__":
    unittest.main()
