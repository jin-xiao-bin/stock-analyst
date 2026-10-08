import pymysql

conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456",
                       database="stock_analyst", charset="utf8mb4")
cur = conn.cursor()
cur.execute("ALTER TABLE agent_config ADD COLUMN disabled_stocks JSON NULL")
conn.commit()
print("agent_config.disabled_stocks added")
conn.close()
