"""归纳总结 Agent：历史 company 报告 vs 后续30天真实走势 → 演变/兑现总结
新增相互印证：核验最新报告数据模型完整性并对照本地财务数据，数据不全时自动触发公司分析更新。"""
import datetime as dt
import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import AnalysisReport, DailyPrice, FinancialSnapshot, ReportChain
from .company_analysis import check_data_completeness, parse_data_model, parse_structured

log = logging.getLogger(__name__)

SYSTEM = (
    "你是资深投资复盘专家。你会收到某股票的历史分析报告序列（可能含人机综合分析：AI报告融合了用户讨论观点），"
    "以及每份报告发布后30个交易日该股的实际累计涨跌幅。\n"
    "请输出 markdown 总结：1) 各期报告的判断后来兑现还是落空（结合实际走势数据）；"
    "2) 分析师观点的演变轨迹（看多/看空/关键位变化）；3) 哪类判断（技术面/基本面/舆情）历史上更可靠；"
    "4) 最新报告的数据模型与本地财务数据(Tushare)的相互印证结果：指标数值是否一致、口径是否冲突、"
    "哪些关键数据缺失或未核验；"
    "5) **用户判断复盘**：报告中标注的用户观点，后来兑现还是落空？与同期AI判断对比谁更准确、"
    "用户在哪类判断上更可靠（如风险识别/题材判断），给出后续协作建议；"
    "6) 对后续使用该系列报告的建议。用数据说话，不要编造。"
    "最后输出一个 ```json 代码块：\n"
    "```json\n"
    '{"data_complete": true或false, "data_issues": ["发现的数据问题，如：现金流拆解缺失、'
    'EPS与财报口径不一致、盈利预测无假设依据..."]}}\n'
    "```\n"
    "data_issues 列出所有数据不完整/不一致/未核验的具体问题；完整无问题则给空数组。"
)

VERIFY_SYSTEM = (
    "你是财务数据核验员。对比【报告数据模型】与【本地财务数据库】两份材料，"
    "输出简短 markdown：一致项、口径冲突项、数据库有而报告缺失的关键指标、报告有而数据库无法印证的指标。"
)


def _perf_after(db: Session, ts_code: str, as_of: dt.date, days: int = 30) -> str:
    """报告 as_of_date 后 days 个交易日的实际走势（累计涨跌幅）"""
    rows = db.scalars(
        select(DailyPrice).where(DailyPrice.ts_code == ts_code, DailyPrice.trade_date >= as_of)
        .order_by(DailyPrice.trade_date).limit(days + 1)
    ).all()
    if len(rows) < 2:
        return "（后续无行情数据，无法验证）"
    base = float(rows[0].close)
    last = rows[-1]
    cum = (float(last.close) / base - 1) * 100 if base else 0.0
    path = " ".join(
        f"{r.trade_date}:{float(r.pct_chg):+.2f}%" for r in rows[1:] if r.pct_chg is not None
    )
    hi = max(float(r.high) for r in rows)
    lo = min(float(r.low) for r in rows)
    return f"基期收盘 {base}，期间最高 {hi} / 最低 {lo}，期末收盘 {float(last.close)}，累计 {cum:+.2f}%。逐日涨跌：{path}"


def _finance_snapshot_text(db: Session, ts_code: str) -> str:
    fins = db.scalars(
        select(FinancialSnapshot).where(FinancialSnapshot.ts_code == ts_code)
        .order_by(FinancialSnapshot.end_date.desc()).limit(4)
    ).all()
    return "\n".join(
        f"报告期 {f.end_date} ROE:{f.roe} EPS:{f.eps} 毛利率:{f.gross_margin} "
        f"净利率:{f.net_margin} 资产负债率:{f.debt_ratio} 营收同比%:{f.revenue_yoy} 净利同比%:{f.net_profit_yoy}"
        for f in fins
    ) or "（本地无财务数据）"


