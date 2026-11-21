#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 templates/ 下的脚本模板按 config.json 渲染成根目录的可执行脚本。

模板用 {{key}} 占位符，例如 {{ports.astrbot}}、{{model.local.gguf}}。
所有端口、路径、名字都来自配置——用户改完 config.json 跑一次本脚本即可。

用法：python scripts/render.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, cfg, say  # noqa: E402

TEMPLATES = os.path.join(ROOT, "templates")

# 模板文件 -> 输出文件（相对项目根）
OUTPUTS = {
    "start-gateway.bat.template": "start-gateway.bat",
    "stop-gateway.bat.template": "stop-gateway.bat",
    "start-model.bat.template": "start-model.bat",
    "stop-model.bat.template": "stop-model.bat",
    "launcher.hta.template": "启动器.hta",
}


def render(text: str) -> str:
    import re

    def repl(match):
        key = match.group(1).strip()
        value = cfg(key, "")
        return str(value)

    return re.sub(r"\{\{([a-zA-Z0-9_.]+)\}\}", repl, text)


def main() -> int:
    for tpl_name, out_name in OUTPUTS.items():
        tpl = os.path.join(TEMPLATES, tpl_name)
        if not os.path.exists(tpl):
            say(f"[warn] 缺少模板 {tpl_name}")
            continue
        with open(tpl, encoding="utf-8") as f:
            text = f.read()
        rendered = render(text)
        out = os.path.join(ROOT, out_name)
        with open(out, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(rendered)
        say(f"[ok] {out_name}")
    say("[done] 脚本已按 config.json 渲染")
    return 0


if __name__ == "__main__":
    sys.exit(main())
