import pymysql

conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456",
                       database="stock_analyst", charset="utf8mb4")
cur = conn.cursor()
cur.execute("ALTER TABLE backtest_run MODIFY strategy_id BIGINT NULL")
conn.commit()
print("backtest_run.strategy_id -> NULLABLE OK")
conn.close()
