"""Tests for gh_publish stages 2-3: local repo preparation and secure push."""
import base64
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "github-publish" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_publish  # noqa: E402
from _helpers import make_tempdir  # noqa: E402

LICENSE_TEXT = "MIT License (test)"


class GitRun:
    """Fake run_git_capture: records argv; per-call stdout/returncode/stderr
    queues (each `when` appends one response; exhausted queues default to
    success so multi-invocation sequences can model transient failures)."""

    def __init__(self):
        self.calls = []
        self.handlers = {}

    def when(self, needle, stdout="", returncode=0, stderr=""):
        self.handlers.setdefault(needle, []).append((stdout, returncode, stderr))

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        for needle, queue in self.handlers.items():
            if any(needle in a for a in argv):
                if queue:
                    stdout, returncode, stderr = queue.pop(0)
                    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def real_git(args, cwd):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class GitStageTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(
            Path(__file__).resolve().parents[2] / ".tmp-github-publisher-tests",
            ignore_errors=True,
        )

    def test_prepare_local_repo_files_and_author(self):
        td = make_tempdir()
        pkg = {"name": "foo-dsh", "version": "0.1.0", "description": "自动入库插件"}
        gh_publish.prepare_local_repo(
            Path(td),
            {"name": "DSH Maintainers", "email": "dsh-maintainers@users.noreply.github.com"},
            readme_en=f"# {pkg['name']}\n\ndesc-en\n",
            readme_zh=f"# {pkg['name']}\n\n{pkg['description']}\n",
            license_text=LICENSE_TEXT,
            pkg=pkg,
        )
        self.assertTrue((Path(td) / ".git").exists())
        self.assertIn("foo-dsh", (Path(td) / "README.md").read_text(encoding="utf-8"))
        self.assertIn("自动入库插件", (Path(td) / "README.zh.md").read_text(encoding="utf-8"))
        self.assertIn("MIT License", (Path(td) / "LICENSE").read_text(encoding="utf-8"))
        gi = (Path(td) / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("config.json", gi)
        self.assertIn(".github-publisher-ca-", gi)
        r = real_git(["log", "-1", "--format=%an <%ae>"], td)
        self.assertEqual(r.stdout.strip(), "DSH Maintainers <dsh-maintainers@users.noreply.github.com>")

    def test_prepare_local_repo_utf8_commit(self):
        td = make_tempdir()
        pkg = {"name": "foo-dsh", "version": "0.1.0", "description": "自动入库插件"}
        gh_publish.prepare_local_repo(
            Path(td),
            {"name": "DSH Maintainers", "email": "dsh-maintainers@users.noreply.github.com"},
            readme_en="# foo-dsh\n\nen\n",
            readme_zh=f"# foo-dsh\n\n{pkg['description']}\n",
            license_text=LICENSE_TEXT,
            pkg=pkg,
        )
        r = real_git(["show", "HEAD:README.zh.md"], td)
        self.assertIn("自动入库插件", r.stdout)

    def test_prepare_local_repo_keeps_existing_files(self):
        td = make_tempdir()
        pkg = {"name": "foo-dsh", "version": "0.1.0", "description": "自动入库插件"}
        (Path(td) / "README.md").write_text("# Custom readme\n\nhand-written\n", encoding="utf-8")
        (Path(td) / "README.zh.md").write_text("# 自定义说明\n", encoding="utf-8")
        (Path(td) / "LICENSE").write_text("Custom license\n", encoding="utf-8")
        (Path(td) / ".gitignore").write_text("custom-ignore-entry\n", encoding="utf-8")
        gh_publish.prepare_local_repo(
            Path(td),
            {"name": "DSH Maintainers", "email": "dsh-maintainers@users.noreply.github.com"},
            readme_en="# TEMPLATE\n",
            readme_zh="# 模板\n",
            license_text="TEMPLATE LICENSE",
            pkg=pkg,
        )
        self.assertEqual((Path(td) / "README.md").read_text(encoding="utf-8"), "# Custom readme\n\nhand-written\n")
        self.assertEqual((Path(td) / "README.zh.md").read_text(encoding="utf-8"), "# 自定义说明\n")
        self.assertEqual((Path(td) / "LICENSE").read_text(encoding="utf-8"), "Custom license\n")
        self.assertEqual((Path(td) / ".gitignore").read_text(encoding="utf-8"), "custom-ignore-entry\n")

    def test_remote_is_empty(self):
        td = make_tempdir()
        ca = Path(td) / "ca.pem"
        ca.write_text("PEM", encoding="utf-8")
        run = GitRun()
        run.when("ls-remote", stdout="")
        self.assertTrue(gh_publish.remote_is_empty(run, "https://github.com/o/r.git", "ghp_x", "o", str(ca)))
        run2 = GitRun()
        run2.when("ls-remote", stdout="abc\trefs/heads/main")
        self.assertFalse(gh_publish.remote_is_empty(run2, "https://github.com/o/r.git", "ghp_x", "o", str(ca)))
        self.assertTrue(ca.exists())  # remote_is_empty must NOT delete the CA file

    def test_push_cmd_contains_security_flags(self):
        td = make_tempdir()
        run = GitRun()
        code, detail = gh_publish.push_main(
            Path(td),
            "https://github.com/ya123-4/foo-dsh.git",
            token="ghp_x",
            owner="ya123-4",
            ca_pem="FAKE-PEM",
            run_git_capture=run,
            ca_base_dir=Path(td),
        )
        self.assertEqual(code, 0)
        self.assertEqual(detail, "")
        flat = [a for call in run.calls for a in call]
        self.assertIn("http.sslBackend=openssl", flat)
        self.assertTrue(any(a.startswith("http.sslCAInfo=") for a in flat))
        auth = [a for a in flat if a.startswith("http.extraHeader=Authorization: Basic ")]
        self.assertTrue(auth)
        decoded = base64.b64decode(auth[0].split("Basic ")[1]).decode()
        self.assertEqual(decoded, "ya123-4:ghp_x")
        self.assertTrue(all("ghp_x" not in a for a in flat))
        self.assertTrue(any("push" in a for a in flat))
        self.assertFalse(any("pull" in a for a in flat))

    def test_push_reports_stderr_on_failure(self):
        td = make_tempdir()
        run = GitRun()
        run.when("push", returncode=1, stderr="fatal: unable to access ... 403")
        code, detail = gh_publish.push_main(
            Path(td),
            "https://github.com/ya123-4/foo-dsh.git",
            token="ghp_x",
            owner="ya123-4",
            ca_pem="FAKE-PEM",
            run_git_capture=run,
            ca_base_dir=Path(td),
        )
        self.assertEqual(code, 1)
        self.assertIn("403", detail)
        self.assertNotIn("ghp_x", detail)

    def test_push_reports_pull_failure_distinctly(self):
        td = make_tempdir()
        run = GitRun()
        run.when("ls-remote", stdout="abc\trefs/heads/main")
        run.when("pull", returncode=1, stderr="CONFLICT")
        code, detail = gh_publish.push_main(
            Path(td),
            "https://github.com/ya123-4/foo-dsh.git",
            token="ghp_x",
            owner="ya123-4",
            ca_pem="FAKE-PEM",
            run_git_capture=run,
            ca_base_dir=Path(td),
        )
        self.assertEqual(code, 1)
        self.assertIn("pull", detail)
        self.assertIn("CONFLICT", detail)

    def test_push_pulls_when_remote_nonempty(self):
        td = make_tempdir()
        run = GitRun()
        run.when("ls-remote", stdout="abc\trefs/heads/main")
        code, _detail = gh_publish.push_main(
            Path(td),
            "https://github.com/ya123-4/foo-dsh.git",
            token="ghp_x",
            owner="ya123-4",
            ca_pem="FAKE-PEM",
            run_git_capture=run,
            ca_base_dir=Path(td),
        )
        self.assertEqual(code, 0)
        pull_idx = next(
            i for i, c in enumerate(run.calls) if any("pull" in a for a in c)
        )
        push_idx = next(
            i for i, c in enumerate(run.calls) if any("push" in a for a in c)
        )
        self.assertLess(pull_idx, push_idx)

    def test_write_ca_tempfile(self):
        td = make_tempdir()
        p = gh_publish.write_ca_tempfile("PEMDATA", base_dir=Path(td))
        self.assertEqual(p.parent, Path(td))
        self.assertEqual(p.read_text(encoding="utf-8"), "PEMDATA")
        p.unlink()


if __name__ == "__main__":
    unittest.main()
