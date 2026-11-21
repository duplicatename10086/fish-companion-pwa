#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 AstrBot dashboard 注入 PWA 外观（幂等，可反复执行）。

命名、主题色、头像全部来自 config.json 的 branding 段：
  - avatar              你自己的图片（png/jpg），自动生成 192/512/180 三尺寸
  - auto_transparent    是否把四角连通的白底抠成透明
  - maskable_scale      maskable 图标里图案缩放比例

用法：
  python scripts/branding.py                 # 自动探测 AstrBot 的 dist 目录
  python scripts/branding.py --dist <路径>   # 手动指定 dist 目录

AstrBot 升级会覆盖 dist，升级后重跑本脚本即可。
依赖：Pillow（pip install Pillow）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, cfg, resolve, say  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("需要 Pillow：pip install Pillow")


def find_dist(explicit: str | None) -> str:
    if explicit:
        return os.path.abspath(explicit)
    # 常见位置：项目内 venv / 相邻 astrbot 安装
    candidates = [
        resolve(cfg("astrbot.venv_python", "venv/Scripts/python.exe")),
    ]
    for cand in candidates:
        venv = os.path.dirname(os.path.dirname(cand))  # .../venv
        dist = os.path.join(venv, "Lib", "site-packages", "astrbot", "dashboard", "dist")
        if os.path.isdir(dist):
            return dist
    # 扫工作区里所有 astrbot dashboard dist
    for base in (os.path.dirname(ROOT), ROOT):
        for dirpath, dirnames, _ in os.walk(base):
            if dirpath.endswith(os.path.join("astrbot", "dashboard", "dist")):
                return dirpath
            # 别钻进太大的无关目录
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "backup")]
    raise SystemExit("没找到 AstrBot 的 dashboard/dist，请用 --dist 指定")


def build_icons(avatar: str, dist: str) -> None:
    name = str(cfg("branding.app_name", "Companion"))
    theme = str(cfg("branding.theme_color", "#1b2340"))
    transparent = bool(cfg("branding.auto_transparent", True))
    scale = float(cfg("branding.maskable_scale", 0.76))

    img = Image.open(avatar).convert("RGBA")
    w, h = img.size

    if transparent:
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            ImageDraw.floodfill(img, corner, (0, 0, 0, 0), thresh=45)
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)

    side = max(img.size)
    pad = int(side * 0.06)
    canvas = Image.new("RGBA", (side + pad * 2, side + pad * 2), (0, 0, 0, 0))
    canvas.paste(img, ((canvas.size[0] - img.size[0]) // 2, (canvas.size[1] - img.size[1]) // 2), img)

    icon_dir = os.path.join(dist, "icons")
    os.makedirs(icon_dir, exist_ok=True)
    for size, filename in ((512, "icon-512.png"), (192, "icon-192.png"), (180, "icon-180.png")):
        canvas.resize((size, size), Image.LANCZOS).save(os.path.join(icon_dir, filename))
        say(f"[ok] icon {filename}")

    base = Image.new("RGBA", (512, 512), theme)
    inner = canvas.resize((int(512 * scale), int(512 * scale)), Image.LANCZOS)
    base.paste(inner, ((512 - inner.size[0]) // 2, (512 - inner.size[1]) // 2), inner)
    base.convert("RGB").save(os.path.join(icon_dir, "icon-maskable-512.png"))
    say("[ok] icon icon-maskable-512.png")

    canvas.resize((32, 32), Image.LANCZOS).save(os.path.join(icon_dir, "favicon-32.png"))
    canvas.save(os.path.join(dist, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])
    say("[ok] favicon.ico")


def write_manifest_and_sw(dist: str) -> None:
    name = str(cfg("branding.app_name", "Companion"))
    theme = str(cfg("branding.theme_color", "#1b2340"))
    desc = str(cfg("character.description", "我的 AI 伴侣"))
    manifest = {
        "name": name,
        "short_name": name,
        "description": desc,
        "lang": "zh-CN",
        "start_url": "/chat",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": theme,
        "theme_color": theme,
        "icons": [
            {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    with open(os.path.join(dist, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    sw = (
        "// PWA service worker: 只用于让浏览器判定可安装，不缓存任何内容。\n"
        "self.addEventListener('install', function () { self.skipWaiting(); });\n"
        "self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });\n"
        "self.addEventListener('fetch', function () {});\n"
    )
    with open(os.path.join(dist, "sw.js"), "w", encoding="utf-8") as f:
        f.write(sw)
    say("[ok] manifest.json + sw.js")


def patch_index(dist: str) -> None:
    name = str(cfg("branding.app_name", "Companion")).replace("'", "\\'")
    theme = str(cfg("branding.theme_color", "#1b2340"))
    path = os.path.join(dist, "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()

    changed = []
    if "manifest.json" not in html:
        anchor = '    <link rel="icon" href="/favicon.svg" />\n'
        if anchor not in html:
            anchor = "<head>\n"
        head_tags = f"""    <link rel="icon" href="/favicon.ico" sizes="any" />
    <link rel="icon" href="/icons/icon-192.png" sizes="192x192" type="image/png" />
    <link rel="manifest" href="/manifest.json" />
    <meta name="theme-color" content="{theme}" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
    <meta name="apple-mobile-web-app-title" content="{name}" />
    <link rel="apple-touch-icon" href="/icons/icon-180.png" />
"""
        html = html.replace(anchor, anchor + head_tags, 1)
        changed.append("head tags")

    if "serviceWorker.register" not in html:
        script = f"""    <script>
      (function () {{
        function brand() {{ if (location.pathname.indexOf('/chat') === 0) {{ document.title = '{name}'; }} }}
        try {{
          brand();
          window.addEventListener('popstate', brand);
          var __t = document.querySelector('title');
          if (__t && window.MutationObserver) {{
            new MutationObserver(function () {{ if (document.title !== '{name}') {{ brand(); }} }}).observe(__t, {{ childList: true }});
          }}
        }} catch (e) {{}}
      }})();
      if ('serviceWorker' in navigator) {{
        window.addEventListener('load', function () {{
          navigator.serviceWorker.register('/sw.js', {{ scope: '/' }}).catch(function () {{}});
        }});
      }}
    </script>
"""
        html = html.replace("</body>", script + "  </body>", 1)
        changed.append("sw register")

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        say("[ok] index.html patched: " + ", ".join(changed))
    else:
        say("[skip] index.html 已经品牌化")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dist")
    args = p.parse_args()
    dist = find_dist(args.dist)
    avatar = resolve(str(cfg("branding.avatar", "")))
    if not avatar or not os.path.exists(avatar):
        raise SystemExit(f"头像文件不存在：{avatar}\n请在 config.json 的 branding.avatar 指向你的图片")
    say(f"[info] dist = {dist}")
    build_icons(avatar, dist)
    write_manifest_and_sw(dist)
    patch_index(dist)
    say("[done] PWA 品牌化完成；AstrBot 升级后重跑本脚本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
