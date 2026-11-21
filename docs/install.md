# 安装与环境准备

本套件的本体是 [AstrBot](https://github.com/AstrBotDevs/AstrBot)。本文件讲怎么把 AstrBot 准备好，再套上本套件。所有路径/端口都能在 `config.json` 改。

## 1. 准备 AstrBot

1. 装 Python 3.10+。
2. 建一个工作目录，例如 `companion/`，最终结构大致是：
   ```
   companion/
   ├── venv/            # Python 虚拟环境
   ├── astrbot-data/    # AstrBot 数据目录
   └── fish-companion-pwa/   # 本套件（本仓库）
   ```
3. 建虚拟环境并装 AstrBot（以 AstrBot 官方说明为准，例如）：
   ```powershell
   python -m venv venv
   .\venv\Scripts\pip install astrbot
   ```
4. 在 `config.json` 的 `astrbot` 段填好：
   - `venv_python` → `venv/Scripts/python.exe`
   - `venv_astrbot` → `venv/Scripts/astrbot.exe`
   - `data_dir` → `astrbot-data`
5. 首次启动 AstrBot 时按提示设好管理账号密码。把密码放进环境变量 `ASTRBOT_PWD`（脚本只从这里读，绝不写进文件）。

> **完整性级别坑**：在 Windows 上要从普通权限的桌面启动器启动 AstrBot。如果从"低完整性"的终端（比如某些 AI 客户端的内置终端）拉起，它可能写不动早期用普通权限建的文件，日志出现 `attempt to write a readonly database`。本套件的 `启动器.hta` 就是普通权限启动的。

## 2. 本地模型（可选）

如果 `model.mode = local`：

1. 下载 [llama.cpp](https://github.com/ggml-org/llama.cpp) 的 Windows CUDA 构建，放 `llama-server.exe`。
2. 下载一个 GGUF 模型（例如 Qwen3-8B-Q4_K_M）。
3. 在 `config.json` 的 `model.local` 填好：
   - `llama_server`、`gguf`、`log` 的路径
   - `aliases`：模型 ID 别名
   - `extra_flags`：Qwen3 用 `--jinja -rea off`（关思考），别的模型可改
   - `context`、`ngl`、`port`
4. 显存：8B Q4 约 7GB。显存不够就换更小的模型或调低 `context`。

> llama-server 默认只监听 `127.0.0.1`，不要改成 `0.0.0.0` 暴露到公网。

如果 `model.mode = cloud`，跳过本节，直接在 AstrBot 面板配好云端 provider，并填 `model.cloud.*`。

## 3. 初始化本套件

```powershell
cd fish-companion-pwa
pip install Pillow
python setup.py
$env:ASTRBOT_PWD = "你的AstrBot管理密码"
python scripts/render.py
```

`setup.py` 会：生成 `config.json`、问你个性化设置、把示例人设复制到 `persona/`。

`render.py` 会把 `templates/` 里的启动脚本按配置渲染成根目录的 `start-gateway.bat` 等文件。**改了端口/路径后要重跑。**

## 4. 起服务

双击根目录 `启动器.hta`：
- 点「开启网关」：如果是 local 模式，会先拉起本地模型、等它监听，再起 AstrBot。
- 点「打开聊天页」：浏览器打开 `http://127.0.0.1:<ports.astrbot>/chat`。

## 5. 同步人格 + 建 key

```powershell
# 先把 persona/人设.md 和 记忆.md 改成你要的角色
python scripts/ctl.py set-persona
python scripts/ctl.py make-key
python scripts/ctl.py send "在吗"
python scripts/selfcheck.py
```

- `set-persona` 会把人设+记忆写进 AstrBot 名为 `character.persona_id` 的人格，并同步到 `default`。
  - 注意：人格名**不要**用 `default`——AstrBot 的 webchat 会丢弃系统默认人格，换成内置通用提示词。用一个真实名字。
- `make-key` 生成 OpenAPI key，存到 `secrets/apikey.txt`。

## 6. 手机 PWA

1. 查电脑局域网 IP（如 `ipconfig` 看 IPv4）。
2. 手机同 Wi-Fi 打开 `http://<电脑IP>:<ports.astrbot>/chat`，登录。
3. 浏览器菜单「添加到主屏幕 / 安装应用」。

改名/换头像后重跑：
```powershell
python scripts/branding.py
```
它会重新生成图标、`manifest.json`、`sw.js`，并给 `index.html` 注入品牌标签。AstrBot 升级覆盖了 dashboard 的 `dist` 后也要重跑；找不到目录时用 `python scripts/branding.py --dist <dist路径>` 指定。

## 7. 可选插件

### 事件桥 + 工作模式（已随仓库提供）

把 `astrbot-plugin/astrbot_plugin_client_bridge/` 整个目录拷进 `<astrbot-data>/data/plugins/`，重启 AstrBot。锁文案/默认用户名可改插件目录里的 `config.json`。

工作模式通过外部（如 DSH 插件）调用桥接的 `/workmode` 端点开关。本套件只提供 AstrBot 侧；DSH 侧的工作模式插件可按你自己的客户端实现。

### 鱼的尾巴

见 [optional/fish-tail-plugin/README.md](../optional/fish-tail-plugin/README.md)。它给回复缀上小括号动作描写，支持 AstrBot 和 DSH。

## 8. 备份与恢复

`ctl.py` 之外，AstrBot 面板自带"备份/导入"。本套件的人设在 `persona/`、配置在 `config.json`、key 在 `secrets/`——把这三个目录备份好就能迁移。

## 常见问题

- **PWA 报 context 超限**（`request exceeds the available context size`）：会话历史太长了，AstrBot 聊天页「创建对话」开新对话即可。不要一味加大 `-c`，显存不够。
- **模型切换不生效**：AstrBot webchat 每条消息带 `selected_provider`，前端下拉框选过的值会覆盖后端默认值。想固定本地，就别动下拉框；或清掉浏览器里存的选择。
- **启动器闪黑窗**：`launch-hidden.vbs` 就是为解决这个；bat/vbs 保持 CRLF + ASCII 注释，cmd 才不会串行。
