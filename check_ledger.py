import sqlite3
con = sqlite3.connect(r'C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\stonkfly\runs\paper\ledger.sqlite')
cur = con.cursor()
cur.execute("SELECT key, value FROM meta")
for row in cur.fetchall():
    print(f"{row[0]}: {str(row[1])[:100]}")
con.close()
