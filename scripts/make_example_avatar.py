#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯代码画一张示例头像（蓝色小鱼），零版权风险。

只是给 examples/ 放一张占位图，让用户第一次跑 branding.py 能成功。
用户应该换成自己的图片。依赖 Pillow。
"""
import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "examples", "avatar", "default-avatar.png")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 身体（椭圆）
d.ellipse([90, 150, 400, 380], fill=(87, 143, 235, 255), outline=(40, 80, 160, 255), width=6)
# 尾巴（三角）
d.polygon([(390, 265), (470, 190), (470, 340)], fill=(70, 120, 210, 255), outline=(40, 80, 160, 255))
d.line([(390, 265), (470, 190)], fill=(40, 80, 160, 255), width=6)
d.line([(390, 265), (470, 340)], fill=(40, 80, 160, 255), width=6)
# 背鳍
d.polygon([(200, 160), (250, 90), (300, 160)], fill=(70, 120, 210, 255), outline=(40, 80, 160, 255))
# 眼睛
d.ellipse([160, 220, 195, 255], fill=(255, 255, 255, 255))
d.ellipse([170, 230, 187, 247], fill=(20, 30, 60, 255))
d.ellipse([174, 233, 179, 238], fill=(255, 255, 255, 255))
# 嘴
d.arc([195, 270, 240, 310], start=15, end=120, fill=(20, 30, 60, 255), width=5)
# 腮红
d.ellipse([205, 275, 235, 295], fill=(240, 140, 150, 120))

img.save(OUT)
print("wrote", OUT)
