"""客户端事件桥 + 工作模式（Work Mode）联动 —— v0.3.0（第8周期）。

一个插件，两条通道。所有外部调用都走 AstrBot 自己的 6185 端口，
鉴权统一用 AstrBot 的 API Key（Bearer abk_…，plugin 作用域），
不另开端口、不另设口令。

===========================================================================
一、事件流转的优先级（第8周期核心设计）
===========================================================================

AstrBot 流水线：唤醒检查 → 白名单 → 限流 → 内容安全 → 会话状态 → 插件 handler
→ 结果装饰 → 发送。插件 handler 按 `priority` 从大到小执行，只要某个 handler 调了
stop_event()，后面的 handler 和整个 LLM 阶段都不会执行。

本插件的排序：

  ┌ 优先级 1000  guard_work_mode   ← 本插件 · 第8周期新增
  │   · 只接 webchat（PWA）的消息
  │   · is_working_mode=True 时：回一句锁文案 → stop_event
  │   · 结果：其它插件（含"QQ空间事件注入"那类）、LLM、DSH 都看不到这条消息
  │
  ├ 优先级 0    其它插件的 handler（命令、表情包、梗百科……）
  │
  ├ ——         LLM 阶段（agent runner）
  │
  └ 兜底网     on_waiting_llm_request 钩子 ← 第7周期写的，保留
      · 兜住绕过 handler 阶段、直接进模型请求的路径（follow-up 捕获、内部重投）

「拦截流」和「注入流」的冲突就在这里解决：/inject 注入的事件同样走这条流水线，
所以它也先撞上 guard_work_mode；而且锁着时 /inject 直接在入口返回 423 + 锁文案，
根本不会产生一条"看起来像 QQ 消息"的事件去惊动别的插件。

===========================================================================
二、端点（全在 AstrBot 6185 上）
===========================================================================

统一前缀：/api/v1/plugins/extensions/astrbot_plugin_client_bridge/

  POST inject     注入一条客户端消息，等机器人回复
  POST lock       上锁      {"message": "……", "by": "dsh-workmode"}
  POST unlock     解锁
  POST workmode   上锁/解锁二合一 {"status": "locked"|"unlocked"}（第7周期老地址，保留）
  GET  state      读工作模式状态
  GET  health     统一健康检查（版本/运行时长/工作模式/桥接计数）

关于路径：AstrBot 4.29.4 把插件路由统一挂在 extensions/<插件名>/ 下，
`/api/bridge/lock` 这种根路径拿不到——那是 dashboard 自己的 /api/* 命名空间，
插件硬塞进去升级时会被打回原形。所以 lock/unlock/health 就是那组端点的等价实现，
只是前缀按框架规矩来（这条写进 README 了，别再改回去）。

===========================================================================
三、鉴权
===========================================================================

所有端点都要求 `Authorization: Bearer abk_…`，且 key 必须有 plugin 作用域。
这一层由 AstrBot 的 dashboard 中间件强制，插件自己不碰密码。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import time
import uuid

try:  # AstrBot 自带的 quart 兼容层
    from quart import jsonify, request
except Exception:  # pragma: no cover - 极端情况下退化成 flask 风格
    from flask import jsonify, request  # type: ignore

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import EventMessageType, PlatformAdapterType
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata

PLUGIN_NAME = "astrbot_plugin_client_bridge"
BASE = f"/{PLUGIN_NAME}"  # 注册用；dashboard 会统一加 extensions 前缀
ROUTE_INJECT = f"{BASE}/inject"
ROUTE_LOCK = f"{BASE}/lock"          # 第8周期新增
ROUTE_UNLOCK = f"{BASE}/unlock"      # 第8周期新增
ROUTE_STATE = f"{BASE}/state"        # 第8周期新增
ROUTE_HEALTH = f"{BASE}/health"      # 第8周期新增
ROUTE_WORKMODE = f"{BASE}/workmode"  # 第7周期，保留

# 只拦这些平台。PWA 走的是 AstrBot 的 webchat 适配器。
# 以后要顺便拦 QQ，把 "aiocqhttp" 加进来即可——但注意 QQ 群消息被拦会像掉线。
LOCKED_PLATFORMS = {"webchat"}

# 守卫优先级：数字越大越先跑。其它插件基本都在 0 附近，留 1000 的余量。
GUARD_PRIORITY = 1000

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PLUGIN_DIR, "config.json")


def _load_config() -> dict:
    """可选配置：把锁文案、默认用户名等个性化项放在插件目录的 config.json。"""
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            pass
    return {}


_PCFG = _load_config()
PLUGIN_AUTHOR = str(_PCFG.get("author", "Companion"))
DEFAULT_LOCK_MESSAGE = str(
    _PCFG.get("lock_message", "🐟 正在搬砖中，暂时不聊天～（误触请发送 /work_force_end 唤醒）")
)
DEFAULT_USER = str(_PCFG.get("default_user", "主人"))

STATE_FILE = os.path.join(_PLUGIN_DIR, "workmode_state.json")

# 借用 webchat 的平台身份：umo 形如 webchat:FriendMessage:webchat!<user>!<session>
PLATFORM_META = PlatformMetadata(
    name="webchat",
    description="客户端事件桥注入的消息",
    id="webchat",
)

_STARTED_AT = time.time()


class WorkModeState:
    """工作模式开关。刻意做得很小：一个布尔、一句话、一个时间戳。

    is_working_mode 是给外部（DSH、文档、以后接手的自己）看的名字，
    真正的状态存在 locked 上，两者永远一致。
    """

    def __init__(self) -> None:
        self.locked: bool = False
        self.message: str = ""
        self.locked_at: float = 0.0
        self.updated_by: str = ""
        # 第8周期：拦截计数，用来证明"锁真的生效了"，排障时也有据可查
        self.blocked_count: int = 0
        self.last_blocked_at: float = 0.0

    @property
    def is_working_mode(self) -> bool:
        return self.locked

    def load(self) -> None:
        """从磁盘恢复。文件坏了就当没锁——宁可放行聊天，也不要让人打不开。"""
        try:
            if not os.path.exists(STATE_FILE):
                return
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.locked = bool(data.get("locked", False))
            self.message = str(data.get("message") or "")
            self.locked_at = float(data.get("locked_at") or 0.0)
            self.updated_by = str(data.get("updated_by") or "")
            self.blocked_count = int(data.get("blocked_count") or 0)
            self.last_blocked_at = float(data.get("last_blocked_at") or 0.0)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[client_bridge] 工作模式状态读取失败，按未锁处理：{e}")

    def save(self) -> None:
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.as_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[client_bridge] 工作模式状态写入失败：{e}")

    def as_dict(self) -> dict:
        return {
            "locked": self.locked,
            "is_working_mode": self.locked,
            "message": self.message,
            "locked_at": self.locked_at,
            "locked_at_text": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.locked_at))
                if self.locked_at
                else ""
            ),
            "updated_by": self.updated_by,
            "platforms": sorted(LOCKED_PLATFORMS),
            "blocked_count": self.blocked_count,
            "last_blocked_at": self.last_blocked_at,
        }

    def apply(self, status: str, message: str, by: str) -> None:
        if status == "locked":
            # 重复加锁保留最早的 locked_at，方便算"已经工作多久了"
            if not self.locked:
                self.locked_at = time.time()
                self.blocked_count = 0
            self.locked = True
            self.message = message or DEFAULT_LOCK_MESSAGE
        else:
            self.locked = False
            self.message = ""
            self.locked_at = 0.0
        self.updated_by = by
        self.save()

    def note_blocked(self) -> None:
        self.blocked_count += 1
        self.last_blocked_at = time.time()
        # 故意不落盘：拦截是高频路径，等下一次状态变更一起写就行

    def reply_text(self) -> str:
        return self.message or DEFAULT_LOCK_MESSAGE


# 模块级单例：hook、guard、web api 共用同一个对象
WORK = WorkModeState()


def is_working_mode() -> bool:
    """给外部脚本 / 别的插件用的小函数（文档里也直接引用这个名字）。"""
    return WORK.is_working_mode


class ClientBridgeEvent(AstrMessageEvent):
    """把 send() 拦下来丢进队列，而不是真的发给某个平台。"""

    def __init__(self, *args, reply_queue: asyncio.Queue, **kwargs):
        super().__init__(*args, **kwargs)
        self._reply_queue: asyncio.Queue = reply_queue

    async def send(self, message: MessageChain) -> None:
        self._has_send_oper = True
        logger.info(f"[client_bridge] send() 拦截到回复：{_chain_to_text(message)!r}")
        await self._reply_queue.put(message)

    async def send_streaming(self, generator, use_fallback: bool = False) -> None:
        async for chain in generator:
            await self.send(chain)


def _decode_images(items: list[str]) -> tuple[list[Image], list[str]]:
    """把 base64 / 本地路径变成 Image 组件，返回 (组件, 临时文件)。"""
    components: list[Image] = []
    temps: list[str] = []
    for item in items or []:
        if not isinstance(item, str) or not item:
            continue
        try:
            if item.startswith("data:") and ";base64," in item:
                item = item.split(";base64,", 1)[1]
            if os.path.exists(item):
                components.append(Image(file=item))
                continue
            raw = base64.b64decode(item, validate=False)
            fd, path = tempfile.mkstemp(suffix=".png", prefix="client_bridge_")
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            temps.append(path)
            components.append(Image(file=path))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[client_bridge] 图片解析失败：{e}")
    return components, temps


def _chain_to_text(chain: MessageChain) -> str:
    parts: list[str] = []
    for comp in chain.chain:
        if isinstance(comp, Plain):
            parts.append(comp.text)
        elif isinstance(comp, Image):
            parts.append("[图片]")
    return "".join(parts).strip()


def _ok(data: dict | None = None):
    return jsonify({"status": "ok", "data": data or {}})


def _err(message: str, code: str = "error", http: int | None = None):
    resp = jsonify({"status": "error", "code": code, "message": message})
    if http is not None:
        try:
            resp.status_code = http
        except Exception:  # noqa: BLE001
            pass
    return resp


@register(PLUGIN_NAME, PLUGIN_AUTHOR, "客户端事件桥 + 工作模式联动", "0.3.1")
class ClientBridgePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.context = context
        WORK.load()
        # 第8周期：注入计数，health 里能看到"到底被调用过没有"
        self.inject_count = 0
        self.last_inject_at = 0.0

        self.context.register_web_api(
            ROUTE_INJECT, self._api_inject, ["POST"],
            "把一条客户端消息注入 AstrBot 事件队列（模拟 QQ/webchat 消息）",
        )
        self.context.register_web_api(
            ROUTE_LOCK, self._api_lock, ["POST"],
            "工作模式上锁：PWA 消息不再进模型，直接回锁文案",
        )
        self.context.register_web_api(
            ROUTE_UNLOCK, self._api_unlock, ["POST"],
            "工作模式解锁",
        )
        self.context.register_web_api(
            ROUTE_WORKMODE, self._api_workmode, ["POST", "GET"],
            "工作模式开关（locked/unlocked 二合一，第7周期老地址，保留）",
        )
        self.context.register_web_api(
            ROUTE_STATE, self._api_state, ["GET"],
            "读工作模式状态",
        )
        self.context.register_web_api(
            ROUTE_HEALTH, self._api_health, ["GET"],
            "统一健康检查：版本/运行时长/工作模式/桥接计数",
        )
        logger.info(
            f"[client_bridge] v0.3.0 ready；workmode={'locked' if WORK.locked else 'unlocked'}；"
            f"guard_priority={GUARD_PRIORITY}；platforms={sorted(LOCKED_PLATFORMS)}"
        )

    # ==================================================================
    # 优先级 1000：最前置拦截（第8周期新增）
    # ==================================================================
    @filter.platform_adapter_type(PlatformAdapterType.WEBCHAT)
    @filter.event_message_type(EventMessageType.ALL, priority=GUARD_PRIORITY)
    async def guard_work_mode(self, event: AstrMessageEvent):
        """工作模式守卫：锁着时，PWA 的消息在这里就结束，不再往下传。

        为什么用 handler 而不是只在 LLM 钩子里拦：
          * handler 阶段 stop_event() 会让 star_request 直接 break，
            后面注册的所有插件 handler（包括"QQ空间事件注入"那类）都跑不到；
          * LLM 阶段更不会被调用，所以 DSH 那边根本收不到请求。

        为什么还要加平台过滤：
          * handler 一旦被激活，唤醒检查阶段就会把这条消息标成"已唤醒"。
            要是它接住所有平台，QQ 群里没 @ 机器人的话也会被唤醒，就乱套了。
          * 所以只接 webchat（PWA）——PWA 的每条消息本来就该被回复。
        """
        # 没锁：原样放行，什么都不做
        if not WORK.locked:
            return
        platform = (event.get_platform_name() or "").lower()
        if platform not in LOCKED_PLATFORMS:
            return

        WORK.note_blocked()
        logger.info(
            f"[client_bridge] guard 拦截 platform={platform} umo={event.unified_msg_origin} "
            f"count={WORK.blocked_count}"
        )
        await self._send_blocked_reply(event, WORK.reply_text())
        event.stop_event()

    async def _send_blocked_reply(self, event: AstrMessageEvent, text: str) -> None:
        """把锁文案送到具体平台。

        stop_event() 之后流水线不会替我们发结果，所以必须自己发。
        webchat 还要补一个"本轮结束"，否则输入框一直转圈。
        """
        try:
            await event.send(MessageChain([Plain(text)]))
            if getattr(event, "platform_meta", None) and event.platform_meta.name in LOCKED_PLATFORMS:
                try:
                    await event.send(None)  # type: ignore[arg-type]
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[client_bridge] 锁文案发送失败：{e}")

    # ==================================================================
    # 兜底网：LLM 请求前（第7周期写的，保留）
    # ==================================================================
    @filter.on_waiting_llm_request()
    async def on_waiting_llm_request(self, event: AstrMessageEvent):
        """兜住绕过 handler 阶段、直接进模型请求的路径（follow-up、内部重投等）。

        正常情况下 guard_work_mode 已经拦掉了；走到这里说明那条路径没经过 handler
        阶段——这正是第7周期踩过的坑，所以两道网都留着，成本只有一次布尔判断。
        """
        if not WORK.locked:
            return
        platform = (event.get_platform_name() or "").lower()
        if platform not in LOCKED_PLATFORMS:
            return

        WORK.note_blocked()
        logger.info(f"[client_bridge] waiting-llm 兜底拦截 umo={event.unified_msg_origin}")
        await self._send_blocked_reply(event, WORK.reply_text())
        event.stop_event()

    # ==================================================================
    # 工作模式端点
    # ==================================================================
    async def _read_body(self) -> dict:
        try:
            payload = await request.get_json(force=True, silent=True)
            return payload if isinstance(payload, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    async def _set_mode(self, status: str, payload: dict):
        WORK.apply(
            status=status,
            message=str(payload.get("message") or "")[:500],
            by=str(payload.get("by") or "dsh-workmode")[:120],
        )
        logger.info(
            f"[client_bridge] 工作模式 -> {status}（by={WORK.updated_by}, "
            f"message={WORK.message!r}）"
        )
        return _ok(WORK.as_dict())

    async def _api_lock(self):
        return await self._set_mode("locked", await self._read_body())

    async def _api_unlock(self):
        return await self._set_mode("unlocked", await self._read_body())

    async def _api_workmode(self):
        method = (getattr(request, "method", "POST") or "POST").upper()
        if method == "GET":
            return _ok(WORK.as_dict())
        payload = await self._read_body()
        status = str(payload.get("status") or "").strip().lower()
        if payload.get("locked") is True:
            status = "locked"
        elif payload.get("locked") is False:
            status = "unlocked"
        if status not in ("locked", "unlocked"):
            return _err('status 只能是 "locked" 或 "unlocked"', code="bad-request")
        return await self._set_mode(status, payload)

    async def _api_state(self):
        return _ok(WORK.as_dict())

    async def _api_health(self):
        """统一健康检查：一条请求回答"这套东西还活着吗"。

        刻意不查数据库、不试模型——那是自检脚本的活。这里要快（<50ms），
        所以只读内存里的状态。
        """
        persona_id = ""
        try:
            cfg = self.context.get_config()
            persona_id = str(
                ((cfg.get("agent_runner") or {}).get("config") or {})
                .get("persona", {})
                .get("persona_id")
                or ""
            )
        except Exception:  # noqa: BLE001
            pass
        return _ok(
            {
                "plugin": PLUGIN_NAME,
                "version": "0.3.0",
                "uptime_s": int(time.time() - _STARTED_AT),
                "workmode": WORK.as_dict(),
                "bridge": {
                    "inject_count": self.inject_count,
                    "last_inject_at": self.last_inject_at,
                },
                "persona_id": persona_id,
                "platforms_locked": sorted(LOCKED_PLATFORMS),
                "guard_priority": GUARD_PRIORITY,
            }
        )

    # ==================================================================
    # 事件桥
    # ==================================================================
    async def _api_inject(self):
        payload = await self._read_body()

        # 第8周期：锁着时注入直接拒掉。
        # 注入流也走同一条流水线，与其让它排队被 guard 拦一次、客户端干等超时，
        # 不如在入口就说清楚"现在是工作模式"。
        if WORK.locked:
            logger.info("[client_bridge] inject 被工作模式拒绝")
            return _err(WORK.reply_text(), code="working-mode", http=423)

        text = str(payload.get("text") or "").strip()
        if not text and not payload.get("images"):
            return _err("text 不能为空", code="bad-request")

        user = str(payload.get("user") or DEFAULT_USER)[:64]
        session = str(payload.get("session") or "default")[:64]
        wait = bool(payload.get("wait", True))
        timeout = float(payload.get("timeout") or 120)

        images, temps = _decode_images(payload.get("images") or [])

        abm = AstrBotMessage()
        abm.type = MessageType.FRIEND_MESSAGE
        abm.self_id = "client_bridge"
        abm.session_id = f"webchat!{user}!{session}"
        abm.message_id = uuid.uuid4().hex
        abm.sender = MessageMember(user_id=user, nickname=user)
        abm.message = ([Plain(text)] if text else []) + images
        abm.message_str = text or "[图片]"
        abm.raw_message = payload
        abm.timestamp = int(time.time())

        reply_queue: asyncio.Queue = asyncio.Queue()
        event = ClientBridgeEvent(
            message_str=abm.message_str,
            message_obj=abm,
            platform_meta=PLATFORM_META,
            session_id=abm.session_id,
            reply_queue=reply_queue,
        )
        event.set_extra("client_bridge", True)
        event.set_extra("client_bridge_raw", payload)

        started = time.time()
        self.inject_count += 1
        self.last_inject_at = int(started)
        try:
            await self.context.get_event_queue().put(event)
        except Exception as e:  # noqa: BLE001
            logger.exception("[client_bridge] 入队失败")
            return _err(f"入队失败：{e}", code="enqueue-failed")

        if not wait:
            return _ok({"accepted": True, "session_id": abm.session_id})

        # 收集回复：有内容之后静默 0.6s 就算说完；没内容就一直等到 deadline。
        # 不能把"空 chain"当结束信号——流水线在回复前会发几帧空链。
        reply_parts: list[str] = []
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            quiet = 0.6 if reply_parts else remaining
            try:
                chain = await asyncio.wait_for(reply_queue.get(), timeout=min(remaining, quiet))
            except asyncio.TimeoutError:
                if reply_parts:
                    break
                continue
            if chain is None:
                if reply_parts:
                    break
                continue
            text_out = _chain_to_text(chain)
            if text_out:
                reply_parts.append(text_out)

        if not reply_parts:
            return _err(
                f"{timeout:.0f}s 内没有等到回复（可能被插件拦下或模型超时）",
                code="no-reply",
            )

        for path in temps:
            try:
                os.remove(path)
            except OSError:
                pass

        reply = "\n".join(part for part in reply_parts if part).strip()
        return _ok(
            {
                "reply": reply,
                "session_id": abm.session_id,
                "took_ms": int((time.time() - started) * 1000),
            }
        )

    async def terminate(self):
        logger.info("[client_bridge] terminated")
