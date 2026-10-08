"""进程内事件总线：业务点 publish（任意线程）→ SSE 客户端(桌面宠物)订阅"""
import asyncio
import logging
from collections import deque
from datetime import datetime

log = logging.getLogger(__name__)

_subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
_recent: deque = deque(maxlen=50)  # 新客户端连上时先补发最近事件


def publish(event_type: str, payload: dict, important: bool = False):
    """业务代码调用（任意线程安全）。投递到所有 SSE 订阅者。"""
    event = {
        "type": event_type,
        "important": important,
        "time": datetime.now().isoformat(timespec="seconds"),
        "payload": payload,
    }
    _recent.append(event)
    for loop, q in list(_subs):
        try:
            loop.call_soon_threadsafe(q.put_nowait, event)
        except RuntimeError:  # loop 已关闭
            _subs.discard((loop, q))


async def subscribe_queue() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subs.add((asyncio.get_running_loop(), q))
    return q


def unsubscribe_queue(q: asyncio.Queue):
    for pair in list(_subs):
        if pair[1] is q:
            _subs.discard(pair)


def recent_events() -> list:
    return list(_recent)
