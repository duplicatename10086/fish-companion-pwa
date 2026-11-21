#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一自检（全部读 config.json）。

  ① 主进程      AstrBot HTTP 服务在不在
  ② OpenAPI     用 key 能不能读人格
  ③ 人设完整性   人设/记忆文件在不在、人格是否非空
  ④ 端到端      真发一句话，看回的是不是你的角色名
  ⑤ 工作模式     桥接插件装没装、端点通不通（可选）
  ⑥ 启动器       启动器文件在不在

用法：python scripts/selfcheck.py [--no-chat]
退出码 0 = 全过；非 0 = 失败项数。
"""
from __future__ import annotations

import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    ROOT, base_url, cfg, http, http_json, persona_id, read_key, resolve, say,
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("  " + detail if detail else ""))
    return ok


def check_process() -> bool:
    code, _, raw = http("/api/stat/start-time", timeout=8)
    ok = code == 200
    detail = ""
    if ok:
        try:
            start = json.loads(raw.decode())["data"]["start_time"]
            import time
            detail = f"已运行 {(time.time() - start) / 60:.0f} 分钟"
        except Exception:  # noqa: BLE001
            pass
    else:
        detail = f"HTTP {code}"
    return record("① 主进程", ok, detail)


def check_openapi() -> bool:
    key = read_key()
    if not key:
        return record("② OpenAPI", False, "secrets/apikey.txt 不存在（先跑 ctl.py make-key）")
    code, obj = http_json("/api/v1/personas", token=key)
    if code != 200:
        return record("② OpenAPI", False, f"HTTP {code}")
    names = {}
    if isinstance(obj, dict):
        for p in obj.get("data", []):
            names[p.get("persona_id")] = len(p.get("system_prompt") or "")
    pid = persona_id()
    ok = names.get(pid, 0) > 50
    return record("② OpenAPI", ok, f"人格 {pid}:{names.get(pid, 0)}字 " + ", ".join(f"{k}:{v}" for k, v in names.items()))


def check_assets() -> bool:
    ok = True
    for key in ("persona.identity_file", "persona.memory_file"):
        path = resolve(str(cfg(key, "")))
        exists = os.path.exists(path)
        ok &= record(f"③ 文件 {os.path.basename(path)}", exists, "" if exists else f"缺失 {path}")
    return ok


def check_chat() -> bool:
    key = read_key()
    if not key:
        return record("④ 端到端", False, "没有 API key")
    name = str(cfg("character.name", ""))
    body = {"message": "你是谁", "username": "自检", "enable_streaming": False}
    code, ctype, raw = http("/api/v1/chat", "POST", body, key, timeout=180)
    if code != 200:
        return record("④ 端到端", False, f"HTTP {code} {raw[:100]!r}")
    reply = ""
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:"):
            continue
        try:
            frame = json.loads(line[5:].strip())
        except Exception:
            continue
        if frame.get("type") != "plain" or frame.get("chain_type") in ("tool_call", "tool_call_result"):
            continue
        data = frame.get("data")
        if isinstance(data, str):
            reply += data
    if "────" in reply:
        reply = reply.rsplit("────", 1)[-1]
    reply = reply.strip()
    # 角色名出现在回复里即算通过；没填名字就只要求有回复
    ok = bool(reply) and (name in reply if name else True)
    return record("④ 端到端", ok, reply[:60].replace("\n", " "))


def check_workmode() -> bool:
    if not cfg("workmode.enabled", True):
        return record("⑤ 工作模式", True, "已在 config 里关闭，跳过")
    key = read_key()
    if not key:
        return record("⑤ 工作模式", False, "没有 API key")
    route = "/api/v1/plugins/extensions/astrbot_plugin_client_bridge/health"
    code, obj = http_json(route, token=key, timeout=10)
    detail = ""
    if code == 200 and isinstance(obj, dict):
        d = obj.get("data") or {}
        detail = f"v{d.get('version')} guard={d.get('guard_priority')}"
    return record("⑤ 工作模式", code == 200, detail or f"HTTP {code}（插件没装或没启用？）")


def check_launcher() -> bool:
    hta = os.path.join(ROOT, "启动器.hta")
    exists = os.path.exists(hta)
    return record("⑥ 启动器", exists, "启动器.hta" if exists else "缺失，先跑 python scripts/render.py")


def main() -> int:
    say(f"selfcheck  {base_url()}")
    check_process()
    check_openapi()
    check_assets()
    if "--no-chat" not in sys.argv:
        check_chat()
    check_workmode()
    check_launcher()
    failed = [r for r in results if not r[1]]
    print()
    print(f"结果：{len(results) - len(failed)}/{len(results)} 通过" + ("" if not failed else f"，{len(failed)} 项失败"))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
