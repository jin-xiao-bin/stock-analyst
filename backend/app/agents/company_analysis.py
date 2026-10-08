"""公司分析 Agent：数据收集 → 数据建模(核验) → 3 子agent并行 → 首席汇总 → 落库 + 观察任务 + Milvus
分析过程临时文件写入 tmp/analysis/，流程结束自动清理。"""
import datetime as dt
import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import AnalysisReport, DailyPrice, FinancialSnapshot, ReportChain, StockBasic, WatchTask
from ..services import milvus_store
from ..services.bocha_search import web_search
from ..services.deepseek_client import client as ds_client

log = logging.getLogger(__name__)

JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


def _workdir(ts_code: str) -> Path:
    """分析临时工作目录（项目内 tmp/analysis/，流程结束统一清理）。
    注意：不用 tempfile.mkdtemp（其目录 ACL 在部分环境下拒写），用时间戳 mkdir。"""
    base = Path(__file__).resolve().parents[2] / "tmp" / "analysis"
    base.mkdir(parents=True, exist_ok=True)
    d = base / f"{ts_code.replace('.', '_')}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    d.mkdir(parents=True)
    return d


def _cleanup_workdir(d: Path | None):
    if d and d.exists():
        shutil.rmtree(d, ignore_errors=True)
        log.info("已清理分析临时目录 %s", d)

SUB_AGENTS = {
    "technical": {
        "title": "技术面分析",
        "system": "你是资深技术分析师，精通K线形态、均线系统、MACD/RSI/布林带、量价关系、支撑阻力位。基于给定的日线数据输出专业 markdown 分析，包括趋势判断、关键支撑/阻力位（给出具体价格）、量价特征与操作提示。不要编造数据里没有的指标数值。",
    },
    "fundamental": {
        "title": "基本面分析",
        "system": "你是资深基本面分析师，精通财务报表分析、行业景气度、公司竞争力评估。基于给定的财务快照与公司信息输出 markdown 分析：盈利能力、成长性、财务健康度、估值观点。数据缺失时明确说明，不要编造数字。",
    },
    "sentiment": {
        "title": "舆情分析",
        "system": "你是资深舆情分析师。基于给定的新闻搜索结果输出 markdown 分析：近期消息面利好/利空梳理、市场情绪判断、需要持续关注的事件。没有新闻时说明消息面平静，不要编造新闻。",
    },
}

MODELING_SYSTEM = (
    "你是资深基本面研究员。请基于公司最新财报、公告和可核验的公开资料完成业绩分析。"
    "分别拆解收入、利润、现金流、业务结构和关键经营指标，明确区分【公司披露】、【分析假设】和【你的判断】。"
    "更新盈利预测与估值模型，检查三表勾稽、公式引用和口径一致性。"
    "最终交付一份适用资深交易员进行股票分析的数据模型，并列出关键风险与未验证信息。\n\n"
    "输出格式：先输出完整 markdown 数据模型文档（含收入拆解/利润/现金流/业务结构/关键经营指标/"
    "盈利预测与估值/三表勾稽检查/公司披露vs假设vs判断对照/关键风险/未验证信息清单），"
    "然后在文档末尾输出一个 ```json 代码块：\n"
    "```json\n"
    '{"data_model": {'
    '"sections_present": ["收入","利润","现金流","业务结构","经营指标","盈利预测","估值","勾稽检查"], '
    '"disclosed": ["公司披露的事实..."], "assumptions": ["分析假设..."], "judgments": ["你的判断..."], '
    '"unverified_info": ["未能核验的信息..."], "key_risks": ["关键风险..."], '
    '"metrics": {"roe": 数字或null, "eps": 数字或null, "net_margin": 数字或null, '
    '"revenue_yoy": 数字或null, "net_profit_yoy": 数字或null}}}\n'
    "```\n"
    "sections_present 只列你文档中实际完成拆解的模块；数据无法获得时在 unverified_info 中说明，不要编造。"
)

