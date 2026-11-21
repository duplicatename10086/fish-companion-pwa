"""公共基础模块：配置加载、路径解析、HTTP、日志。

所有脚本都从这里取配置，避免把名字、端口、路径写死在各自文件里。
用法：
    from common import cfg, resolve, http_json, say, ROOT

    base = cfg("astrbot.base_url")
    persona = resolve(cfg("persona.identity_file"))
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
EXAMPLE_PATH = os.path.join(ROOT, "config.example.json")


def _load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit(
            "找不到 config.json。请先复制 config.example.json 为 config.json 并修改，"
            "或运行：python scripts/setup.py"
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_CFG: dict | None = None


def config() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = _load()
    return _CFG


def cfg(dotted: str, default=None):
    """按 a.b.c 取配置值；任何一段不存在返回 default。"""
    cur = config()
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def resolve(path: str) -> str:
    """相对路径基于项目根，绝对路径原样返回，~ 会展开。"""
    if not path:
        return path
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(ROOT, path)


def base_url() -> str:
    return str(cfg("astrbot.base_url", "http://127.0.0.1:6185")).rstrip("/")


def admin_password() -> str:
    """管理密码只从环境变量读，绝不写进仓库。"""
    env_name = str(cfg("astrbot.admin_password_env", "ASTRBOT_PWD"))
    pwd = os.environ.get(env_name, "")
    if not pwd:
        raise SystemExit(
            f"管理密码未设置。请先设置环境变量 {env_name} 再运行本脚本。"
            "（setup 向导会告诉你怎么设）"
        )
    return pwd


def admin_user() -> str:
    return str(cfg("astrbot.admin_user", "astrbot"))


def persona_id() -> str:
    return str(cfg("character.persona_id", cfg("character.name", "companion")))


def http(path: str, method: str = "GET", body=None, token: str | None = None, timeout: int = 60):
    """返回 (status, content_type, raw_bytes)。网络异常时 status=-1。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    url = base_url() + path
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()
    except Exception as e:  # noqa: BLE001
        return -1, "", repr(e).encode("utf-8")


def http_json(path: str, method: str = "GET", body=None, token: str | None = None, timeout: int = 60):
    """返回 (status, parsed)。parsed 为 dict/list 或原始文本。"""
    code, _, raw = http(path, method, body, token, timeout)
    text = raw.decode("utf-8", "replace")
    try:
        return code, json.loads(text)
    except Exception:
        return code, text


def login() -> str:
    """登录 AstrBot 后台，返回 token。"""
    code, obj = http_json(
        "/api/v1/auth/login",
        "POST",
        {"username": admin_user(), "password": admin_password()},
    )
    token = ""
    if isinstance(obj, dict):
        token = ((obj.get("data") or {}).get("token")) or ""
    if not token:
        raise SystemExit(f"[FAIL] 登录失败 HTTP {code}: {str(obj)[:160]}")
    say(f"[ok] 已登录 {admin_user()}")
    return token


def read_key() -> str:
    """读取 OpenAPI key（由 ctl.py make-key 生成，存于 secrets/apikey.txt）。"""
    path = os.path.join(ROOT, "secrets", "apikey.txt")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def say(msg: str) -> None:
    """Windows 控制台安全输出：非 ASCII 字符替换为 ?，避免 cmd 乱码。"""
    print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def log(msg: str) -> None:
    log_dir = os.path.join(ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(log_dir, "ctl.log"), "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {msg}\n")
