"""观察任务核验：price_level 比对最新日线；event 用博查+LLM 判定；过期置 expired"""
import datetime as dt
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DailyPrice, WatchTask
from ..services import news_source
from ..services.deepseek_client import client as ds_client

log = logging.getLogger(__name__)


def _latest_bars(db: Session, ts_code: str, limit: int = 5):
    return db.scalars(
        select(DailyPrice).where(DailyPrice.ts_code == ts_code)
        .order_by(DailyPrice.trade_date.desc()).limit(limit)
    ).all()


def _verify_price_level(db: Session, task: WatchTask, bars) -> str | None:
    """返回触发详情字符串；未触发返回 None"""
    if not bars:
        return None
    cond = task.condition_json or {}
    kind = cond.get("kind")
    value = cond.get("value")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    bar = bars[0]  # 最新一根日线
    date_str = bar.trade_date.isoformat()
    if kind == "price_below" and float(bar.low) <= value:
        return f"{date_str} 最低价 {bar.low} 已跌破观察价 {value}"
    if kind == "price_above" and float(bar.high) >= value:
        return f"{date_str} 最高价 {bar.high} 已上穿观察价 {value}"
    return None


def _verify_event(db: Session, task: WatchTask) -> str | None:
    """双通道搜索事件关键词(博查→东财) → deepseek-chat 判定是否已发生"""
    cond = task.condition_json or {}
    desc = cond.get("desc") or (task.expect_json or {}).get("expect") or ""
    if not desc:
        return None
    news = news_source.verify_search(f"{task.ts_code} {desc}", count=8)
    if not news:
        return None
    news_text = "\n".join(f"- [{n.get('date', '')[:10]}] {n['title']}：{n['snippet']}" for n in news)
    today = dt.date.today().isoformat()
    prompt = (
        "你是事件核查助手。根据以下新闻搜索结果判断指定事件是否已经发生。\n"
        f"观察事件：{task.ts_code} —— {desc}\n"
        f"观察任务创建于 {task.created_at.date() if task.created_at else today}，今日 {today}。\n"
        f"新闻搜索结果：\n{news_text}\n\n"
        '只输出一个 json：{"happened": true/false, "detail": "一句话依据"}'
    )
    try:
        raw = ds_client.chat(
            [{"role": "system", "content": "你只输出合法 JSON，不输出其他内容。"},
             {"role": "user", "content": prompt}],
            model=settings.chat_model, temperature=0.1, max_tokens=500,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        data = json.loads(raw)
        if data.get("happened"):
            return str(data.get("detail") or f"事件已发生: {desc}")[:250]
    except Exception as e:  # noqa: BLE001
        log.warning("事件任务 %s LLM 判定失败(跳过): %s", task.id, e)
    return None


def verify_all(db: Session) -> dict:
    """遍历 waiting 任务核验：触发→triggered；过期→expired。返回统计"""
    stats = {"checked": 0, "triggered": 0, "expired": 0, "errors": 0}
    tasks = db.scalars(
        select(WatchTask).where(WatchTask.status == "waiting")
    ).all()
    today = dt.date.today()
    bars_cache: dict[str, list] = {}
    try:
        for task in tasks:
            stats["checked"] += 1
            # 过期
            if task.expire_date is not None and task.expire_date < today:
                task.status = "expired"
                stats["expired"] += 1
                continue
            try:
                if task.task_type == "price_level":
                    if task.ts_code not in bars_cache:
                        bars_cache[task.ts_code] = _latest_bars(db, task.ts_code)
                    detail = _verify_price_level(db, task, bars_cache[task.ts_code])
                elif task.task_type == "event":
                    detail = _verify_event(db, task)
                else:
                    continue  # indicator 类 M5 暂不支持，跳过
                if detail:
                    task.status = "triggered"
                    task.trigger_date = today
                    task.trigger_detail = detail[:250]
                    stats["triggered"] += 1
                    # 🔴 重要通知：观察任务触发（飞书 + 桌面事件总线）
                    from ..services.notify import notify
                    from ..services import event_bus
                    event_bus.publish("watch_triggered",
                                      {"ts_code": task.ts_code, "detail": detail[:150]},
                                      important=True)
                    notify(f"观察任务触发 {task.ts_code}",
                           f"{detail[:150]}", important=True)
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                log.warning("任务 %s 核验失败(跳过): %s", task.id, e)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    log.info("watch_task 核验完成: %s", stats)
    return stats