CHIEF_SYSTEM = (
    "你是首席交易员，负责汇总技术面、基本面、舆情三位分析师的报告，做出最终综合研判。"
    "输出一份完整的 markdown 报告（含综合结论、评分理由、关键价位、风险提示、观察清单），"
    "并在报告末尾输出一个 ```json 代码块，格式严格如下：\n"
    "```json\n"
    '{"structured": {"score": 1到10的整数, "bullish_points": ["..."], "bearish_points": ["..."], '
    '"key_levels": {"support": [数字...], "resistance": [数字...]}, '
    '"watch_items": [{"task_type": "price_level或event", '
    '"condition": {"kind": "price_below或price_above或event", "value": 数字(event时省略), "desc": "事件描述(event时必填)"}, '
    '"expect": "预期说明"}]}}\n'
    "```\n"
    "watch_items 给 2-5 条最值得跟踪的观察点；价格类用 price_below/price_above 并给出现价附近合理数值。"
)


def parse_data_model(content: str) -> dict | None:
    """解析报告中的 ```json {"data_model": ...} 块（取最后一个）；失败返回 None"""
    try:
        for block in reversed(JSON_BLOCK_RE.findall(content)):
            data = json.loads(block)
            if isinstance(data, dict) and isinstance(data.get("data_model"), dict):
                dm = data["data_model"]
                return {
                    "sections_present": [str(x) for x in (dm.get("sections_present") or [])],
                    "disclosed": [str(x) for x in (dm.get("disclosed") or [])],
                    "assumptions": [str(x) for x in (dm.get("assumptions") or [])],
                    "judgments": [str(x) for x in (dm.get("judgments") or [])],
                    "unverified_info": [str(x) for x in (dm.get("unverified_info") or [])],
                    "key_risks": [str(x) for x in (dm.get("key_risks") or [])],
                    "metrics": dict(dm.get("metrics") or {}),
                }
    except Exception:  # noqa: BLE001
        pass
    return None


def check_data_completeness(model: dict | None) -> list[str]:
    """数据模型完整性硬校验：核心模块缺失 + 无未验证信息清单说明数据可能不全"""
    if not model:
        return ["报告缺少结构化数据模型（data_model 块解析失败）"]
    issues = []
    present = model.get("sections_present") or []
    for required in ("收入", "利润", "现金流", "业务结构"):
        if not any(required in p for p in present):
            issues.append(f"数据模型缺少核心模块：{required}拆解")
    if not model.get("unverified_info"):
        issues.append("未验证信息清单为空（可能未做核验标注）")
    if not model.get("metrics"):
        issues.append("数据模型缺少关键经营指标(metrics)")
    return issues


def parse_structured(content: str) -> dict | None:
    """从报告 markdown 末尾解析 ```json ... ``` 块中的 structured 对象；失败返回 None"""
    try:
        blocks = JSON_BLOCK_RE.findall(content)
        if not blocks:
            return None
        data = json.loads(blocks[-1])
        if isinstance(data, dict) and "structured" in data:
            data = data["structured"]
        if not isinstance(data, dict):
            return None
        kl = data.get("key_levels") or {}
        return {
            "score": max(1, min(10, int(data.get("score", 5)))),
            "bullish_points": [str(x) for x in (data.get("bullish_points") or [])],
            "bearish_points": [str(x) for x in (data.get("bearish_points") or [])],
            "key_levels": {
                "support": [float(x) for x in (kl.get("support") or [])],
                "resistance": [float(x) for x in (kl.get("resistance") or [])],
            },
            "watch_items": [
                w for w in (data.get("watch_items") or [])
                if isinstance(w, dict) and w.get("task_type") in ("price_level", "event")
                and isinstance(w.get("condition"), dict)
            ],
        }
    except Exception:  # noqa: BLE001
        return None


def _fmt_bars(rows) -> str:
    lines = []
    for r in rows:
        lines.append(
            f"{r.trade_date} O:{r.open} H:{r.high} L:{r.low} C:{r.close} 涨跌%:{r.pct_chg} 量(手):{r.vol}"
        )
    return "\n".join(lines)


