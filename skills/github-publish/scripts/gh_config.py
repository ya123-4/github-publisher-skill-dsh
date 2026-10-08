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


def resolve_config_path(workspace=None, home=None, walk_up=True) -> Path:
    """First existing candidate wins; if none exists, default to the home one."""
    candidates = _candidates(workspace, home) if walk_up else _candidates(workspace, home)[:1] + [Path(workspace or Path.cwd()) / WS_CANDIDATE_SUFFIX]
    for c in candidates:
        if c.exists():
            return c
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
