"""API 流量看板 · Python 3.10+ · local-only, no third party dependencies."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.error import HTTPError, URLError
import argparse, csv, io, json, sqlite3, threading, hashlib, random, os

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config/settings.json'
DB = ROOT / 'data/usage.sqlite3'
TZ = timezone(timedelta(hours=8))
PROVIDERS = ('deepseek', 'kimi', 'openai')
SYNC_LOCK = threading.Lock()

def now(): return datetime.now(TZ)
def config():
    with CONFIG.open(encoding='utf-8') as f: return json.load(f)
def configured(key): return bool(key and not key.startswith('YOUR_'))
def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, provider TEXT, model TEXT, project TEXT,
            time TEXT, input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER,
            requests INTEGER, source TEXT, cost TEXT, currency TEXT);
        CREATE INDEX IF NOT EXISTS event_time ON events(time);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
        ''')

def state(key, default=None):
    with connect() as c: row = c.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default

def save_state(key, value):
    with connect() as c: c.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key,json.dumps(value,ensure_ascii=False)))

def natural(value, nullable=True):
    if value is None and nullable: return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise ValueError('Token 和请求数必须为非负整数')
    return value

def estimate(e, cfg):
    # Cached tokens are included in input; never add them a second time.
    for p in sorted(cfg.get('prices', []), key=lambda p:p['effective_from'], reverse=True):
        if p['provider'] == e['provider'] and p['model'] == e['model'] and p['effective_from'] <= e['time'][:10]:
            if any(e[k] is None for k in ('input_tokens','output_tokens','cached_tokens')): return None, None
            rates = [Decimal(str(p[k])) for k in ('input_per_million','output_per_million','cache_read_per_million')]
            if any(not r.is_finite() or r < 0 for r in rates): raise ValueError('价格必须为非负有限数')
            value = ((e['input_tokens']-e['cached_tokens'])*rates[0]+e['output_tokens']*rates[1]+e['cached_tokens']*rates[2])/Decimal(1000000)
            return str(value),p['currency']
    return None,None

def normalize(raw, cfg):
    if raw.get('provider') not in PROVIDERS: raise ValueError('不支持的平台')
    if not isinstance(raw.get('id'),str) or not 0 < len(raw['id']) <= 200: raise ValueError('需要稳定的请求 id（1–200 字符）')
    dt = datetime.fromisoformat(raw['time'].replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError('time 必须包含时区')
    model, project = raw.get('model','unknown'), raw.get('project','default')
    if not all(isinstance(s,str) and 0 < len(s) <= 200 for s in (model,project)): raise ValueError('模型与项目标签无效')
    e = dict(id=raw['provider']+':log:'+raw['id'], provider=raw['provider'], model=model, project=project,
             time=dt.astimezone(TZ).isoformat(), input_tokens=natural(raw.get('input_tokens')),
             output_tokens=natural(raw.get('output_tokens')),cached_tokens=natural(raw.get('cached_tokens')),
             requests=natural(raw.get('requests',1),False),source='logs')
    if e['cached_tokens'] is not None and (e['input_tokens'] is None or e['cached_tokens'] > e['input_tokens']):
        raise ValueError('缓存读取 Token 必须包含在 input_tokens 内')
    e['cost'],e['currency']=estimate(e,cfg)
    return e

COLUMNS = ('id','provider','model','project','time','input_tokens','output_tokens','cached_tokens','requests','source','cost','currency')
def put_events(events, c):
    for e in events:
        c.execute('INSERT OR IGNORE INTO events VALUES ('+','.join('?' for _ in COLUMNS)+')',tuple(e.get(k) for k in COLUMNS))

def ingest(raw):
    if not isinstance(raw,list) or not 1 <= len(raw) <= 5000: raise ValueError('每批需要 1–5000 条调用记录')
    cfg=config()
    events=[normalize(e,cfg) for e in raw]  # validate whole batch before transaction
    with connect() as c:
        before=c.total_changes
        put_events(events,c)
        return c.total_changes-before

class NoRedirect(__import__('urllib.request',fromlist=['HTTPRedirectHandler']).HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

def remote(url, key):
    # Keys only leave the server towards fixed official HTTPS endpoints. Refuse redirects.
    from urllib.request import build_opener
    req=Request(url,headers={'Authorization':'Bearer '+key,'Accept':'application/json','User-Agent':'API-Traffic-Dashboard/1.0'})
    with build_opener(NoRedirect()).open(req,timeout=15) as r: return json.load(r)

def pages(path,key,params):
    results=[]; seen=set()
    for _ in range(100):
        data=remote('https://api.openai.com/v1/organization/'+path+'?'+urlencode(params,doseq=True),key)
        results.extend(data.get('data',[]))
        if not data.get('has_more'): return results
        cursor=data.get('next_page')
        if not cursor or cursor in seen: raise ValueError('上游分页游标无效')
        seen.add(cursor); params={**params,'page':cursor}
    raise ValueError('分页超过上限，请缩短同步日期范围')

def sync_one(provider, cfg):
    key=cfg[{'deepseek':'deepseek_api_key','kimi':'kimi_api_key','openai':'openai_admin_key'}[provider]]
    if not configured(key): return {'status':'unconfigured','message':'请在 config/settings.json 填写密钥'}
    stamp=now().isoformat()
    try:
        if provider=='deepseek':
            d=remote('https://api.deepseek.com/user/balance',key)
            balances=[{'amount':str(b['total_balance']),'currency':b['currency']} for b in d['balance_infos']]
            result={'status':'ok','message':'余额已同步；Token 用量来自调用记录','balances':balances}
        elif provider=='kimi':
            d=remote('https://api.moonshot.cn/v1/users/me/balance',key)
            if not d.get('status',True): raise ValueError('余额接口未返回成功状态')
            result={'status':'ok','message':'余额已同步；Token 用量来自调用记录','balances':[{'amount':str(d['data']['available_balance']),'currency':'CNY'}]}
        else:
            end=now().astimezone(timezone.utc)
            start=(now()-timedelta(days=max(1,min(90,int(cfg.get('sync_days',30)))))).astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
            params={'start_time':int(start.timestamp()),'end_time':int(end.timestamp()),'bucket_width':'1d','limit':31}
            buckets=pages('usage/completions',key,{**params,'group_by[]':['model','project_id']})
            events=[]
            for bucket in buckets:
                for r in bucket.get('results',[]):
                    identity=json.dumps([bucket['start_time'],r.get('model'),r.get('project_id')])
                    e=dict(id='openai:official:'+hashlib.sha256(identity.encode()).hexdigest(),provider='openai',model=r.get('model') or 'unknown',project=r.get('project_id') or 'organization',
                           time=datetime.fromtimestamp(bucket['start_time'],TZ).isoformat(),input_tokens=r.get('input_tokens'),output_tokens=r.get('output_tokens'),cached_tokens=r.get('input_cached_tokens'),requests=r.get('num_model_requests',0),source='official',cost=None,currency=None)
                    events.append(e)
            # Replace snapshot scope atomically. Never sum official and local logs.
            with connect() as c:
                c.execute("DELETE FROM events WHERE source='official' AND time>=? AND time<?",(start.astimezone(TZ).isoformat(),end.astimezone(TZ).isoformat()))
                put_events(events,c)
            result={'status':'ok','message':'已同步 OpenAI 官方 completions 用量；按 UTC 日桶','coverage_start':start.isoformat(),'coverage_end':end.isoformat()}
            try:
                costs=pages('costs',key,params.copy())
                amounts={}
                for b in costs:
                    for r in b.get('results',[]):
                        a=r.get('amount') or {}; currency=a.get('currency','usd').upper()
                        amounts[currency]=str(Decimal(amounts.get(currency,'0'))+Decimal(str(a.get('value',0))))
                result['billing']={'start':start.isoformat(),'end':end.isoformat(),'amounts':amounts,'note':'组织全部产品费用，可能包含非 completions 产品；不与估算相加'}
            except (HTTPError,URLError,ValueError,KeyError,TimeoutError): result['billing_error']='用量同步成功，官方费用同步失败或权限不足'
        result['synced_at']=stamp
        return result
    except HTTPError as ex:
        return {'status':'error','message':f'官方接口 HTTP {ex.code}；请检查密钥权限、配额与端点可用性','attempted_at':stamp}
    except (URLError,TimeoutError,OSError):
        return {'status':'error','message':'无法连接官方接口，请检查网络后重试','attempted_at':stamp}
    except (ValueError,KeyError,TypeError,InvalidOperation):
        return {'status':'error','message':'上游数据格式或配置不符合预期，请核查官方文档与本地配置','attempted_at':stamp}

def sync_all():
    if not SYNC_LOCK.acquire(blocking=False): return {'busy':True}
    try:
        cfg=config()
        for p in PROVIDERS:
            result=sync_one(p,cfg)
            old=state(p,{})
            if result['status']=='error':
                for k in ('balances','billing','synced_at'): 
                    if k in old: result[k]=old[k]
            if result.get('billing_error') and 'billing' in old:
                result['billing']=old['billing']
            save_state(p,result)
        return {'ok':True}
    finally: SYNC_LOCK.release()

def scheduler():
    while True:
        try: sync_all()
        except (OSError,ValueError,KeyError): pass
        try: minutes=max(5,int(config().get('sync_interval_minutes',30)))
        except (OSError,ValueError): minutes=30
        threading.Event().wait(minutes*60)

def demo_events():
    rng=random.Random(42); rows=[]
    for days in range(35):
        day=now().replace(hour=12,minute=0,second=0,microsecond=0)-timedelta(days=days)
        for idx,(p,m) in enumerate([('deepseek','deepseek-chat'),('deepseek','deepseek-reasoner'),('kimi','kimi-k2'),('openai','gpt-4.1'),('openai','codex-api-demo')]):
            inp=rng.randint(35000,260000); out=rng.randint(8000,70000)
            rows.append(dict(id=f'demo-{days}-{idx}',provider=p,model=m,project=['个人编程','研究助手','内容工作流'][idx%3],time=day.isoformat(),input_tokens=inp,output_tokens=out,cached_tokens=inp//3,requests=rng.randint(20,130),source='logs',cost=str(Decimal(inp+out)*Decimal('0.000006')),currency='CNY'))
    return rows

def snapshot(query):
    cfg=config(); mode=query.get('mode',['demo'])[0]
    source=query.get('source',['logs'])[0]
    if source not in ('logs','official'): raise ValueError('无效数据来源')
    start=query.get('start',[(now()-timedelta(days=29)).date().isoformat()])[0]
    end=query.get('end',[now().date().isoformat()])[0]
    a=datetime.strptime(start,'%Y-%m-%d').date(); b=datetime.strptime(end,'%Y-%m-%d').date()
    if a>b or (b-a).days>366: raise ValueError('请选择不超过 366 天的有效日期范围')
    if mode=='demo': rows=demo_events() if source=='logs' else []
    elif mode=='live':
        with connect() as c: rows=[dict(r) for r in c.execute('SELECT * FROM events WHERE source=? AND time>=? AND time<? ORDER BY time DESC',(source,start,(b+timedelta(days=1)).isoformat()))]
    else: raise ValueError('无效模式')
    provider=query.get('provider',['all'])[0]; model=query.get('model',['all'])[0]; project=query.get('project',['all'])[0]
    options={k:sorted(set(r[k] for r in rows)) for k in ('model','project')}
    rows=[r for r in rows if start<=r['time'][:10]<=end and (provider=='all' or r['provider']==provider) and (model=='all' or r['model']==model) and (project=='all' or r['project']==project)]
    rows.sort(key=lambda e:e['time'],reverse=True)
    return {'mode':mode,'source':source,'start':start,'end':end,'events':rows,'options':options,'budget':state('budget',cfg['monthly_budget_cny']), 'usd_to_cny':cfg['usd_to_cny'],'exchange_rate_note':cfg['exchange_rate_note'],
            'accounts':{p:({'status':'demo','message':'演示账户 · 非真实余额','balances':[{'amount':str(260+i*100),'currency':'CNY'}]} if mode=='demo' else {**state(p,{'status':'unconfigured','message':'尚未同步'}),'configured':configured(cfg[{'deepseek':'deepseek_api_key','kimi':'kimi_api_key','openai':'openai_admin_key'}[p]])}) for i,p in enumerate(PROVIDERS)},
            'config_path':str(CONFIG),'timezone':'Asia/Shanghai','generated_at':now().isoformat()}

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)
    def log_message(self,*args): pass
    def respond(self,code,data,mime='application/json; charset=utf-8',extra=None):
        body=json.dumps(data,ensure_ascii=False).encode() if mime.startswith('application/json') else data
        self.send_response(code)
        for k,v in {'Content-Type':mime,'Content-Length':str(len(body)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",**(extra or {})}.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def local_request(self,write=False):
        host=self.headers.get('Host','')
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if host not in allowed: return False
        origin=self.headers.get('Origin')
        if origin and origin not in {'http://'+h for h in allowed}: return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site': return False
        return not write or self.headers.get('Content-Type','').split(';')[0]=='application/json'
    def do_GET(self):
        if not self.local_request(): return self.respond(403,{'error':'仅允许本机同源访问'})
        path=urlparse(self.path).path; q=parse_qs(urlparse(self.path).query)
        try:
            if path=='/api/dashboard': return self.respond(200,snapshot(q))
            if path=='/api/export':
                rows=snapshot(q)['events']; f=io.StringIO(); w=csv.writer(f); w.writerow(COLUMNS)
                for r in rows:
                    # Neutralize spreadsheet formulas in user-provided labels.
                    w.writerow([("'"+str(r.get(k))) if str(r.get(k,'')).startswith(('=','+','-','@','\t','\r')) else r.get(k) for k in COLUMNS])
                return self.respond(200,('\ufeff'+f.getvalue()).encode(),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="api-usage.csv"'})
            files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
            if path not in files: return self.respond(404,{'error':'未找到资源'})
            mime={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path]
            return self.respond(200,(ROOT/'public'/files[path]).read_bytes(),mime)
        except (ValueError,KeyError,InvalidOperation): return self.respond(400,{'error':'日期、筛选参数或配置无效'})
    def do_POST(self):
        if not self.local_request(True): return self.respond(403,{'error':'仅允许本机同源 JSON 请求'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=2_000_000: return self.respond(413,{'error':'请求体应为 1–2000000 字节'})
            body=json.loads(self.rfile.read(size))
            path=urlparse(self.path).path
            if path=='/api/sync': return self.respond(200,sync_all())
            if path=='/api/events': return self.respond(200,{'inserted':ingest(body['events'])})
            if path=='/api/budget':
                amount=Decimal(str(body['amount']))
                if not amount.is_finite() or not 0<amount<=Decimal('100000000'): raise ValueError('预算应为大于 0 的有限金额')
                save_state('budget',str(amount)); return self.respond(200,{'ok':True})
            return self.respond(404,{'error':'未找到接口'})
        except (ValueError,KeyError,TypeError,InvalidOperation) as ex:
            return self.respond(400,{'error':'输入无效：请检查 JSON、Token 数值、时间与配置'})

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8787); args=parser.parse_args()
    init(); config()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    threading.Thread(target=scheduler,daemon=True).start()
    print(f'API 流量看板：http://127.0.0.1:{args.port}\n密钥配置：{CONFIG}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
