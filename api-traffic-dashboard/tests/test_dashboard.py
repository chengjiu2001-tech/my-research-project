import sys, tempfile, unittest, threading, json
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen, Request
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as app

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old_db=app.DB;app.DB=Path(self.tmp.name)/'test.db';app.init()
        self.cfg=app.config();self.mock=patch.object(app,'config',return_value=self.cfg);self.mock.start()
    def tearDown(self):
        self.mock.stop();app.DB=self.old_db;self.tmp.cleanup()
    def event(self,**kw):
        return dict(id='req-1',provider='deepseek',model='model-a',project='test',time=app.now().isoformat(),input_tokens=100,output_tokens=20,cached_tokens=30,**kw)
    def test_atomic_import_and_idempotency(self):
        self.assertEqual(app.ingest([self.event()]),1)
        self.assertEqual(app.ingest([self.event()]),0)
        bad=self.event();bad['cached_tokens']=101
        good=self.event();good['id']='req-2'
        with self.assertRaises(ValueError):app.ingest([good,bad])
        with app.connect() as c:self.assertEqual(c.execute('select count(*) from events').fetchone()[0],1)
    def test_price_versions_and_cache_included(self):
        self.cfg['prices']=[dict(provider='deepseek',model='model-a',effective_from='2020-01-01',input_per_million='2',output_per_million='4',cache_read_per_million='1',currency='CNY'),dict(provider='deepseek',model='model-a',effective_from='2099-01-01',input_per_million='99',output_per_million='99',cache_read_per_million='99',currency='CNY')]
        self.assertEqual(app.normalize(self.event(),self.cfg)['cost'],'0.00025')
        raw=self.event();raw['cached_tokens']=None
        self.assertIsNone(app.normalize(raw,self.cfg)['cost'])
    def test_demo_does_not_pollute_live(self):
        self.assertTrue(app.snapshot({'mode':['demo']})['events'])
        self.assertEqual(app.snapshot({'mode':['live']})['events'],[])
        with app.connect() as c:self.assertEqual(c.execute('select count(*) from events').fetchone()[0],0)
    def test_unknown_usage_preserved(self):
        raw=self.event();raw['cached_tokens']=None;raw['input_tokens']=None
        app.ingest([raw]);record=app.snapshot({'mode':['live']})['events'][0]
        self.assertIsNone(record['input_tokens']);self.assertIsNone(record['cached_tokens']);self.assertIsNone(record['cost'])
    def test_official_and_logs_never_sum(self):
        app.ingest([self.event()]);e=app.normalize(self.event(),self.cfg);e.update(id='official',source='official')
        with app.connect() as c:app.put_events([e],c)
        self.assertEqual(len(app.snapshot({'mode':['live'],'source':['logs']})['events']),1)
        self.assertEqual(len(app.snapshot({'mode':['live'],'source':['official']})['events']),1)
    def test_pagination_and_query(self):
        with patch.object(app,'remote',side_effect=[{'data':[1],'has_more':True,'next_page':'abc'},{'data':[2],'has_more':False}]) as remote:
            self.assertEqual(app.pages('usage/completions','x',{'group_by[]':['model','project_id']}),[1,2])
            self.assertIn('page=abc',remote.call_args[0][0]);self.assertIn('group_by%5B%5D=model',remote.call_args[0][0])
    def test_official_snapshot_refresh(self):
        self.cfg['openai_admin_key']='test-only'
        bucket=int((app.now()-app.timedelta(days=1)).timestamp())
        def fake(n):return [{'start_time':bucket,'results':[{'model':'m','project_id':'p','input_tokens':n,'output_tokens':5,'input_cached_tokens':0,'num_model_requests':1}]}]
        for n in [100,200]:
            with patch.object(app,'pages',side_effect=[fake(n),[]]):self.assertEqual(app.sync_one('openai',self.cfg)['status'],'ok')
        result=app.snapshot({'mode':['live'],'source':['official']})['events'];self.assertEqual(len(result),1);self.assertEqual(result[0]['input_tokens'],200)
    def test_no_network_when_keys_placeholders(self):
        with patch.object(app,'remote') as remote:
            app.sync_all();remote.assert_not_called()
    def test_http_privacy_and_mutations(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/api/dashboard?mode=live') as r:self.assertNotIn('YOUR_DEEPSEEK_API_KEY',r.read().decode())
            for path in ['/config/settings.json','/server.py','/data/usage.sqlite3','/../config/settings.json']:
                with self.assertRaises(HTTPError) as ex:urlopen(base+path)
                self.assertEqual(ex.exception.code,404)
            for amount in ['NaN','Infinity','-10']:
                req=Request(base+'/api/budget',data=json.dumps({'amount':amount}).encode(),headers={'Content-Type':'application/json'})
                with self.assertRaises(HTTPError) as ex:urlopen(req)
                self.assertEqual(ex.exception.code,400)
            req=Request(base+'/api/budget',data=b'{"amount":900}',headers={'Content-Type':'application/json','Origin':'https://evil.example'})
            with self.assertRaises(HTTPError) as ex:urlopen(req)
            self.assertEqual(ex.exception.code,403)
            req=Request(base+'/api/budget',data=b'{"amount":900}',headers={'Content-Type':'application/json'})
            with urlopen(req) as r:self.assertTrue(json.load(r)['ok'])
            self.assertEqual(app.state('budget'),'900')
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
