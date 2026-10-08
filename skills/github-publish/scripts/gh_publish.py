"""github-publish core executor.

Stages:
  0 self-check (config, tgz, TLS, token)
  1 idempotent repo creation  (exit 3 on failure)
  2 local repo preparation     (exit 4)   -- Task 5
  3 secure push                (exit 5)   -- Task 5
  4 Release creation           (exit 6)   -- Task 6
  5 tgz asset upload           (exit 7)   -- Task 6
  6 verification + report      (exit 0)

Every GitHub API call goes through urllib with an injectable opener; git is
used only for local operations and the push. The token never touches disk,
git config, or a remote URL.
"""
import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path
from urllib.request import Request, build_opener

import gh_check
import gh_config

API = "https://api.github.com"
GZIP_MAGIC = b"\x1f\x8b"

EXIT_OK = 0
EXIT_CHECK = 2
EXIT_REPO = 3
EXIT_COMMIT = 4
EXIT_PUSH = 5
EXIT_RELEASE = 6
EXIT_ASSET = 7


def build_repo_payload(name: str, description: str, private: bool) -> dict:
    return {
        "name": name,
        "description": description,
        "private": bool(private),
        "auto_init": False,
    }


def _default_repo_name(pkg_name: str, suffix: str) -> str:
    if suffix and pkg_name.endswith(suffix):
        return pkg_name
    return pkg_name + suffix


def emit_result(ok: bool, stage: str, message: str, hint: str = "", **fields) -> str:
    payload = {"ok": ok, "stage": stage, "message": message}
    if hint:
        payload["hint"] = hint
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


def create_repo_if_missing(
    opener, token: str, owner: str, name: str, description: str, private: bool,
    retries: int = 2, sleep_s: float = 2.0,
) -> dict:
    """POST /user/repos. 201->created; 422 already_exists->exists; else error.

    Network failures retry `retries` more times with `sleep_s` between tries.
    """
    payload = build_repo_payload(name, description, private)
    data = json.dumps(payload).encode("utf-8")
    url = f"{API}/user/repos"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-publisher-skill-dsh",
        "Content-Type": "application/json",
    }
    op = opener or build_opener()
    last_err = "unknown"
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(sleep_s)
        try:
            req = Request(url, data=data, headers=headers, method="POST")
            with op.open(req, timeout=15) as resp:
                status = resp.status
                body = resp.read()
        except Exception as exc:
            last_err = gh_config.mask_token(str(exc), token)
            continue
        text = body.decode("utf-8", "replace")
        if status == 201:
            try:
                info = json.loads(text)
                html_url = info.get("html_url", "")
            except Exception:
                html_url = ""
            return {"status": "created", "html_url": html_url, "message": "仓库已创建"}
        if status == 422:
            if "already_exists" in text or "already exists" in text.lower():
                return {
                    "status": "exists",
                    "html_url": f"https://github.com/{owner}/{name}",
                    "message": "仓库已存在，复用",
                }
            return {"status": "error", "message": f"HTTP 422：{text[:200]}"}
        if status == 403:
            return {
                "status": "error",
                "message": "HTTP 403：token 权限不足（需要创建仓库的权限）",
            }
        if status == 404:
            return {"status": "error", "message": "HTTP 404：token 无效或账号不存在"}
        if status >= 500:
            last_err = f"HTTP {status}"
            continue
        return {"status": "error", "message": f"HTTP {status}：{text[:200]}"}
    return {
        "status": "error",
        "message": f"建仓失败（已重试 {retries} 次）：{last_err}",
    }


def _is_gzip(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(2) == GZIP_MAGIC
    except OSError:
        return False


def _read_package(dir_path: str) -> dict:
    p = Path(dir_path) / "package.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"无法读取 {p}：{exc}") from exc


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="gh_publish.py", description="Publish a DSH plugin to GitHub")
    parser.add_argument("--dir", required=True, help="插件源码目录（含 package.json）")
    parser.add_argument("--tgz", required=True, help="已打包的 tgz 文件路径")
    parser.add_argument("--repo-name", default=None, help="仓库名（默认 <包名>+后缀）")
    parser.add_argument("--description", default=None, help="仓库描述（默认 package.json description）")
    parser.add_argument("--private", action="store_true", help="创建私有仓库（默认公开）")
    parser.add_argument("--tag", default=None, help="Release tag（默认 v<version>）")
    parser.add_argument("--config", default=None, help="配置文件路径（默认自动探测）")
    return parser.parse_args(argv)


def _fail(code, stage, message, hint="", **fields):
    print(emit_result(False, stage, message, hint=hint, **fields))
    return code


def main(argv, *, opener=None, tls_probe=None, sleep_s=2.0) -> int:
    args = _parse_args(argv)

    # Stage 0a: tgz sanity (packaging is the caller's job, we only verify)
    tgz = Path(args.tgz)
    if not tgz.exists() or not _is_gzip(tgz):
        return _fail(EXIT_CHECK, "check", "tgz 不存在或不是 gzip 文件", hint="请先用 npm pack 打包")

    # Stage 0b: config
    try:
        cfg_path = Path(args.config) if args.config else gh_config.resolve_config_path()
        cfg = gh_config.load_config(cfg_path)
    except gh_config.ConfigError as exc:
        return _fail(EXIT_CHECK, "check", str(exc), hint="运行 gh_check.py 完成一次性 PAT 配置")
    token = cfg.get("token", "")
    owner = cfg.get("owner", "")
    if not token or not owner:
        return _fail(EXIT_CHECK, "check", "config 缺少 token 或 owner", hint="请先完成一次性 PAT 配置")

    # Stage 0c: environment (TLS + token validity)
    try:
        env = gh_check.check_environment(cfg_path, opener=opener, tls_probe=tls_probe)
    except gh_config.ConfigError as exc:
        return _fail(EXIT_CHECK, "check", str(exc))
    if not env["tls_ok"] or not env["token_ok"]:
        return _fail(EXIT_CHECK, "check", "；".join(env["messages"]))

    # Stage 1: idempotent repo creation
    try:
        pkg = _read_package(args.dir)
    except ValueError as exc:
        return _fail(EXIT_CHECK, "check", str(exc))
    suffix = cfg.get("defaults", {}).get("repo_suffix", "-dsh")
    name = args.repo_name or _default_repo_name(pkg.get("name", ""), suffix)
    description = args.description or pkg.get("description", "")
    private = args.private or cfg.get("defaults", {}).get("visibility") == "private"
    repo = create_repo_if_missing(
        opener, token, owner, name, description, private, sleep_s=sleep_s
    )
    if repo["status"] == "error":
        return _fail(EXIT_REPO, "repo", repo["message"])
    print(
        emit_result(
            True, "repo", repo["message"], repo_name=name, html_url=repo["html_url"]
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
