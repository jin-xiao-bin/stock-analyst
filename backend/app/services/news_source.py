"""新闻/公告双通道聚合：博查AI搜索(主) → 东方财富公开接口(兜底)

统一输出 [{title, snippet, url, date, source}]，按标题去重，单通道失败不阻塞。
东财通道实测可用：个股公告(np-anotice-stock) + 新闻搜索(search-api-web，需浏览器头)。
"""
import json
import logging

import httpx

from .bocha_search import web_search as bocha_search
from ..config import settings

log = logging.getLogger(__name__)

EM_ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
EM_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://so.eastmoney.com/",
}


def _strip_tags(s: str) -> str:
    return (s or "").replace("<em>", "").replace("</em>", "").strip()


def em_announcements(ts_code: str, limit: int = 10) -> list[dict]:
    """东财个股公告列表 → [{title, snippet, url, date, source}]"""
    try:
        symbol = ts_code.split(".")[0]
        r = httpx.get(
            EM_ANN_URL,
            params={"sr": -1, "page_size": limit, "page_index": 1,
                    "ann_type": "A", "stock_list": symbol},
            timeout=15, headers=EM_HEADERS,
        )
        r.raise_for_status()
        lst = ((r.json().get("data") or {}).get("list")) or []
        out = []
        for it in lst:
            art = it.get("art_code") or ""
            out.append({
                "title": _strip_tags(it.get("title")),
                "snippet": "【公告】" + _strip_tags(it.get("title")),
                "url": f"https://data.eastmoney.com/notices/detail/{ts_code}/{art}.html" if art else "",
                "date": (it.get("notice_date") or "")[:10],
                "source": "em_ann",
            })
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("东财公告接口失败(降级跳过): %s", e)
        return []


def em_news_search(keyword: str, limit: int = 10) -> list[dict]:
    """东财新闻搜索 → [{title, snippet, url, date, source}]"""
    try:
        param = {
            "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
            "client": "web", "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time",
                                            "pageIndex": 1, "pageSize": limit,
                                            "preTag": "", "postTag": ""}},
        }
        r = httpx.get(
            EM_SEARCH_URL,
            params={"cb": "jQuery_cb", "param": json.dumps(param, ensure_ascii=False)},
            timeout=15, headers=EM_HEADERS,
        )
        r.raise_for_status()
        text = r.text.strip()
        prefix = "jQuery_cb("
        if not text.startswith(prefix):
            return []
        d = json.loads(text[len(prefix):-1])
        arts = (d.get("result") or {}).get("cmsArticleWebOld") or []
        return [{
            "title": _strip_tags(a.get("title")),
            "snippet": _strip_tags(a.get("content"))[:200],
            "url": a.get("url") or "",
            "date": (a.get("date") or "")[:10],
            "source": "em_news",
        } for a in arts]
    except Exception as e:  # noqa: BLE001
        log.warning("东财新闻搜索失败(降级跳过): %s", e)
        return []


def _dedup(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for it in items:
        key = it.get("title", "")
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def get_news(ts_code: str, name: str, count: int = 10) -> list[dict]:
    """个股新闻+公告聚合：博查优先，不足用东财公告/新闻补齐，按标题去重。"""
    items = [{**it, "source": "bocha"} for it in
             bocha_search(f"{name} {ts_code} 股票 最新消息 公告", count=count, freshness="oneMonth")]
    if len(items) < count:
        items += em_announcements(ts_code, limit=count)
        items += em_news_search(f"{name} {ts_code}", limit=count)
    return _dedup(items)[:count]


def verify_search(query: str, count: int = 5) -> list[dict]:
    """事件核验搜索：博查优先，空则东财新闻兜底。"""
    items = [{**it, "source": "bocha"} for it in bocha_search(query, count=count, freshness="oneMonth")]
    if not items:
        items = em_news_search(query, limit=count)
    return _dedup(items)[:count]
