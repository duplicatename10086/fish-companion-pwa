# 🐟 Fish Companion PWA

> 把大模型变成住在你电脑里的专属伴侣，手机 PWA 随时能聊。**本地优先、完全可定制、数据不出门。**

这是一套 Windows 上的部署套件：以 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 为网关，前端是一个可"添加到主屏幕"的 PWA（渐进式网页应用），大脑默认跑在你自己的显卡上（llama.cpp）。你将得到一个有名字、有性格、有头像的 AI 伴侣，电脑和手机都能聊。

它源自一位铲屎官给自家"蓝色大肥鱼"搭的系统，现在整理成任何人改一个配置文件就能用的通用项目。

---

## 它做了什么（七件套）

| 能力 | 说明 |
|---|---|
| 🛡️ 安全网 | 人格/配置内容寻址快照、AstrBot 整体备份、一键自检 |
| 🔗 事件桥 | 一条 HTTP 接口把外部消息注入聊天，并拿回回复 |
| 🖼️ 头像与称呼 | 头像、应用名、主题色、角色名全部可自定义 |
| 🧠 本地模型 | llama.cpp + GGUF，OpenAI 兼容接口，本地优先、可选云端兜底 |
| ⚙️ 工作模式 | 一条命令把伴侣"锁住"不聊天，适合专心干活时 |
| 🧩 三冲突解决 | 拦截流优先级、统一端口与鉴权、模型 ID 统一 + 原子操作 |
| 🚀 启动器 | 一个桌面小窗口管网关和模型的启停，状态一眼可见 |

可选附赠 [鱼的尾巴插件](optional/fish-tail-plugin/)：给回复缀上中文小括号的动作与神态描写。

---

## 架构

```
                  ┌─────────────────────────────┐
                  │  人格 + 记忆（唯一真源）      │
                  │  persona/人设.md + 记忆.md   │
                  └──────────────┬──────────────┘
                                 │ ctl.py set-persona 同步
                                 ▼
   电脑浏览器 ──┐        ┌──────────────────────┐
               ├───────▶│  AstrBot 网关  :6185  │◀──── 手机 PWA
   桌面启动器 ──┘        │  WebUI + OpenAPI     │
                        └──────────┬───────────┘
                                   │ 默认走本地
                                   ▼
                        ┌──────────────────────┐
                        │ llama.cpp  :8088      │
                        │ 你的 GGUF 模型         │
                        └──────────────────────┘
```

所有端口、路径、名字都在 `config.json` 里，可改。

---

## 快速开始

### 前置条件

