"""全局配置：从 backend/.env 读取"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    # 数据库
    mysql_url: str = "mysql+pymysql://root:123456@127.0.0.1:3306/stock_analyst?charset=utf8mb4"
    redis_url: str = ""  # 为空则不启用缓存(可选降级)
    milvus_uri: str = "http://192.168.190.167:19530"

    # Tushare
    tushare_token: str = ""
    tushare_api_url: str = "https://tuaremax.top"
    tushare_max_per_min: int = 300

    # 外部服务
    bocha_api_key: str = ""
    deepseek_api_key: str = ""
    chat_model: str = "deepseek-chat"
    reasoner_model: str = "deepseek-reasoner"

    # 本地向量模型
    bge_m3_path: str = ""

    # 模拟交易费用
    commission_rate: float = 0.00025
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.001

    # 飞书通知（可选）
    feishu_webhook_url: str = ""
    feishu_secret: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""


settings = Settings()