def _gather(db: Session, ts_code: str) -> dict:
    """收集本地行情/财务 + 博查新闻 + Milvus 历史报告检索"""
    data: dict = {"ts_code": ts_code}
    basic = db.get(StockBasic, ts_code)
    data["stock"] = {
        "name": basic.name if basic else ts_code,
        "industry": basic.industry if basic else None,
        "area": basic.area if basic else None,
    }
    bars = db.scalars(
        select(DailyPrice).where(DailyPrice.ts_code == ts_code)
        .order_by(DailyPrice.trade_date.desc()).limit(250)
    ).all()
    bars = list(reversed(bars))
    data["bars_text"] = _fmt_bars(bars) if bars else "（本地无日线数据）"
    data["latest_close"] = float(bars[-1].close) if bars else None

    fins = db.scalars(
        select(FinancialSnapshot).where(FinancialSnapshot.ts_code == ts_code)
        .order_by(FinancialSnapshot.end_date.desc()).limit(8)
    ).all()
    data["finance_text"] = "\n".join(
        f"报告期 {f.end_date} ROE:{f.roe} EPS:{f.eps} 毛利率:{f.gross_margin} "
        f"净利率:{f.net_margin} 资产负债率:{f.debt_ratio} 营收同比%:{f.revenue_yoy} 净利同比%:{f.net_profit_yoy}"
        for f in fins
    ) or "（无财务数据）"

    # 真实估值数据（PE/PB/换手/市值，近5日+分位参考）
    from ..models import DailyBasic
    vals = db.scalars(select(DailyBasic).where(DailyBasic.ts_code == ts_code)
                      .order_by(DailyBasic.trade_date.desc()).limit(500)).all()
    if vals:
        latest = vals[0]
        pes = [float(v.pe_ttm or v.pe) for v in vals if (v.pe_ttm or v.pe)]
        pctile = None
        if pes and len(pes) > 60 and (latest.pe_ttm or latest.pe):
            cur = float(latest.pe_ttm or latest.pe)
            pctile = round(sum(1 for p in pes if p <= cur) / len(pes) * 100)
        data["valuation_text"] = (
            f"最新({latest.trade_date}) 估值：PE(TTM) {latest.pe_ttm or latest.pe}、"
            f"PE(动) {latest.pe}、PB {latest.pb}、换手率 {latest.turn_rate}%、量比 {latest.volume_ratio}、"
            f"总市值 {round(float(latest.total_mv or 0) / 10000, 1)}亿"
            + (f"、PE(TTM)处近{len(pes)}日{pctile}%分位" if pctile is not None else ""))
    else:
        data["valuation_text"] = "（无本地估值数据）"

    name = data["stock"]["name"]
    from ..services import news_source
    news = news_source.get_news(ts_code, name, count=10)
    data["news"] = news
    data["news_text"] = "\n".join(
        f"- [{n.get('date', '')[:10]}][{n.get('source', '')}] {n['title']}：{n.get('snippet', '')}" for n in news
    ) or "（近一个月无搜索到相关新闻）"

    hits = milvus_store.search("report_kb", f"{ts_code} {name} 分析报告", top_k=3)
    data["history_reports"] = hits
    data["history_text"] = "\n---\n".join(h["text"] for h in hits) or "（无历史报告检索结果）"
    return data


def _run_sub_agent_content(role: str, system: str, user: str, workdir: Path | None = None) -> tuple[str, str, str]:
    """单个子agent调用，返回 (role, title, content)；产物落盘临时目录"""
    spec = SUB_AGENTS[role]
    content = ds_client.chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        model=settings.chat_model,
        temperature=0.5,
        max_tokens=3000,
    )
    if workdir:
        try:
            (workdir / f"sub_{role}.md").write_text(content, encoding="utf-8")
        except OSError:
            pass
    return role, spec["title"], content


