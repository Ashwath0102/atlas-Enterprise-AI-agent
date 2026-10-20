import sqlite3, json
con = sqlite3.connect("data/tickets.db")
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("tables:", tables)
for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = [(r[1], r[2]) for r in cur.fetchall()]
    print(f"{t}: {cols}")
cur.execute("SELECT * FROM tickets LIMIT 3")
rows = cur.fetchall()
cur.execute("PRAGMA table_info(tickets)")
col_names = [r[1] for r in cur.fetchall()]
print("col_names:", col_names)
for row in rows:
    print(dict(zip(col_names, row)))
con.close()
