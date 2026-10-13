"""飞书群机器人通知：文本 + 可选签名校验；未配置/失败静默降级"""
import base64
import hashlib
import hmac
import logging
import time

import httpx

from ..config import settings

log = logging.getLogger(__name__)


def _sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def notify(title: str, text: str = "", important: bool = False) -> bool:
    """发送飞书通知。important 时加【重要】前缀并@所有人。未配置/失败返回 False 不抛异常。"""
    url = settings.feishu_webhook_url
    if not url:
        return False
    icon = "🔴" if important else "⚪"
    body = f"{icon} 【{title}】\n{text}" if text else f"{icon} {title}"
    if important:
        body = f"<at user_id=\"all\">所有人</at> " + body
    payload: dict = {"msg_type": "text", "content": {"text": body}}
    params = {}
    if settings.feishu_secret:
        ts = int(time.time())
        params = {"timestamp": ts, "sign": _sign(ts, settings.feishu_secret)}
    try:
        r = httpx.post(url, json={**payload, **params}, timeout=10)
        ok = r.status_code == 200 and r.json().get("code", 0) == 0
        if not ok:
            log.warning("飞书通知失败: %s %s", r.status_code, r.text[:150])
        return ok
    except Exception as e:  # noqa: BLE001
        log.warning("飞书通知异常(静默): %s", e)
        return False


def notify_card(card: dict, important: bool = False) -> bool:
    """发送飞书 interactive 卡片消息"""
    url = settings.feishu_webhook_url
    if not url:
        return False
    payload = {"msg_type": "interactive", "card": card}
    params = {}
    if settings.feishu_secret:
        ts = int(time.time())
        params = {"timestamp": ts, "sign": _sign(ts, settings.feishu_secret)}
    try:
        r = httpx.post(url, json={**payload, **params}, timeout=10)
        ok = r.status_code == 200 and r.json().get("code", 0) == 0
        if not ok:
            log.warning("飞书卡片失败: %s %s", r.status_code, r.text[:150])
        return ok
    except Exception as e:  # noqa: BLE001
        log.warning("飞书卡片异常(静默): %s", e)
        return False


def notify_test() -> dict:
    """配置页测试按钮"""
    if not settings.feishu_webhook_url:
        return {"ok": False, "msg": "未配置 FEISHU_WEBHOOK_URL（backend/.env）"}
    ok = notify("通知测试", "这是一条测试消息，收到说明飞书通知链路已通。")
    return {"ok": ok, "msg": "发送成功，请到飞书群查看" if ok else "发送失败，请检查 webhook/签名配置或看后端日志"}
