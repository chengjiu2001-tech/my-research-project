"""Explicitly recalculate local usage estimates from versioned local prices."""
import server

def main():
    server.init();cfg=server.config()
    with server.connect() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM events WHERE source='logs'")]
        for row in rows:
            cost,currency=server.estimate(row,cfg)
            c.execute('UPDATE events SET cost=?,currency=? WHERE id=?',(cost,currency,row['id']))
    print(f'已按当前价格版本更新 {len(rows)} 条本地调用记录；官方费用不变。')
if __name__=='__main__':main()
