"""github-publisher config store: PAT, owner, author, defaults.

All file I/O is UTF-8. The token is stored in one dedicated JSON file that
must never be committed to git; any text emitted by this module is token-safe.
"""
import json
import os
import subprocess
from pathlib import Path

DEFAULT_AUTHOR_NAME = "DSH Maintainers"
DEFAULT_AUTHOR_EMAIL = "dsh-maintainers@users.noreply.github.com"

HOME_CANDIDATE_SUFFIX = Path(".dsh") / "github-publisher" / "config.json"
WS_CANDIDATE_SUFFIX = Path("ws-rt") / "github-publisher-config.json"


class ConfigError(Exception):
    """Raised when the config file is missing, unreadable, or corrupt."""


def config_template(owner: str) -> dict:
    return {
        "owner": owner,
        "token": "",
        "author": {"name": DEFAULT_AUTHOR_NAME, "email": DEFAULT_AUTHOR_EMAIL},
        "defaults": {"visibility": "public", "repo_suffix": "-dsh"},
    }


def _candidates(workspace, home):
    home = Path(home) if home else Path(os.path.expanduser("~"))
    ws = Path(workspace) if workspace else Path.cwd()
    candidates = [home / HOME_CANDIDATE_SUFFIX]
    # walk up from the cwd so a config under any ancestor's ws-rt/ is found
    p = ws
    seen = set()
    while p is not None and p not in seen and p != p.parent:
        seen.add(p)
        candidates.append(p / WS_CANDIDATE_SUFFIX)
        p = p.parent
    return candidates


def _readable(path) -> bool:
    try:
        with open(path, "r", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


def resolve_config_path(workspace=None, home=None, walk_up=True) -> Path:
    """First existing AND readable candidate wins (scripts only read the
    config; writability matters only when init writes it and save_config's
    fallback handles that). Falls back to the first existing candidate,
    then to the home default when nothing exists."""
    if walk_up:
        candidates = _candidates(workspace, home)
    else:
        candidates = _candidates(workspace, home)[:1] + [
            Path(workspace or Path.cwd()) / WS_CANDIDATE_SUFFIX
        ]
    first_existing = None
    for c in candidates:
        if c.exists():
            if first_existing is None:
                first_existing = c
            if _readable(c):
                return c
    if first_existing is not None:
        return first_existing
    return candidates[0]


def load_config(path) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"无法读取配置文件 {path}（{exc}）。请重新配置。"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"配置文件 {path} 损坏：{exc}。请删除该文件后重新配置。"
        ) from exc


def save_config(path, config: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    restrict_file(p)


def restrict_file(path) -> bool:
    """Best-effort ACL tightening on Windows (icacls). Returns False on failure."""
    if os.name != "nt":
        return True
    try:
        user = os.environ.get("USERNAME", "")
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(RX,W,D)"],
            check=True,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def mask_token(text: str, token: str) -> str:
    if not token:
        return text
    return text.replace(token, "***")


def main(argv=None, *, stdin=None, home=None, workspace=None) -> int:
    """CLI: `python gh_config.py init` reads the PAT from STDIN (never from
    argv, so the token never shows up in process listings or shell history)
    and writes the config file, falling back across writable candidates."""
    import argparse
    import json as _json
    import sys as _sys

    ap = argparse.ArgumentParser(
        prog="gh_config.py", description="github-publisher config store"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser(
        "init", help="create the config file from a PAT read on stdin"
    )
    p_init.add_argument("--owner", default="ya123-4", help="GitHub owner (default ya123-4)")
    p_init.add_argument("--author-name", default=DEFAULT_AUTHOR_NAME)
    p_init.add_argument("--author-email", default=DEFAULT_AUTHOR_EMAIL)
    args = ap.parse_args(argv)

    if args.cmd == "init":
        stream = stdin if stdin is not None else _sys.stdin
        token = stream.read().strip()
        if not token:
            print(_json.dumps({"ok": False, "message": "stdin 未提供 PAT"}, ensure_ascii=False))
            return 2
        cfg = config_template(args.owner)
        cfg["token"] = token
        cfg["author"] = {"name": args.author_name, "email": args.author_email}
        written = None
        failures = []
        for c in _candidates(workspace, home):
            try:
                save_config(c, cfg)
                written = c
                break
            except Exception as exc:
                failures.append(f"{c}: {exc}")
        if written is None:
            print(
                _json.dumps(
                    {"ok": False, "message": "没有可写的配置位置", "failures": failures},
                    ensure_ascii=False,
                )
            )
            return 2
        print(
            _json.dumps(
                {"ok": True, "config_path": str(written), "token_stored": True},
                ensure_ascii=False,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    import sys as _sys

    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _sys.exit(main())
