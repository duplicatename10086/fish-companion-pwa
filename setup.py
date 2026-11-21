#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化向导：把模板变成你自己的配置。

做四件事：
  1. 复制 config.example.json -> config.json（已有则不覆盖）
  2. 交互式问你几个个性化问题（名字 / 头像 / 主题色 / 模型模式）
  3. 复制示例人设到 persona/（已有则不覆盖）
  4. 提示你设置管理密码环境变量 ASTRBOT_PWD

无交互：python setup.py --defaults   （全部用示例值，之后自己改 config.json）
"""
from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(ROOT, "config.example.json")
CONFIG = os.path.join(ROOT, "config.json")


def ask(prompt: str, default: str) -> str:
    try:
        value = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        value = ""
    return value or default


def main() -> int:
    interactive = "--defaults" not in sys.argv

    if not os.path.exists(CONFIG):
        shutil.copy2(EXAMPLE, CONFIG)
        print("[ok] 已生成 config.json")
    else:
        print("[skip] config.json 已存在，不覆盖")

    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)

    if interactive:
        print("\n--- 个性化设置（直接回车用默认值）---")
        name = ask("你的 AI 伴侣叫什么", cfg["character"]["name"])
        call = ask("它怎么称呼你", cfg["character"]["call_user"])
        app = ask("手机 PWA 应用名", cfg["branding"]["app_name"])
        theme = ask("主题色（十六进制）", cfg["branding"]["theme_color"])
        avatar = ask("头像图片路径", cfg["branding"]["avatar"])
        mode = ask("模型模式 local / cloud", cfg["model"]["mode"])

        cfg["character"]["name"] = name
        cfg["character"]["persona_id"] = name
        cfg["character"]["call_user"] = call
        cfg["branding"]["app_name"] = app
        cfg["branding"]["theme_color"] = theme
        cfg["branding"]["avatar"] = avatar
        cfg["model"]["mode"] = mode
        if mode == "cloud":
            cfg["model"]["fallback"] = ask("本地挂了是否切云端 yes/no", "no").lower().startswith("y")

        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print("[ok] 个性化设置已写入 config.json")

    # 人设模板：渲染 {{character.*}} 占位符
    persona_dir = os.path.join(ROOT, "persona")
    os.makedirs(persona_dir, exist_ok=True)
    import re

    def fill(text: str) -> str:
        def repl(m):
            key = m.group(1).strip()
            cur = cfg
            for part in key.split("."):
                cur = cur.get(part, "") if isinstance(cur, dict) else ""
            return str(cur)
        return re.sub(r"\{\{(character\.[a-zA-Z0-9_.]+)\}\}", repl, text)

    cfg = json.load(open(CONFIG, encoding="utf-8"))
    for src_name, dst_name in (("人设.md", "人设.md"), ("记忆.md", "记忆.md")):
        src = os.path.join(ROOT, "examples", "persona", src_name)
        dst = os.path.join(persona_dir, dst_name)
        if os.path.exists(src) and not os.path.exists(dst):
            with open(src, encoding="utf-8") as f:
                text = f.read()
            with open(dst, "w", encoding="utf-8") as f:
                f.write(fill(text))
            print(f"[ok] 已生成示例人设 persona/{dst_name}（记得改成你自己的）")

    # 密钥目录
    os.makedirs(os.path.join(ROOT, "secrets"), exist_ok=True)

    env_name = cfg.get("astrbot", {}).get("admin_password_env", "ASTRBOT_PWD")
    print(f"""
--- 还差一步：设置 AstrBot 管理密码 ---
在 PowerShell 里执行（只在当前窗口有效）：
    $env:{env_name} = "你的AstrBot管理密码"

要永久生效：
    [Environment]::SetEnvironmentVariable("{env_name}", "你的密码", "User")

然后运行自检：
    python scripts/selfcheck.py --no-chat
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
