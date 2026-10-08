"""FastAPI 入口 + 每日调度"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, stocks
from .db import SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _job_sync_tracked():
    from .services.market_sync import sync_all_tracked
    db = SessionLocal()
    try:
        sync_all_tracked(db)
    finally:
        db.close()


def _job_verify_watch_tasks():
    from .services.watch_tasks import verify_all
    db = SessionLocal()
    try:
        verify_all(db)
    except Exception as e:  # noqa: BLE001
        log.error("watch_task 核验失败: %s", e)
    finally:
        db.close()


def _job_run_strategies():
    from .services.live_runner import run_all_bindings
    db = SessionLocal()
    try:
        run_all_bindings(db)
    except Exception as e:  # noqa: BLE001
        log.error("挂机策略执行失败: %s", e)
    finally:
        db.close()


def _job_agent_intraday():
    """盘中巡逻：交易时段内按 patrol_freq 间隔触发"""
    import datetime as dt
    now = dt.datetime.now()
    if now.weekday() >= 5:
        return
    hm = now.hour * 60 + now.minute
    if not (9 * 60 + 35 <= hm <= 14 * 60 + 55):
        return
    try:
        from .services.agent.trader import run_pool
        results = run_pool("intraday")
        log.info("agent盘中巡逻完成: %s", results)
    except Exception as e:  # noqa: BLE001
        log.error("agent盘中巡逻失败: %s", e)


def _job_agent_daily():
    """收盘后全量深度决策 15:30 → 完成后推送每日摘要（普通级）"""
    try:
        from .services.agent.trader import run_pool
        results = run_pool("daily")
        log.info("agent收盘决策完成: %s", results)
        if results:
            from .services.notify import notify
            lines = []
            for r in results:
                if r.get("status") == "executed":
                    lines.append(f"{r['ts_code']} {r['action']} {r.get('qty', '')}股（执行）")
                elif r.get("status") == "rejected_by_risk":
                    lines.append(f"{r['ts_code']} {r['action']}（风控拒：{str(r.get('risk_note', ''))[:40]}）")
                elif r.get("error"):
                    lines.append(f"{r['ts_code']} 失败（{str(r['error'])[:40]}）")
                else:
                    lines.append(f"{r['ts_code']} {r.get('action', 'hold')}（{r.get('status', '')}）")
            notify("Agent 每日收盘决策摘要", "\n".join(lines))
    except Exception as e:  # noqa: BLE001
        log.error("agent收盘决策失败: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(_job_sync_tracked, "cron", hour=17, minute=10, id="daily_sync")
    # 可选模块：对应服务就绪后自动生效
    try:
        from .services.watch_tasks import verify_all  # noqa: F401
        scheduler.add_job(_job_verify_watch_tasks, "cron", hour=17, minute=30, id="watch_verify")
    except ImportError:
        log.info("watch_tasks 服务未就绪，跳过核验调度")
    try:
        from .services.live_runner import run_all_bindings  # noqa: F401
        scheduler.add_job(_job_run_strategies, "cron", hour=17, minute=45, id="strategy_run")
    except ImportError:
        log.info("live_runner 服务未就绪，跳过挂机调度")
    # 自主交易 agent：每5分钟检查（job内部判断交易时段+巡逻频率），15:30 全量
    try:
        from .services.agent.trader import run_pool  # noqa: F401
        scheduler.add_job(_job_agent_intraday, "cron", minute="*/5", id="agent_intraday")
        scheduler.add_job(_job_agent_daily, "cron", hour=15, minute=30, id="agent_daily")
        from .services.agent.learning import weekly_learning  # noqa: F401
        scheduler.add_job(lambda: weekly_learning(), "cron",
                          day_of_week="sun", hour=18, minute=0, id="agent_learning")
    except ImportError:
        log.info("agent trader 未就绪，跳过自主交易调度")
    # 飞书指令通道（长连接，后台线程）
    try:
        from .services.feishu_bot import start_ws_client
        start_ws_client()
    except Exception as e:  # noqa: BLE001
        log.warning("飞书指令通道启动失败: %s", e)
    # 启动补偿：错过的行情增量同步追补（后台线程，不阻塞启动）
    import threading

    def _catchup_sync():
        try:
            _job_sync_tracked()
        except Exception as e:  # noqa: BLE001
            log.warning("启动补偿同步失败: %s", e)

    threading.Thread(target=_catchup_sync, name="catchup-sync", daemon=True).start()
    scheduler.start()
    log.info("调度器已启动")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Stock Analyst", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(admin.router)

# 可选模块路由（子模块未完成时不阻塞启动）
for _mod, _attr in [
    ("app.api.replay", "router"),
    ("app.api.trades", "router"),
    ("app.api.analysis", "router"),
    ("app.api.watch_tasks", "router"),
    ("app.api.strategies", "router"),
    ("app.api.backtests", "router"),
    ("app.api.reviews", "router"),
    ("app.api.agent", "router"),
    ("app.api.events", "router"),
    ("app.api.pet", "router"),
]:
    try:
        import importlib
        _m = importlib.import_module(_mod)
        app.include_router(getattr(_m, _attr))
        log.info("已加载路由: %s", _mod)
    except Exception as e:  # noqa: BLE001
        log.warning("路由 %s 加载失败(可忽略): %s", _mod, e)


@app.get("/api/health")
def health():
    return {"status": "ok", "simulation_only": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8300, reload=True)
