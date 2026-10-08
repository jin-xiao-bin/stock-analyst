"""桌面宠物 SSE 事件流"""
import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..services import event_bus

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/stream")
async def stream():
    """SSE：agent决策/熔断/观察触发等事件实时推流"""
    q = await event_bus.subscribe_queue()

    async def gen():
        try:
            # 先补发最近事件
            for ev in event_bus.recent_events():
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # 心跳防代理断连
        finally:
            event_bus.unsubscribe_queue(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
