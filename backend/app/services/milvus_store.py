"""Milvus 向量库封装：report_kb / news_kb / strategy_kb（1024维 COSINE auto_id）
连接失败全部静默降级（log warning 返回空），绝不抛异常阻塞主流程"""
import logging
import threading

from ..config import settings
from . import embedding as emb

log = logging.getLogger(__name__)

DIM = 1024
COLLECTIONS = ("report_kb", "news_kb", "strategy_kb")

_client = None
_client_lock = threading.Lock()
_connect_failed = False


def _get_client():
    global _client, _connect_failed
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        if _connect_failed:
            return None
        try:
            from pymilvus import MilvusClient
            c = MilvusClient(uri=settings.milvus_uri, timeout=10)
            c.list_collections()
            _client = c
            log.info("Milvus 已连接: %s", settings.milvus_uri)
            return _client
        except Exception as e:  # noqa: BLE001
            _connect_failed = True
            log.warning("Milvus 连接失败(%s)，向量库降级为空操作: %s", settings.milvus_uri, e)
            return None


def ensure_collections() -> bool:
    """创建缺失的 collection；失败静默返回 False"""
    c = _get_client()
    if c is None:
        return False
    try:
        from pymilvus import DataType
        existing = set(c.list_collections())
        for name in COLLECTIONS:
            if name in existing:
                continue
            schema = MilvusSchema.create(c)
            schema.add_field("id", DataType.INT64, is_primary=True)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIM)
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            schema.add_field("metadata", DataType.JSON)
            index_params = c.prepare_index_params()
            index_params.add_index(field_name="vector", metric_type="COSINE", index_type="AUTOINDEX")
            c.create_collection(collection_name=name, schema=schema, index_params=index_params)
            log.info("Milvus collection 已创建: %s", name)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Milvus ensure_collections 失败(降级): %s", e)
        return False


class MilvusSchema:
    """轻量包装，兼容不同 pymilvus 版本的 schema 创建入口"""

    def __init__(self, schema):
        self._schema = schema

    @classmethod
    def create(cls, client):
        try:
            return cls(client.create_schema(auto_id=True, enable_dynamic_field=True))
        except Exception:  # noqa: BLE001
            from pymilvus import CollectionSchema
            return cls(CollectionSchema(auto_id=True, enable_dynamic_field=True))

    def add_field(self, *args, **kwargs):
        return self._schema.add_field(*args, **kwargs)

    @property
    def raw(self):
        return self._schema


def upsert(collection: str, texts: list[str], metadatas: list[dict]) -> bool:
    """向量化并写入；embedding 不可用或连接失败 → 静默跳过返回 False"""
    if collection not in COLLECTIONS or not texts:
        return False
    c = _get_client()
    if c is None:
        return False
    try:
        ensure_collections()
        vectors = emb.embed(texts)
        if vectors is None:
            log.warning("embedding 不可用，跳过 Milvus upsert(%s, %d 条)", collection, len(texts))
            return False
        rows = [
            {"vector": v, "text": t, "metadata": m or {}}
            for t, v, m in zip(texts, vectors, metadatas)
        ]
        c.insert(collection_name=collection, data=rows)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Milvus upsert 失败(%s, 降级): %s", collection, e)
        return False


def search(collection: str, query_text: str, top_k: int = 3) -> list[dict]:
    """相似检索 → [{text, metadata, score}]；任何失败返回 []"""
    if collection not in COLLECTIONS or not query_text:
        return []
    c = _get_client()
    if c is None:
        return []
    try:
        vecs = emb.embed([query_text])
        if vecs is None:
            return []
        res = c.search(
            collection_name=collection,
            data=vecs,
            limit=top_k,
            output_fields=["text", "metadata"],
        )
        out = []
        for hit_group in res:
            for hit in hit_group:
                ent = hit.get("entity", {}) if isinstance(hit, dict) else getattr(hit, "entity", {})
                out.append({
                    "text": (ent.get("text") if isinstance(ent, dict) else getattr(ent, "text", "")) or "",
                    "metadata": (ent.get("metadata") if isinstance(ent, dict) else getattr(ent, "metadata", {})) or {},
                    "score": hit.get("distance", 0.0) if isinstance(hit, dict) else getattr(hit, "distance", 0.0),
                })
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Milvus search 失败(%s, 降级返回空): %s", collection, e)
        return []