def _create_watch_tasks(db: Session, report_id: int, ts_code: str, structured: dict) -> list[dict]:
    """解析 watch_items 逐条建 watch_task（expire = 今天 + 90 天）"""
    tasks_out = []
    expire = dt.date.today() + dt.timedelta(days=90)
    for item in structured.get("watch_items") or []:
        cond = item.get("condition") or {}
        kind = cond.get("kind")
        task_type = item.get("task_type")
        if task_type == "price_level" and kind not in ("price_below", "price_above"):
            kind = "price_above" if kind else None
        if task_type == "event":
            kind = "event"
        if not kind:
            continue
        condition_json = {"kind": kind}
        if kind != "event":
            try:
                condition_json["value"] = float(cond.get("value"))
            except (TypeError, ValueError):
                continue
        else:
            condition_json["desc"] = str(cond.get("desc") or item.get("expect") or "待观察事件")
        task = WatchTask(
            ts_code=ts_code,
            source_report_id=report_id,
            task_type=task_type,
            condition_json=condition_json,
            expect_json={"expect": str(item.get("expect") or "")},
            status="waiting",
            expire_date=expire,
        )
        db.add(task)
        db.flush()
        tasks_out.append({
            "id": task.id, "ts_code": ts_code, "task_type": task.task_type,
            "condition_json": task.condition_json, "expect_json": task.expect_json,
            "status": task.status, "expire_date": task.expire_date.isoformat(),
        })
    return tasks_out


def _sync_milvus_report(ts_code: str, report_id: int, as_of: dt.date, content: str):
    """报告切片（按 ## 标题分段）同步到 report_kb"""
    chunks: list[tuple[str, dict]] = []
    current_title = "总览"
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_lines:
                chunks.append((f"## {current_title}\n" + "\n".join(current_lines).strip(),
                               {"ts_code": ts_code, "report_id": report_id, "section": current_title}))
            current_title = line[3:].strip() or "（无标题）"
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        chunks.append((f"## {current_title}\n" + "\n".join(current_lines).strip(),
                       {"ts_code": ts_code, "report_id": report_id, "section": current_title,
                        "as_of_date": as_of.isoformat()}))
    if chunks:
        for text, meta in chunks:
            meta.setdefault("as_of_date", as_of.isoformat())
        milvus_store.upsert("report_kb", [t for t, _ in chunks], [m for _, m in chunks])


