"""Tests for gh_publish stages 4-6: release, asset upload, verification."""
import hashlib
import io
import json
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-publish" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_publish  # noqa: E402
from _helpers import FakeOpener, FakeResponse, json_response, make_tempdir  # noqa: E402
from test_gh_publish_git import GitRun  # noqa: E402


def make_tgz(path: Path, size: int = 16):
    # exact `size` bytes, starting with the gzip magic
    path.write_bytes(b"\x1f\x8b" + b"x" * (size - 2))


class ReleaseTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(
            Path(__file__).resolve().parents[2] / ".tmp-github-publisher-tests",
            ignore_errors=True,
        )

    def test_create_release_201(self):
        opener = FakeOpener(
            [json_response(201, {"id": 42, "html_url": "https://github.com/o/r/releases/tag/v0.1.0"})]
        )
        result = gh_publish.create_release(opener, "ghp_x", "o", "r", "v0.1.0", "body")
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["release_id"], 42)

    def test_create_release_retries_transient(self):
        import urllib.error

        opener = FakeOpener(
            [
                urllib.error.URLError("timeout"),
                json_response(201, {"id": 7, "html_url": "https://github.com/o/r/releases/tag/v0.1.0"}),
            ]
        )
        result = gh_publish.create_release(
            opener, "ghp_x", "o", "r", "v0.1.0", "body", retries=1, sleep_s=0
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(opener.requests), 2)

    def test_create_release_422_exists(self):
        opener = FakeOpener(
            [json_response(422, {"errors": [{"message": "already_exists"}]})]
        )
        result = gh_publish.create_release(opener, "ghp_x", "o", "r", "v0.1.0", "body")
        self.assertEqual(result["status"], "exists")
        self.assertIn("bump", result["message"])

    def test_upload_asset_headers_and_url(self):
        td = make_tempdir()
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz)
        opener = FakeOpener(
            [json_response(201, {"size": 20, "browser_download_url": "https://x/dl"})]
        )
        result = gh_publish.upload_asset(opener, "ghp_x", "o", "r", 42, tgz)
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["browser_download_url"], "https://x/dl")
        req = opener.requests[0]
        self.assertIn("uploads.github.com/repos/o/r/releases/42/assets?name=foo-dsh-0.1.0.tgz", req.full_url)
        self.assertEqual(req.get_header("Content-type"), "application/octet-stream")
        self.assertIn("Authorization", req.headers)

    def test_upload_asset_same_size_skipped(self):
        td = make_tempdir()
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz, size=20)
        opener = FakeOpener(
            [
                json_response(422, {"errors": [{"message": "already_exists"}]}),
                json_response(200, [{"name": "foo-dsh-0.1.0.tgz", "size": 20, "browser_download_url": "https://x/dl"}]),
            ]
        )
        result = gh_publish.upload_asset(opener, "ghp_x", "o", "r", 42, tgz)
        self.assertEqual(result["status"], "skipped_same")

    def test_upload_asset_diff_size_error(self):
        td = make_tempdir()
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz, size=20)
        opener = FakeOpener(
            [
                json_response(422, {"errors": [{"message": "already_exists"}]}),
                json_response(200, [{"name": "foo-dsh-0.1.0.tgz", "size": 999, "browser_download_url": "https://x/dl"}]),
            ]
        )
        result = gh_publish.upload_asset(opener, "ghp_x", "o", "r", 42, tgz)
        self.assertEqual(result["status"], "error")
        self.assertIn("人工", result["message"])

    def test_upload_asset_same_sha256_skipped_even_if_size_differs(self):
        td = make_tempdir()
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz, size=20)
        digest = "sha256:" + hashlib.sha256(tgz.read_bytes()).hexdigest()
        opener = FakeOpener(
            [
                json_response(422, {"errors": [{"message": "already_exists"}]}),
                json_response(
                    200,
                    [
                        {
                            "name": "foo-dsh-0.1.0.tgz",
                            "size": 999,  # stale size, but digest proves identity
                            "digest": digest,
                            "browser_download_url": "https://x/dl",
                        }
                    ],
                ),
            ]
        )
        result = gh_publish.upload_asset(opener, "ghp_x", "o", "r", 42, tgz)
        self.assertEqual(result["status"], "skipped_same")

    def test_upload_asset_diff_sha256_error_even_if_size_matches(self):
        td = make_tempdir()
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz, size=20)
        opener = FakeOpener(
            [
                json_response(422, {"errors": [{"message": "already_exists"}]}),
                json_response(
                    200,
                    [
                        {
                            "name": "foo-dsh-0.1.0.tgz",
                            "size": 20,  # same size, but content differs
                            "digest": "sha256:" + "0" * 64,
                            "browser_download_url": "https://x/dl",
                        }
                    ],
                ),
            ]
        )
        result = gh_publish.upload_asset(opener, "ghp_x", "o", "r", 42, tgz)
        self.assertEqual(result["status"], "error")
        self.assertIn("人工", result["message"])

    def test_upload_asset_retries_transient(self):
        import urllib.error

        td = make_tempdir()
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz)
        opener = FakeOpener(
            [
                urllib.error.URLError("boom"),
                json_response(201, {"size": 16, "browser_download_url": "https://x/dl"}),
            ]
        )
        result = gh_publish.upload_asset(
            opener, "ghp_x", "o", "r", 42, tgz, retries=1, sleep_s=0
        )
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(len(opener.requests), 2)

    def test_upload_asset_list_failure_reports_real_cause(self):
        td = make_tempdir()
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz)
        opener = FakeOpener(
            [
                json_response(422, {"errors": [{"message": "already_exists"}]}),
                json_response(200, [{"__error": "HTTP 500"}]),
            ]
        )
        result = gh_publish.upload_asset(opener, "ghp_x", "o", "r", 42, tgz)
        self.assertEqual(result["status"], "error")
        self.assertIn("HTTP 500", result["message"])

    def test_verify_release_retries_transient(self):
        import urllib.error

        opener = FakeOpener(
            [
                urllib.error.URLError("boom"),
                json_response(200, {"tag_name": "v0.1.0", "html_url": "https://x", "assets": []}),
            ]
        )
        result = gh_publish.verify_release(
            opener, "ghp_x", "o", "r", "v0.1.0", retries=1, sleep_s=0
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(opener.requests), 2)

    def test_emit_result_masks_token(self):
        out = gh_publish.emit_result(False, "push", "token=ghp_x leaked?", token="ghp_x")
        self.assertNotIn("ghp_x", out)

    def test_verify_release_bad_json_returns_error(self):
        opener = FakeOpener([FakeResponse(200, b"<html>not json</html>")])
        result = gh_publish.verify_release(opener, "ghp_x", "o", "r", "v0.1.0")
        self.assertEqual(result["status"], "error")
        self.assertIn("解析", result["message"])

    def test_main_unexpected_exception_returns_json_exit_2(self):
        td = make_tempdir()
        pkg_dir = Path(td) / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "package.json").write_text(
            json.dumps({"name": "foo-dsh", "version": "0.1.0", "description": "d"}),
            encoding="utf-8",
        )
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz)
        cfg = Path(td) / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "owner": "ya123-4",
                    "token": "ghp_x",
                    "author": {"name": "DSH Maintainers", "email": "x@y.z"},
                    "defaults": {"visibility": "public", "repo_suffix": "-dsh"},
                }
            ),
            encoding="utf-8",
        )
        opener = FakeOpener(
            [
                json_response(200, {"login": "ya123-4"}),  # GET /user
                json_response(422, {"errors": [{"message": "name already exists"}]}),  # repo
            ]
        )

        def exploding_git(argv, **kw):
            raise OSError("git vanished")

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_publish.main(
                ["--dir", str(pkg_dir), "--tgz", str(tgz), "--config", str(cfg)],
                opener=opener,
                tls_probe=lambda: (True, "ok"),
                sleep_s=0,
                ca_bundle="PEM",
                run_git=exploding_git,
            )
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stage"], "fatal")

    def test_main_release_exists_exit_6(self):
        td = make_tempdir()
        pkg_dir = Path(td) / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "package.json").write_text(
            json.dumps({"name": "foo-dsh", "version": "0.1.0", "description": "d"}),
            encoding="utf-8",
        )
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz)
        cfg = Path(td) / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "owner": "ya123-4",
                    "token": "ghp_x",
                    "author": {"name": "DSH Maintainers", "email": "x@y.z"},
                    "defaults": {"visibility": "public", "repo_suffix": "-dsh"},
                }
            ),
            encoding="utf-8",
        )
        opener = FakeOpener(
            [
                json_response(200, {"login": "ya123-4"}),  # GET /user
                json_response(422, {"errors": [{"message": "name already exists"}]}),  # repo
                json_response(422, {"errors": [{"message": "already_exists"}]}),  # release
            ]
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_publish.main(
                ["--dir", str(pkg_dir), "--tgz", str(tgz), "--config", str(cfg)],
                opener=opener,
                tls_probe=lambda: (True, "ok"),
                sleep_s=0,
                ca_bundle="PEM",
                run_git=GitRun(),
            )
        self.assertEqual(code, 6)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stage"], "release")

    def _full_chain_fixture(self, verify_assets):
        td = make_tempdir()
        pkg_dir = Path(td) / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "package.json").write_text(
            json.dumps({"name": "foo-dsh", "version": "0.1.0", "description": "d"}),
            encoding="utf-8",
        )
        tgz = Path(td) / "foo-dsh-0.1.0.tgz"
        make_tgz(tgz)  # exactly 16 bytes
        cfg = Path(td) / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "owner": "ya123-4",
                    "token": "ghp_x",
                    "author": {"name": "DSH Maintainers", "email": "x@y.z"},
                    "defaults": {"visibility": "public", "repo_suffix": "-dsh"},
                }
            ),
            encoding="utf-8",
        )
        opener = FakeOpener(
            [
                json_response(200, {"login": "ya123-4"}),  # GET /user
                json_response(422, {"errors": [{"message": "name already exists"}]}),  # repo
                json_response(201, {"id": 42, "html_url": "https://github.com/o/r/releases/tag/v0.1.0"}),
                json_response(201, {"size": 16, "browser_download_url": "https://x/dl"}),
                json_response(
                    200,
                    {
                        "tag_name": "v0.1.0",
                        "html_url": "https://github.com/o/r/releases/tag/v0.1.0",
                        "assets": verify_assets,
                    },
                ),
            ]
        )
        return td, pkg_dir, tgz, cfg, opener

    def test_main_full_success_exit_0_with_config_path(self):
        td, pkg_dir, tgz, cfg, opener = self._full_chain_fixture(
            [{"name": "foo-dsh-0.1.0.tgz", "size": 16, "browser_download_url": "https://x/dl"}]
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_publish.main(
                ["--dir", str(pkg_dir), "--tgz", str(tgz), "--config", str(cfg)],
                opener=opener,
                tls_probe=lambda: (True, "ok"),
                sleep_s=0,
                ca_bundle="PEM",
                run_git=GitRun(),
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stage"], "done")
        self.assertEqual(payload["config_path"], str(cfg))

    def test_main_verify_mismatch_exit_7(self):
        td, pkg_dir, tgz, cfg, opener = self._full_chain_fixture(
            [{"name": "foo-dsh-0.1.0.tgz", "size": 999, "browser_download_url": "https://x/dl"}]
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_publish.main(
                ["--dir", str(pkg_dir), "--tgz", str(tgz), "--config", str(cfg)],
                opener=opener,
                tls_probe=lambda: (True, "ok"),
                sleep_s=0,
                ca_bundle="PEM",
                run_git=GitRun(),
            )
        self.assertEqual(code, 7)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stage"], "verify")

    def test_main_retries_push_once_after_transient_failure(self):
        td, pkg_dir, tgz, cfg, opener = self._full_chain_fixture(
            [{"name": "foo-dsh-0.1.0.tgz", "size": 16, "browser_download_url": "https://x/dl"}]
        )
        run = GitRun()
        run.when("push", returncode=128, stderr="fatal: remote not ready")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_publish.main(
                ["--dir", str(pkg_dir), "--tgz", str(tgz), "--config", str(cfg)],
                opener=opener,
                tls_probe=lambda: (True, "ok"),
                sleep_s=0,
                ca_bundle="PEM",
                run_git=run,
            )
        self.assertEqual(code, 0)
        push_calls = [c for c in run.calls if any("push" in a for a in c)]
        self.assertEqual(len(push_calls), 2)


if __name__ == "__main__":
    unittest.main()