- Windows 10/11
- Python 3.10+（装了 [Pillow](https://pypi.org/project/Pillow/)：`pip install Pillow`）
- 一个 AstrBot 运行环境（见 [docs/install.md](docs/install.md)）
- 本地模型可选：llama.cpp + 一个 GGUF 模型；也可以纯用云端

### 三步上手

```powershell
# 1. 初始化（会问你名字、头像、主题色、模型模式，并生成 config.json）
python setup.py

# 2. 设置 AstrBot 管理密码（本窗口有效）
$env:ASTRBOT_PWD = "你的AstrBot管理密码"

# 3. 按你的配置生成启动脚本 + 给聊天页做 PWA 品牌化
python scripts/render.py
python scripts/branding.py
```

然后双击根目录的 **`启动器.hta`**，点「开启网关」，再点「打开聊天页」就能聊了。

> 完整步骤、AstrBot 安装、人格同步、key 创建见 [docs/install.md](docs/install.md)。

---

## 个性化（重点）

一切都在 **`config.json`**（由 `config.example.json` 复制而来）：

| 想改什么 | 改哪里 |
|---|---|
| 角色名字 / 称呼你怎么称呼 | `character.name`、`character.call_user` |
| 手机 App 名字 | `branding.app_name` |
| **头像自己选** | `branding.avatar` 指向你的图片，重跑 `branding.py` |
| 主题色 | `branding.theme_color` |
| **模型自己挑** | `model.mode`（local/cloud）、`model.local.gguf`、`model.cloud.*` |
| 端口 | `ports.astrbot`、`ports.local_model` |
| 工作模式锁文案 | `workmode.lock_message` |
| 人设 / 记忆 | `persona/*.md`，改完跑 `ctl.py set-persona` |

改完配置后，凡是动过端口/路径/名字的，重跑一次 `python scripts/render.py` 让启动脚本生效。

AI 的**性格**不靠本套件的脚本决定，而是你写在 `persona/人设.md` 里的——想让它像谁、怎么说话、有什么边界，全由你写。

---

## 常用命令

```powershell
# 同步人设到 AstrBot（改了 persona/*.md 后必跑）
python scripts/ctl.py set-persona

# 创建 OpenAPI key（第一次用）
python scripts/ctl.py make-key

# 试聊一句
python scripts/ctl.py send "在吗"

# 看端口状态
python scripts/ctl.py status

# 自检
python scripts/selfcheck.py
```

---

## 手机 PWA

1. 手机连同一个 Wi-Fi，浏览器打开 `http://<电脑局域网IP>:<ports.astrbot>/chat`。
2. 登录 AstrBot 面板账号。
3. 菜单里「添加到主屏幕 / 安装应用」，名字和图标就是你在 `branding` 里设的。

> 局域网 http 下，安卓 Chrome 通常只能建快捷方式（不能成为真正 WebAPK，那需要 HTTPS）；iPhone 的 `apple-touch-icon` 直接生效。要公网访问可自行套 HTTPS/内网穿透，本套件不强制。

---

## 模型：本地优先，你说了算

- **local 模式**：llama.cpp 载 GGUF，`127.0.0.1:8088`，OpenAI 兼容。默认不配 fallback——本地挂了就明确报错，不偷偷切云端。
- **cloud 模式**：用 AstrBot 里配好的云端 provider。
- 想临时在聊天窗口切模型，用聊天页顶部的模型下拉（前端选择会覆盖后端默认值）。

显存占用取决于你的模型；8B Q4 大约 7GB。别在模型运行时开别的吃显存的活。

---

## 目录结构

```
fish-companion-pwa/
├── config.example.json        # 配置模板（复制成 config.json）
├── setup.py                   # 初始化向导
├── 启动器.hta                  # 桌面启动小窗口（render 生成）
├── start-gateway.bat / stop-gateway.bat
├── start-model.bat / stop-model.bat
├── launch-hidden.vbs          # 无黑窗转发
├── scripts/
│   ├── common.py              # 配置/路径/HTTP 公共模块
│   ├── ctl.py                 # 人设同步、key、试聊
│   ├── branding.py            # 头像/名字/主题色 → PWA
│   ├── selfcheck.py           # 六关自检
│   └── render.py              # 用 config 渲染启动脚本
├── templates/                 # 启动脚本模板（端口/路径占位符）
├── astrbot-plugin/            # 事件桥 + 工作模式插件（装进 AstrBot）
├── optional/fish-tail-plugin/ # 可选：鱼的尾巴插件（AstrBot + DSH）
├── examples/                  # 示例头像、人设模板
├── persona/                   # 你的角色人设/记忆（不入库）
├── secrets/                   # API key（不入库）
└── docs/                      # 详细文档
```

---

## 安全与隐私

- **数据留在本地**：本地模型模式下，对话不出你的电脑。
- **密钥不入仓库**：管理密码只从环境变量 `ASTRBOT_PWD` 读，API key 存在 `secrets/`（已被 `.gitignore` 排除）。
- **无个人资产**：仓库里没有真实记忆、头像原图、聊天记录、QQ 号。

---

## License

MIT —— 随便用、随便改、随便分发。[鱼的尾巴插件](optional/fish-tail-plugin/) 沿用其原 MIT 署名。

---

<3 愿你也有一条陪你睡觉的小鱼。
