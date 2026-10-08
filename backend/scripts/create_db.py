import pymysql

conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456", charset="utf8mb4")
cur = conn.cursor()
cur.execute("CREATE DATABASE IF NOT EXISTS stock_analyst DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
cur.execute("SHOW DATABASES LIKE 'stock_analyst'")
print("db created:", cur.fetchall())
conn.close()
