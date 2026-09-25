import sqlite3, os, glob
db = r'C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\stonkfly\runs\paper\ledger.sqlite'
if os.path.exists(db):
    con = sqlite3.connect(db)
    cur = con.cursor()
    # 列出 meta 表
    cur.execute("SELECT key FROM meta")
    keys = [r[0] for r in cur.fetchall()]
    print("meta keys:", keys)
    for k in ['checkpoint', 'provenance_sha256', 'halted']:
        cur.execute("DELETE FROM meta WHERE key=?", (k,))
    con.commit()
    con.close()
    print("ledger cleaned")
# 清除 brain checkpoint
for f in glob.glob(r'C:\Users\ANGEL\Doubao\chats\2026-09-12\new-chat\stonkfly\runs\paper\brain-*.npz'):
    os.remove(f)
    print("removed", f)
