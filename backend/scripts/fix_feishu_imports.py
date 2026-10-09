from pathlib import Path

p = Path("app/services/feishu_bot.py")
s = p.read_text(encoding="utf-8")
s = s.replace("from .executor import execute_agent_order",
              "from .agent.executor import execute_agent_order")
s = s.replace("from . import risk as risk_engine",
              "from .agent import risk as risk_engine")
s = s.replace("from .trader import run_intraday, run_daily",
              "from .agent.trader import run_intraday, run_daily")
s = s.replace("from ..services.realtime import get_realtime",
              "from .realtime import get_realtime")
s = s.replace("from ..services import news_source",
              "from . import news_source")
s = s.replace("from ..services.deepseek_client import client as ds_client",
              "from .deepseek_client import client as ds_client")
p.write_text(s, encoding="utf-8")
print("imports fixed")
