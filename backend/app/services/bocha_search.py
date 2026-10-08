"""博查 AI 网络搜索（失败降级返回 []）"""
import logging

import httpx

from ..config import settings

log = logging.getLogger(__name__)

BOCHA_URL = "https://api.bochaai.com/v1/web-search"


def web_search(query: str, count: int = 10, freshness: str = "oneMonth") -> list[dict]:
    """网页搜索，返回 [{title, snippet, url, date}]；任何失败返回 []（不抛异常）"""
    if not settings.bocha_api_key:
        log.warning("bocha_api_key 未配置，跳过搜索")
        return []
    try:
        r = httpx.post(
            BOCHA_URL,
            headers={
                "Authorization": f"Bearer {settings.bocha_api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query, "count": count, "freshness": freshness},
            timeout=20,
        )
        r.raise_for_status()
        pages = (r.json().get("data") or {}).get("webPages") or {}
        results = []
        for p in pages.get("value") or []:
            results.append({
                "title": p.get("name") or "",
                "snippet": p.get("snippet") or "",
                "url": p.get("url") or "",
                "date": p.get("dateLastCrawled") or p.get("datePublished") or "",
            })
        return results
    except Exception as e:  # noqa: BLE001
        log.warning("博查搜索失败(降级返回空): %s", e)
        return []
