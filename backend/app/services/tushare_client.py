"""Tushare 客户端：中转地址 + 令牌桶限流 + 重试退避"""
import logging
import threading
import time
from collections import deque

import pandas as pd
import tushare as ts

from ..config import settings

log = logging.getLogger(__name__)


class RateLimiter:
    """滑动窗口令牌限流（每分钟 N 次）"""

    def __init__(self, max_per_min: int):
        self.max = max_per_min
        self.window: deque[float] = deque()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                while self.window and now - self.window[0] > 60:
                    self.window.popleft()
                if len(self.window) < self.max:
                    self.window.append(now)
                    return
                wait = 60 - (now - self.window[0]) + 0.1
            log.debug("tushare 限流等待 %.1fs", wait)
            time.sleep(min(wait, 5))


class TushareClient:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._init()
                cls._instance = obj
            return cls._instance

    def _init(self):
        self.limiter = RateLimiter(settings.tushare_max_per_min)
        self._api = ts.pro_api(settings.tushare_token)
        # 关键：走中转地址（显式覆盖私有字段）
        self._api._DataApi__token = settings.tushare_token
        self._api._DataApi__http_url = settings.tushare_api_url

    def query(self, api_name: str, retries: int = 3, **kwargs) -> pd.DataFrame:
        last_err = None
        for attempt in range(retries):
            self.limiter.acquire()
            try:
                df = getattr(self._api, api_name)(**kwargs)
                if df is None:
                    return pd.DataFrame()
                # 中转/官方约定：异常通过 code 列返回
                if "code" in df.columns and len(df) and str(df.iloc[0].get("code", "")).startswith("-1"):
                    raise RuntimeError(f"tushare {api_name} 错误: {df.iloc[0].to_dict()}")
                return df
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("tushare %s 第%d次失败: %s", api_name, attempt + 1, e)
                time.sleep(2 ** attempt)
        raise RuntimeError(f"tushare {api_name} 重试{retries}次仍失败: {last_err}")


client = TushareClient()
