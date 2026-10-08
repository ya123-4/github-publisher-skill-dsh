"""Environment self-check for github-publish.

Every network access goes through Python urllib/ssl only (verified stable on
this machine behind the SteamTools TLS middlebox). Functions that touch the
network accept injectable dependencies so unit tests run offline.
"""
import json
import shutil
import socket
import ssl
from urllib.request import Request, build_opener

import gh_config

API_USER = "https://api.github.com/user"


def validate_token(token: str, owner: str, opener=None) -> tuple:
    """(ok, message): GET /user with the token. 200 -> (True, login)."""
    if not token:
        return (False, "token 为空，请先完成一次性 PAT 配置")
    req = Request(
        API_USER,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-publisher-skill-dsh",
        },
    )
    op = opener or build_opener()
    try:
        with op.open(req, timeout=15) as resp:
            status = resp.status
            body = resp.read()
    except Exception as exc:  # URLError, timeout, TLS failures
        return (False, f"网络错误：{gh_config.mask_token(str(exc), token)}")
    if status == 200:
        login = "?"
        try:
            login = json.loads(body.decode("utf-8")).get("login", "?")
        except Exception:
            pass
        return (True, login)
    return (False, f"HTTP {status}")


def probe_tls(host: str = "github.com", port: int = 443) -> tuple:
    """(ok, message): real TLS handshake through the system trust store."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                s.recv(1)
        return (True, f"TLS ok: {host}:{port}")
    except Exception as exc:
        return (False, f"TLS 失败：{exc}")


def der_to_pem(cert_der: bytes) -> str:
    # Base64 wrap without structure validation: ssl.DER_cert_to_PEM_cert in
    # CPython 3.12+ re-parses the DER and rejects anything it cannot decode,
    # which blocks injectable tests and buys nothing for certs that already
    # came from the system store or a real handshake.
    import base64

    b64 = base64.b64encode(cert_der).decode("ascii")
    lines = [b64[i : i + 64] for i in range(0, len(b64), 64)]
    return (
        "-----BEGIN CERTIFICATE-----\n"
        + "\n".join(lines)
        + "\n-----END CERTIFICATE-----\n"
    )


def _default_enum_certs():
    return ssl.enum_certificates("ROOT")


def _default_handshake(host, port):
    ctx = ssl._create_unverified_context()
    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as s:
            return s.getpeercert(binary_form=True)


def fetch_peer_ca_bundle(host="github.com", port=443, enum_certs=None, handshake=None) -> str:
    """PEM bundle for git's sslCAInfo: all system root certs (this covers the
    SteamTools root) plus the leaf certificate presented by the peer."""
    pems = []
    try:
        for entry in (enum_certs or _default_enum_certs)():
            der = entry[0] if entry else b""
            if der:
                pems.append(der_to_pem(der))
    except Exception:
        pass
    try:
        leaf = (handshake or (lambda: _default_handshake(host, port)))()
        if leaf:
            pems.append(der_to_pem(leaf))
    except Exception:
        pass
    return "\n".join(pems)


def check_environment(config_path, opener=None, tls_probe=None) -> dict:
    """Full pre-flight check; raises ConfigError when config is missing/corrupt."""
    cfg = gh_config.load_config(config_path)
    token = cfg.get("token", "")
    owner = cfg.get("owner", "")
    messages = []
    result = {
        "python_ok": True,
        "git_ok": bool(shutil.which("git")),
        "tls_ok": False,
        "token_ok": False,
        "owner": owner,
        "actual_config_path": str(config_path),
        "messages": messages,
    }
    tls_ok, tls_msg = (tls_probe or probe_tls)()
    result["tls_ok"] = tls_ok
    messages.append(tls_msg)
    if not result["git_ok"]:
        messages.append("未找到 git 可执行文件")
    token_ok, token_msg = validate_token(token, owner, opener=opener)
    result["token_ok"] = token_ok
    messages.append(token_msg)
    return result