def run_synthesis(ts_code: str, db: Session | None = None):
    """归纳总结生成器：yield ("status",...) / ("section",{role:'chief',...}) / ("done",...)/("error",...)"""
    own_db = db is None
    db = db or SessionLocal()
    try:
        yield ("status", {"stage": "gathering", "msg": f"收集 {ts_code} 历史报告与后续走势数据..."})
        reports = db.scalars(
            select(AnalysisReport)
            .where(AnalysisReport.ts_code == ts_code, AnalysisReport.report_type == "company")
            .order_by(AnalysisReport.as_of_date, AnalysisReport.id)
        ).all()
        if not reports:
            yield ("error", {"msg": f"{ts_code} 无历史 company 报告，无法归纳"})
            return

        chains = {
            r.report_id: r.prev_report_id
            for r in db.scalars(select(ReportChain).where(ReportChain.ts_code == ts_code)).all()
        }
        blocks = []
        from ..models import ReportDiscussion, ReportMerge
        for rep in reports:
            # 混合基准：有人机综合分析优先用综合分析，否则用原始AI报告
            merged = db.scalar(select(ReportMerge).where(ReportMerge.report_id == rep.id))
            base = merged.content if merged else rep.content
            base_kind = "人机综合分析" if merged else "AI原始报告"
            structured = parse_structured(base)
            score = structured.get("score") if structured else None
            # 用户观点：讨论中的用户发言（供用户判断复盘）
            user_msgs = db.scalars(select(ReportDiscussion).where(
                ReportDiscussion.report_id == rep.id,
                ReportDiscussion.role == "user")
                .order_by(ReportDiscussion.id)).all()
            user_views = "\n".join(f"- {m.content[:150]}" for m in user_msgs)
            summary = (f"### 报告 {rep.id}《{rep.title}》 as_of={rep.as_of_date} "
                       f"类型={base_kind} 评分={score}\n{base[:2500]}")
            if user_views:
                summary += f"\n\n**该期用户观点（讨论记录）**：\n{user_views}"
            perf = _perf_after(db, ts_code, rep.as_of_date, days=30)
            blocks.append(f"{summary}\n\n**该报告后30个交易日实际走势**：{perf}")
        user_content = (f"股票 {ts_code} 共 {len(reports)} 份历史公司分析报告（按时间升序）及各自后续30日实际走势：\n\n"
                        + "\n\n---\n\n".join(blocks))

        yield ("status", {"stage": "chief", "msg": "deepseek-reasoner 归纳判断兑现/落空与观点演变..."})
        content = None
        try:
            from ..services.deepseek_client import client as ds_client

            # ---- 相互印证：核验最新报告数据模型 vs 本地财务数据 ----
            latest = reports[-1]
            model = parse_data_model(latest.content)
            code_issues = check_data_completeness(model)
            verify_md = ""
            verify_note = ""
            if model:
                yield ("status", {"stage": "verifying", "msg": "数据核验：报告数据模型 vs 本地财务数据..."})
                try:
                    verify_md = ds_client.chat(
                        [{"role": "system", "content": VERIFY_SYSTEM},
                         {"role": "user",
                          "content": (f"【报告数据模型(最新报告 {latest.id})】\n{json.dumps(model, ensure_ascii=False, indent=1)}\n\n"
                                      f"【本地财务数据库(Tushare fina_indicator 近4期)】\n"
                                      f"{_finance_snapshot_text(db, ts_code)}")}],
                        model=settings.chat_model,
                        max_tokens=2000,
                    )
                    verify_note = f"\n\n## 数据相互印证（报告模型 vs 本地财务库）\n\n{verify_md}"
                except Exception as e:  # noqa: BLE001
                    log.warning("数据核验 LLM 失败(降级为硬校验): %s", e)
            data_issues = list(code_issues)
            if verify_md:
                # LLM 核验结论只作展示，硬性 issues 以代码校验 + 归纳 agent 输出为准
                user_content_tail = (f"\n\n=== 数据相互印证材料 ===\n{verify_md}\n"
                                     f"=== 代码硬校验发现的问题 ===\n" +
                                     ("\n".join(f"- {i}" for i in code_issues) if code_issues else "（无）"))
            else:
                user_content_tail = ("\n\n=== 代码硬校验发现的数据问题 ===\n" +
                                     ("\n".join(f"- {i}" for i in code_issues) if code_issues else "（无）"))

            content = ds_client.chat(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_content + user_content_tail}],
                model=settings.reasoner_model,
                max_tokens=8192,
            )
        except Exception as e:  # noqa: BLE001
            yield ("error", {"msg": f"归纳总结 LLM 调用失败: {e}"})
            return
        yield ("section", {"role": "chief", "title": f"{ts_code} 历史报告归纳总结", "content": content + verify_note})

        # 解析归纳 agent 的数据问题结论（与代码硬校验合并去重）
        llm_issues: list[str] = []
        try:
            blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            for b in reversed(blocks):
                d = json.loads(b)
                if isinstance(d, dict) and "data_issues" in d:
                    llm_issues = [str(x) for x in (d.get("data_issues") or [])]
                    break
        except Exception:  # noqa: BLE001
            pass
        all_issues = list(dict.fromkeys(data_issues + llm_issues))

        yield ("status", {"stage": "done", "msg": "总结入库..."})
        today = dt.date.today()
        report = AnalysisReport(
            ts_code=ts_code,
            as_of_date=today,
            report_type="synthesis",
            title=f"{ts_code} 历史报告归纳总结 {today.isoformat()}",
            content=content + verify_note,
            model=settings.reasoner_model,
        )
        db.add(report)
        db.commit()

        # ---- 相互印证闭环：数据不全 → 自动重跑公司分析（新版本入库+版本链） ----
        updated_company_report_id = None
        if all_issues:
            yield ("status", {"stage": "updating",
                              "msg": f"发现 {len(all_issues)} 项数据问题，自动更新公司分析报告..."})
            from .company_analysis import run_analysis
            try:
                for ev, payload in run_analysis(ts_code):
                    if ev == "error":
                        log.error("自动更新公司分析失败: %s", payload)
                        break
                    if ev == "done":
                        updated_company_report_id = payload.get("report_id")
            except Exception as e:  # noqa: BLE001
                log.exception("自动更新公司分析异常 %s", ts_code)

        yield ("done", {"report_id": report.id, "data_issues": all_issues,
                        "company_updated": updated_company_report_id is not None,
                        "updated_company_report_id": updated_company_report_id})
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.exception("归纳总结失败 %s", ts_code)
        yield ("error", {"msg": f"归纳总结失败: {e}"})
    finally:
        if own_db:
            db.close()
