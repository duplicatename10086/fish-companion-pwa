#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AstrBot 控制台（全部读 config.json）。

子命令：
  set-persona   把人设+记忆写进 AstrBot 人格库（并同步 default）
  show-persona  读回人格确认同步成功
  make-key      创建 OpenAPI Key，存到 secrets/apikey.txt
  send TEXT     用 key 试聊一句
  status        看端口状态
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    ROOT, cfg, config, http, http_json, login, log, persona_id,
    read_key, resolve, say,
)

DEFAULT_SCOPES = ["chat", "file", "im", "persona", "bot", "provider", "data"]


def sse_text(body: bytes) -> str:
    """从 AstrBot SSE 流里提取可见回复，丢掉思维链与工具帧。"""
    parts: list[str] = []
    too_large: list[str] = []
    for line in body.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            frame = json.loads(chunk)
        except Exception:
            continue
        if not isinstance(frame, dict):
            continue
        kind, chain, data = frame.get("type"), frame.get("chain_type"), frame.get("data")
        if kind == "plain" and isinstance(data, str) and data:
            if chain in ("tool_call", "tool_call_result"):
                continue
            if data.lstrip().startswith("🤔"):
                continue
            if parts and data == parts[-1]:
                continue
            if parts and data.startswith(parts[-1]):
                parts[-1] = data
            else:
                parts.append(data)
        elif kind == "image" and isinstance(data, str):
            too_large.append(data)
    text = "".join(parts).strip()
    if too_large:
        text += "\n[附带图片] " + ", ".join(too_large)
    return text or "(没有 plain 帧)"


def build_persona() -> str:
    identity_path = resolve(cfg("persona.identity_file", "persona/人设.md"))
    memory_path = resolve(cfg("persona.memory_file", "persona/记忆.md"))
    parts = []
    for path in (identity_path, memory_path):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                parts.append(f.read().strip())
        else:
            say(f"[warn] 缺少 {path}")
    return "\n\n---\n\n".join(parts) + "\n"


def cmd_set_persona(_args) -> int:
    token = login()
    prompt = build_persona()
    targets = [persona_id()]
    if cfg("persona.sync_default_too", True):
        targets.append("default")
    results = []
    for name in targets:
        pid = urllib.parse.quote(name, safe="")
        code, _, body = http(f"/api/v1/personas/{pid}", "PUT", {"system_prompt": prompt}, token)
        obj = json.loads(body.decode("utf-8", "replace")) if body else {}
        ok = code == 200 and isinstance(obj, dict) and obj.get("status") == "ok"
        results.append((name, code, ok))
        log(f"set-persona[{name}] status={code}")
    ok = all(r[2] for r in results)
    say(f"[{'ok' if ok else 'FAIL'}] set-persona {len(prompt)}字 " + ", ".join(f"{n}:{c}" for n, c, _ in results))
    return 0 if ok else 1


def cmd_show_persona(_args) -> int:
    token = login()
    pid = urllib.parse.quote(persona_id(), safe="")
    code, obj = http_json(f"/api/v1/personas/by-id?persona_id={pid}", token=token)
    prompt = ""
    if isinstance(obj, dict):
        prompt = ((obj.get("data") or {}).get("system_prompt") or "")
    say(f"[{'ok' if code == 200 else 'FAIL'}] show-persona {code} {len(prompt)}字")
    if prompt:
        print(prompt[:500])
    return 0 if code == 200 else 1


def cmd_make_key(args) -> int:
    token = login()
    name = args.name or cfg("character.name", "companion")
    code, obj = http_json("/api/v1/api-keys", "POST", {"name": name, "scopes": DEFAULT_SCOPES}, token)
    data = (obj.get("data") or {}) if isinstance(obj, dict) else {}
    key = data.get("api_key") or ""
    if code != 200 or not key:
        say(f"[FAIL] make-key {code}: {str(obj)[:160]}")
        return 1
    secret_dir = os.path.join(ROOT, "secrets")
    os.makedirs(secret_dir, exist_ok=True)
    with open(os.path.join(secret_dir, "apikey.txt"), "w", encoding="utf-8") as f:
        f.write(key + "\n")
    say(f"[ok] 已创建 key（{data.get('key_prefix', '')}...）-> secrets/apikey.txt")
    return 0


def cmd_send(args) -> int:
    key = read_key()
    if not key:
        say("[FAIL] 还没有 key，先运行 make-key")
        return 2
    payload = {
        "message": args.text,
        "username": args.username or cfg("character.call_user", "主人"),
        "enable_streaming": False,
    }
    code, ctype, body = http("/api/v1/chat", "POST", payload, key, timeout=240)
    reply = sse_text(body) if "event-stream" in ctype else body.decode("utf-8", "replace")[:2000]
    say(f"[{'ok' if code == 200 else 'FAIL'}] chat {code} {len(reply)}字")
    print(reply[:800])
    return 0 if code == 200 else 1


def cmd_status(_args) -> int:
    import socket
    ports = [
        (int(cfg("ports.astrbot", 6185)), "AstrBot 网关"),
        (int(cfg("ports.local_model", 8088)), "本地模型"),
    ]
    for port, label in ports:
        s = socket.socket()
        s.settimeout(0.6)
        up = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        say(f"  {port}  {label:12s} {'UP' if up else 'down'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=f"{cfg('character.name', 'Companion')} AstrBot 控制台")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("set-persona").set_defaults(func=cmd_set_persona)
    sub.add_parser("show-persona").set_defaults(func=cmd_show_persona)
    k = sub.add_parser("make-key")
    k.add_argument("--name")
    k.set_defaults(func=cmd_make_key)
    s = sub.add_parser("send")
    s.add_argument("text")
    s.add_argument("--username")
    s.set_defaults(func=cmd_send)
    sub.add_parser("status").set_defaults(func=cmd_status)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
