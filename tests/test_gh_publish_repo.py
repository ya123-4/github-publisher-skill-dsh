"""Tests for gh_publish stages 0-1: args, self-check, idempotent repo creation."""
import io
import json
import shutil
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-publish" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_publish  # noqa: E402
from _helpers import FakeOpener, json_response, make_tempdir  # noqa: E402


def gzip_file(path: Path):
    path.write_bytes(b"\x1f\x8b\x08\x00fake-gzip-body")


class RepoTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(
            Path(__file__).resolve().parents[2] / ".tmp-github-publisher-tests",
            ignore_errors=True,
        )

    def test_payload_defaults(self):
        self.assertEqual(
            gh_publish.build_repo_payload("foo-dsh", "desc", False),
            {"name": "foo-dsh", "description": "desc", "private": False, "auto_init": False},
        )

    def test_create_201(self):
        opener = FakeOpener(
            [json_response(201, {"html_url": "https://github.com/ya123-4/foo-dsh"})]
        )
        result = gh_publish.create_repo_if_missing(
            opener, "ghp_x", "ya123-4", "foo-dsh", "desc", False, sleep_s=0
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["html_url"], "https://github.com/ya123-4/foo-dsh")
        self.assertIn("Authorization", opener.requests[0].headers)

    def test_create_422_already_exists(self):
        opener = FakeOpener(
            [json_response(422, {"errors": [{"message": "name already exists on this account"}]})]
        )
        result = gh_publish.create_repo_if_missing(
            opener, "ghp_x", "ya123-4", "foo-dsh", "desc", False, sleep_s=0
        )
        self.assertEqual(result["status"], "exists")
        self.assertIn("https://github.com/ya123-4/foo-dsh", result["html_url"])

    def test_create_403_permission(self):
        opener = FakeOpener([json_response(403, {"message": "Resource not accessible"})])
        result = gh_publish.create_repo_if_missing(
            opener, "ghp_x", "ya123-4", "foo-dsh", "desc", False, sleep_s=0
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("权限", result["message"])

    def test_create_retry_then_success(self):
        opener = FakeOpener(
            [
                urllib.error.URLError("boom1"),
                urllib.error.URLError("boom2"),
                json_response(201, {"html_url": "https://github.com/ya123-4/foo-dsh"}),
            ]
        )
        result = gh_publish.create_repo_if_missing(
            opener, "ghp_x", "ya123-4", "foo-dsh", "desc", False, retries=2, sleep_s=0
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(opener.requests), 3)

    def test_default_repo_name(self):
        self.assertEqual(
            gh_publish._default_repo_name("github-publisher-skill-dsh", "-dsh"),
            "github-publisher-skill-dsh",
        )
        self.assertEqual(gh_publish._default_repo_name("foo", "-dsh"), "foo-dsh")

    def test_main_missing_config_exit_2(self):
        td = make_tempdir()
        pkg_dir = Path(td) / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "package.json").write_text(
            json.dumps({"name": "foo", "version": "0.1.0", "description": "d"}),
            encoding="utf-8",
        )
        tgz = Path(td) / "foo-0.1.0.tgz"
        gzip_file(tgz)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_publish.main(
                [
                    "--dir", str(pkg_dir),
                    "--tgz", str(tgz),
                    "--config", str(Path(td) / "no-such-config.json"),
                ]
            )
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stage"], "check")


if __name__ == "__main__":
    unittest.main()