def run_analysis(ts_code: str, db: Session | None = None):
    """公司分析主流程生成器：数据建模 → 子agent并行 → 首席汇总 → 落库。
    yield ("status"/"section"/"done"/"error", payload)；临时目录在 finally 中清理。"""
    own_db = db is None
    db = db or SessionLocal()
    workdir: Path | None = None
    try:
        yield ("status", {"stage": "gathering", "msg": f"收集 {ts_code} 行情/财务/新闻/历史报告数据..."})
        data = _gather(db, ts_code)
        name = data["stock"]["name"]
        workdir = _workdir(ts_code)

        # ---- 阶段1：数据建模（用户提示词：拆解收入/利润/现金流/业务结构，区分披露vs假设vs判断） ----
        yield ("status", {"stage": "modeling", "msg": "数据建模agent：基于最新财报/公告构建可核验数据模型..."})
        model_user = (
            f"公司名称：{name}，股票代码：{ts_code}，行业：{data['stock']['industry']}。\n"
            f"本地财务快照（近8期，来自Tushare fina_indicator）：\n{data['finance_text']}\n\n"
            f"最新估值（Tushare daily_basic）：{data['valuation_text']}\n\n"
            f"近期新闻（供公告/事件参考）：\n{data['news_text']}\n\n"
            "请按系统要求交付数据模型文档与 json 块。"
        )
        model_content = ds_client.chat(
            [{"role": "system", "content": MODELING_SYSTEM},
             {"role": "user", "content": model_user}],
            model=settings.reasoner_model,
            max_tokens=8192,
        )
        (workdir / "data_model.md").write_text(model_content, encoding="utf-8")
        data_model = parse_data_model(model_content)
        if data_model:
            (workdir / "data_model.json").write_text(
                json.dumps(data_model, ensure_ascii=False, indent=2), encoding="utf-8")
        yield ("section", {"role": "model", "title": f"{name}({ts_code}) 数据模型与核验清单", "content": model_content})

        # ---- 阶段2：三子agent并行（基本面基于数据模型） ----
        yield ("status", {"stage": "technical", "msg": "技术面/基本面/舆情 三个子分析师并行分析中..."})

        def sub_user(role: str) -> str:
            if role == "technical":
                return (f"股票：{ts_code} {name}，最新收盘价 {data['latest_close']}。\n"
                        f"近250个交易日日线数据：\n{data['bars_text']}")
            if role == "fundamental":
                return (f"股票：{ts_code} {name}（行业：{data['stock']['industry']}）。\n"
                        f"下面是研究员刚完成的数据模型（以此为主要依据，核验其口径与勾稽，"
                        f"标注其中你不同意的假设）：\n\n{model_content}\n\n"
                        f"原始财务快照（近8期）：\n{data['finance_text']}\n"
                        f"最新估值：{data['valuation_text']}")
            return (f"股票：{ts_code} {name}，最新收盘价 {data['latest_close']}。\n"
                    f"近一个月新闻搜索结果：\n{data['news_text']}")

        sections: dict[str, tuple[str, str]] = {}
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                role: pool.submit(
                    _run_sub_agent_content, role, spec["system"], sub_user(role), workdir)
                for role, spec in SUB_AGENTS.items()
            }
            for role, fut in futures.items():
                try:
                    _, title, content = fut.result()
                    sections[role] = (title, content)
                except Exception as e:  # noqa: BLE001
                    errors[role] = str(e)
                    log.warning("子agent %s 失败: %s", role, e)
        for role in ("technical", "fundamental", "sentiment"):
            if role in sections:
                title, content = sections[role]
                yield ("section", {"role": role, "title": title, "content": content})

        if not sections:
            yield ("error", {"msg": f"全部子agent失败: {errors}"})
            return

        # ---- 阶段3：首席交易员综合研判（基于数据模型 + 子报告） ----
        yield ("status", {"stage": "chief", "msg": "首席交易员(deepseek-reasoner)综合研判中..."})
        sub_md = "\n\n".join(
            f"## {sections[r][0]}\n\n{sections[r][1]}" for r in sections if r in sections
        )
        history_note = ""
        if data["history_reports"]:
            history_note = ("\n\n=== 历史报告检索(向量库,供延续性参考) ===\n" + data["history_text"])
        chief_content = ds_client.chat(
            [{"role": "system", "content": CHIEF_SYSTEM},
             {"role": "user",
              "content": (f"股票：{ts_code} {name}，最新收盘价 {data['latest_close']}，"
                          f"今日 {dt.date.today().isoformat()}。\n\n"
                          f"=== 研究员数据模型（分析的事实基础，如与分析师结论矛盾请指出） ===\n"
                          f"{model_content}\n\n三位分析师报告：\n\n{sub_md}{history_note}")}],
            model=settings.reasoner_model,
            max_tokens=8192,
        )
        (workdir / "chief.md").write_text(chief_content, encoding="utf-8")
        yield ("section", {"role": "chief", "title": f"{name}({ts_code}) 综合研判", "content": chief_content})

        # ---- 落库（正文 = 首席研判 + 数据模型附录，json 块保持在末尾可解析） ----
        yield ("status", {"stage": "done", "msg": "报告入库、创建观察任务、同步向量库、清理临时文件..."})
        structured = parse_structured(chief_content)
        today = dt.date.today()
        full_content = (chief_content.rstrip()
                        + f"\n\n---\n\n# 附：数据模型与核验清单\n\n{model_content}")
        report = AnalysisReport(
            ts_code=ts_code,
            as_of_date=today,
            report_type="company",
            title=f"{name}({ts_code}) 综合分析 {today.isoformat()}",
            content=full_content,
            model=settings.reasoner_model,
        )
        db.add(report)
        db.flush()

        prev_id = db.scalar(
            select(AnalysisReport.id)
            .where(AnalysisReport.ts_code == ts_code, AnalysisReport.report_type == "company",
                   AnalysisReport.id != report.id)
            .order_by(AnalysisReport.id.desc()).limit(1)
        )
        db.add(ReportChain(ts_code=ts_code, report_id=report.id, prev_report_id=prev_id))

        watch_tasks_out = []
        if structured:
            watch_tasks_out = _create_watch_tasks(db, report.id, ts_code, structured)
        db.commit()

        _sync_milvus_report(ts_code, report.id, today, full_content)

        yield ("done", {"report_id": report.id, "watch_tasks": watch_tasks_out,
                        "data_issues": check_data_completeness(data_model)})
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.exception("公司分析失败 %s", ts_code)
        yield ("error", {"msg": f"分析失败: {e}"})
    finally:
        _cleanup_workdir(workdir)
        if own_db:
            db.close()
