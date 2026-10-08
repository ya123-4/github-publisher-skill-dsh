"""Tests for github-publish/scripts/gh_config.py"""
import shutil
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-publish" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_config  # noqa: E402
from _helpers import make_tempdir  # noqa: E402

# Temp dirs live outside the repo (see _helpers.py for the sandbox story).
WORKSPACE_TMP = Path(__file__).resolve().parents[2] / ".tmp-github-publisher-tests"


class ConfigTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(WORKSPACE_TMP, ignore_errors=True)

    def test_config_template_defaults(self):
        t = gh_config.config_template("ya123-4")
        self.assertEqual(t["owner"], "ya123-4")
        self.assertEqual(t["author"]["name"], "DSH Maintainers")
        self.assertEqual(t["author"]["email"], "dsh-maintainers@users.noreply.github.com")
        self.assertEqual(t["defaults"]["visibility"], "public")
        self.assertEqual(t["defaults"]["repo_suffix"], "-dsh")
        self.assertIn("token", t)

    def test_roundtrip(self):
        td = make_tempdir()
        p = Path(td) / "config.json"
        cfg = gh_config.config_template("ya123-4")
        cfg["token"] = "ghp_test123"
        gh_config.save_config(p, cfg)
        loaded = gh_config.load_config(p)
        self.assertEqual(loaded["token"], "ghp_test123")
        self.assertEqual(loaded["author"]["name"], "DSH Maintainers")

    def test_corrupt_json_raises_without_token(self):
        td = make_tempdir()
        p = Path(td) / "config.json"
        p.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(gh_config.ConfigError) as cm:
            gh_config.load_config(p)
        msg = str(cm.exception)
        self.assertIn("重新配置", msg)
        self.assertNotIn("ghp_", msg)

    def test_mask_token(self):
        out = gh_config.mask_token("push failed token=ghp_abc123", "ghp_abc123")
        self.assertNotIn("ghp_abc123", out)
        self.assertIn("***", out)

    def test_resolve_prefers_existing_home(self):
        td = make_tempdir()
        home = Path(td) / "home"
        ws = Path(td) / "ws"
        cfg = home / ".dsh" / "github-publisher" / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("{}", encoding="utf-8")
        got = gh_config.resolve_config_path(workspace=str(ws), home=str(home))
        self.assertEqual(got, cfg)

    def test_resolve_falls_back_to_ws_rt(self):
        td = make_tempdir()
        home = Path(td) / "home"  # no config under home
        ws = Path(td) / "ws"
        cfg = ws / "ws-rt" / "github-publisher-config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("{}", encoding="utf-8")
        got = gh_config.resolve_config_path(workspace=str(ws), home=str(home))
        self.assertEqual(got, cfg)

    def test_resolve_defaults_to_home_when_none_exist(self):
        td = make_tempdir()
        home = Path(td) / "home"
        ws = Path(td) / "ws"
        got = gh_config.resolve_config_path(workspace=str(ws), home=str(home), walk_up=False)
        self.assertEqual(got, home / ".dsh" / "github-publisher" / "config.json")

    def test_resolve_walks_up_to_ws_rt(self):
        td = make_tempdir()
        home = Path(td) / "home"
        ws_root = Path(td) / "ws"
        cfg = ws_root / "ws-rt" / "github-publisher-config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("{}", encoding="utf-8")
        deep = ws_root / "a" / "b" / "c"  # cwd nested 3 levels down
        got = gh_config.resolve_config_path(workspace=str(deep), home=str(home))
        self.assertEqual(got, cfg)

    def test_cli_init_writes_config_from_stdin(self):
        td = make_tempdir()
        home = Path(td) / "home"
        ws = Path(td) / "ws"
        import io
        import json as _json
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_config.main(
                ["init", "--owner", "ya123-4"],
                stdin=io.StringIO("ghp_from_stdin\n"),
                home=str(home),
                workspace=str(ws),
            )
        self.assertEqual(code, 0)
        payload = _json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertNotIn("ghp_from_stdin", buf.getvalue())
        cfg = gh_config.load_config(home / ".dsh" / "github-publisher" / "config.json")
        self.assertEqual(cfg["token"], "ghp_from_stdin")
        self.assertEqual(cfg["owner"], "ya123-4")

    def test_cli_init_empty_stdin_exit_2(self):
        td = make_tempdir()
        import io
        import json as _json
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_config.main(
                ["init"],
                stdin=io.StringIO("  \n"),
                home=str(Path(td) / "home"),
                workspace=str(Path(td) / "ws"),
            )
        self.assertEqual(code, 2)
        payload = _json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])

    def test_cli_init_falls_back_when_home_path_unwritable(self):
        td = make_tempdir()
        home = Path(td) / "home"
        ws = Path(td) / "ws"
        # make the home candidate's parent chain un-creatable: .dsh is a FILE
        home.mkdir()
        (home / ".dsh").write_text("i am a file", encoding="utf-8")
        import io
        import json as _json
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = gh_config.main(
                ["init", "--owner", "ya123-4"],
                stdin=io.StringIO("ghp_fallback\n"),
                home=str(home),
                workspace=str(ws),
            )
        self.assertEqual(code, 0)
        payload = _json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["config_path"],
            str(ws / "ws-rt" / "github-publisher-config.json"),
        )


if __name__ == "__main__":
    unittest.main()
