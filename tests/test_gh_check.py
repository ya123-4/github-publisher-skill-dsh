"""Tests for github-publish/scripts/gh_check.py"""
import json
import shutil
import ssl
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-publish" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_check  # noqa: E402
from _helpers import FakeOpener, json_response, make_tempdir  # noqa: E402


class CheckTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(
            Path(__file__).resolve().parents[2] / ".tmp-github-publisher-tests",
            ignore_errors=True,
        )

    def test_validate_token_ok(self):
        opener = FakeOpener([json_response(200, {"login": "ya123-4"})])
        ok, msg = gh_check.validate_token("ghp_x", "ya123-4", opener=opener)
        self.assertTrue(ok)
        self.assertIn("ya123-4", msg)
        self.assertIn("Authorization", opener.requests[0].headers)

    def test_validate_token_bad_credentials(self):
        opener = FakeOpener([json_response(401, {"message": "Bad credentials"})])
        ok, msg = gh_check.validate_token("ghp_x", "ya123-4", opener=opener)
        self.assertFalse(ok)
        self.assertIn("401", msg)

    def test_check_environment_with_fake_opener(self):
        td = make_tempdir()
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
        opener = FakeOpener([json_response(200, {"login": "ya123-4"})])
        result = gh_check.check_environment(
            cfg, opener=opener, tls_probe=lambda: (True, "ok")
        )
        self.assertTrue(result["token_ok"])
        self.assertTrue(result["tls_ok"])
        self.assertTrue(result["python_ok"])
        self.assertEqual(result["owner"], "ya123-4")
        self.assertEqual(result["actual_config_path"], str(cfg))

    def test_der_to_pem(self):
        der = b"\x30\x82\x01\x22 fake der certificate bytes"
        pem = gh_check.der_to_pem(der)
        self.assertEqual(ssl.PEM_cert_to_DER_cert(pem), der)

    def test_fetch_peer_ca_bundle_from_store_and_handshake(self):
        enum = [(b"rootder1",), (b"rootder2",)]
        bundle = gh_check.fetch_peer_ca_bundle(
            enum_certs=lambda: enum, handshake=lambda: b"leafder"
        )
        self.assertEqual(bundle.count("BEGIN CERTIFICATE"), 3)

    def test_fetch_peer_ca_bundle_survives_handshake_failure(self):
        enum = [(b"rootder1",)]
        bundle = gh_check.fetch_peer_ca_bundle(
            enum_certs=lambda: enum,
            handshake=lambda: (_ for _ in ()).throw(OSError("refused")),
        )
        self.assertEqual(bundle.count("BEGIN CERTIFICATE"), 1)

    def test_cli_missing_config_exit_2(self):
        td = make_tempdir()
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_check.main(
                ["--config", str(Path(td) / "missing.json")]
            )
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])

    def test_cli_ok_with_fakes(self):
        td = make_tempdir()
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
        import io
        from contextlib import redirect_stdout

        opener = FakeOpener([json_response(200, {"login": "ya123-4"})])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_check.main(
                ["--config", str(cfg)],
                opener=opener,
                tls_probe=lambda: (True, "ok"),
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["token_ok"])
        self.assertNotIn("ghp_x", buf.getvalue())

    def test_probe_tls_handshake_only(self):
        class FakeConn:
            def __init__(self):
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.closed = True
                return False

        conn = FakeConn()
        wrapped = []

        def fake_wrap(sock):
            wrapped.append(sock)
            return sock

        ok, msg = gh_check.probe_tls(
            connect=lambda: conn, wrap=fake_wrap
        )
        self.assertTrue(ok, msg)
        self.assertTrue(wrapped)
        self.assertTrue(conn.closed)

    def test_probe_tls_handshake_failure(self):
        def boom(sock):
            raise ssl.SSLError("handshake failed")

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        ok, msg = gh_check.probe_tls(connect=lambda: FakeConn(), wrap=boom)
        self.assertFalse(ok)
        self.assertIn("handshake failed", msg)


if __name__ == "__main__":
    unittest.main()
