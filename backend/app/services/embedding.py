"""BGE-M3 embedding：进程内单例懒加载；失败/超时(60s)返回 None 由调用方降级"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from ..config import settings

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()
_load_failed = False
_load_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge-load")


def _do_load():
    from sentence_transformers import SentenceTransformer  # 延迟导入
    return SentenceTransformer(settings.bge_m3_path)


def get_model():
    """懒加载单例模型；失败或超过 60s 返回 None"""
    global _model, _load_failed
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        if _load_failed or not settings.bge_m3_path:
            return None
        try:
            future = _load_pool.submit(_do_load)
            _model = future.result(timeout=60)
            log.info("BGE-M3 模型加载成功: %s", settings.bge_m3_path)
            return _model
        except Exception as e:  # noqa: BLE001  含 TimeoutError
            _load_failed = True
            log.warning("BGE-M3 加载失败或超时(60s)，embedding 降级为 None: %s", e)
            return None


def embed(texts: list[str]) -> list[list[float]] | None:
    """向量化；模型不可用返回 None（调用方降级，如跳过向量检索）"""
    if not texts:
        return []
    model = get_model()
    if model is None:
        return None
    try:
        vecs = model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]
    except Exception as e:  # noqa: BLE001
        log.warning("embedding 编码失败(降级 None): %s", e)
        return None
