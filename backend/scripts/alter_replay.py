import pymysql

conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456",
                       database="stock_analyst", charset="utf8mb4")
cur = conn.cursor()
cur.execute("ALTER TABLE replay_session ADD COLUMN strategy_id BIGINT NULL")
cur.execute("ALTER TABLE replay_session ADD COLUMN params JSON NULL")
cur.execute("ALTER TABLE replay_session ADD COLUMN strategy_last_date DATE NULL")
conn.commit()
print("replay_session: strategy columns added")
conn.close()
