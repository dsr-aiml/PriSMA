import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
from sqlalchemy import select

from app import public_files
from app.collection import TinyFishCollector
from app.models import Evidence, Investigation, Question, User
from app.source_semantics import visible_report
from app.web_observation import append_response, new_snapshot, safe_url, shape, signatures
from test_baseline import register
from test_document_intelligence import run


def test_shipped_markers_require_structural_content_not_marketing():
    assert signatures('We migrated from React, PHP and Next.js', 'https://example.com/docs', 'text/plain') == []
    found = signatures('<script src="/_next/static/app.js"></script>', 'https://example.com', 'text/html', {'x-vercel-id': 'edge-id'})
    assert {row['name'] for row in found} == {'Next.js','Vercel'}
    assert shape({'token':'secret-value','rows':[{'id':1,'active':True}]}) == {'token':'string','rows':[{'id':'number','active':'boolean'}]}
    assert 'secret-value' not in safe_url('https://example.com/items?token=secret-value&limit=2')


def test_observation_import_maps_delivery_without_inventing_private_storage(context):
    client,_,_ = context
    register(client)
    snapshot = new_snapshot('https://example.com')
    append_response(snapshot,'https://example.com','https://example.com','text/html',{'server':'nginx'},200,'<script src="/_next/static/app.js"></script>')
    snapshot['resources']=[{'url':'https://example.com/_next/static/app.js','kind':'script'},{'url':'https://example.com/style.css','kind':'stylesheet'}]
    append_response(snapshot,'https://api.example.com/items','https://api.example.com/items','application/json',{},200,resource_type='fetch')
    snapshot['responses'][-1]['response_shape']={'items':[{'id':'number'}]}
    _,detail = run(client,[{'title':'Observation','origin':'local:observations/page.json','format':'json','content':json.dumps(snapshot,indent=2)}])
    report=detail['report']
    assert {row['name'] for row in report['technologies']} == {'Next.js','NGINX'}
    assert len(report['nodes']) >= 5 and len(report['edges']) >= 4
    assert all(row['name'].startswith('Response ') for row in report['entities'])
    assert all(claim.get('attributes', {}).get('schema_role') == 'observed_response' for claim in report['claims'] if claim['type'] in {'entity', 'field'})
    assert len(report['api_endpoints']) == 1
    endpoint=report['api_endpoints'][0]
    assert endpoint['contract_basis']=='observed_response' and endpoint['response_shape']=={'items':[{'id':'number'}]}
    sources={e['id']:e for e in detail['evidence']}
    for claim in report['claims']:
        for citation in claim['citations']:
            assert sources[citation['evidence_id']]['content'][citation['start']:citation['end']]==citation['quote']


def test_static_collection_captures_headers_and_bounded_assets(context,monkeypatch):
    client,factory,_=context
    register(client)
    called=[]
    def read(url,**kwargs):
        kwargs['before_request']()
        called.append(url)
        if url.endswith('/app.js'):
            return b'Symbol.for("react.transitional.element");',url,'application/javascript',{},200
        if url.endswith('/style.css'):
            return b'/* Bootstrap v5.3.0 */ body { margin: 0; }',url,'text/css',{},200
        return b'<html><body><script src="/app.js"></script><link rel="stylesheet" href="/style.css"></body></html>',url,'text/html',{'x-vercel-id':'region-id'},200
    monkeypatch.setattr(public_files,'read_public',read)
    with factory() as db:
        collector=TinyFishCollector(db,db.scalar(select(User)).id,budget=object(),options={'direct_read_limit':3})
        records=[]
        collector.collect_public_files('https://example.com/','example.com',records,set(),lambda *_:None)
        assert len(called)==3 and collector.record['public_files']['requests']==3
        assert not any(url.endswith('.css') for url in called)
        observation=next(row for row in records if row[2]['collection_method']=='public_observation')
        data=json.loads(observation[1])
        assert {row['name'] for row in data['signals']} >= {'Vercel','React'}
        assert len(data['responses'])==3
        assert any(row['kind']=='stylesheet' for row in data['resources'])
        assert collector.record['url_attempts']==0 and collector.record['search_attempts']==0


def test_browser_failure_retains_existing_sources(context,monkeypatch):
    from app import web_observation
    client,factory,_=context
    register(client)
    def unavailable(*args):
        raise httpx.ConnectError('observer offline')
    monkeypatch.setattr(web_observation,'collect_browser',unavailable)
    with factory() as db:
        collector=TinyFishCollector(db,db.scalar(select(User)).id,budget=object())
        source=SimpleNamespace(content='Retained architecture',origin='https://example.com')
        rows=[(source,source.content,{})]
        collector.collect_browser_observation('https://example.com',rows,set(),lambda *_:None)
        assert rows[0][0] is source and len(rows)==1
        assert collector.record['browser']['status']=='unavailable'
        assert collector.record['status']=='partial'


def test_history_and_hashes_do_not_pollute_current_stack_or_capability(context):
    client,_,_=context
    register(client)
    readme='# Project\n## Tech Stack\n- React\n## Features\n- Stream document exports (db675f1)\n- Modern table rendering (remark-gfm)\n'
    history='# Changelog\n## Features\n- Changed the build compiler (cc39fc5)\n'
    _,detail=run(client,[{'title':'README','origin':'local:README.md','content':readme},{'title':'Changelog','origin':'local:CHANGELOG.md','content':history}])
    assert {row['name'] for row in detail['report']['technologies']}=={'React','remark-gfm'}
    assert len(detail['report']['features'])==2
    assert all(row['commercial_scope']=='not_specified' for row in detail['report']['features'])


def test_old_report_projection_is_read_only_and_exports_match(context):
    client,factory,_=context
    register(client)
    identifier,detail=run(client,[{'title':'Declaration','origin':'local:README.md','content':'## Features\n- Document export with metadata\n'}])
    with factory() as db:
        inv=db.get(Investigation,identifier)
        e=db.scalar(select(Evidence).where(Evidence.investigation_id==identifier))
        claim=deepcopy(inv.report['claims'][0]);claim.update(id='bad-hash',type='technology',description='db675f1')
        report=deepcopy(inv.report);report['claims'].append(claim);report['technologies'].append({'id':'bad-tech','name':'db675f1','category':'documented_capability','claim_id':'bad-hash','claim_ids':['bad-hash'],'declarations':[{'group':'documented_capability','claim_id':'bad-hash','version':''}]})
        original=deepcopy(report)
        assert visible_report(report,[e])['technologies']==[] and report==original
        inv.report=report;db.commit()
    assert client.get(f'/investigations/{identifier}').json()['report']['technologies']==[]
    export=client.get(f'/investigations/{identifier}/export/json').json()
    assert export['report']['technologies']==[] and export['report']['presentation_exclusions']
    with factory() as db:
        assert db.get(Investigation,identifier).report==original


def test_reference_uses_shared_parsers_without_rows_jobs_or_question_history(context):
    client,factory,queued=context
    register(client)
    first=client.get('/reference').json()
    assert first['report']['repository']['modules'] and first['report']['features']
    assert first['report']['run']['provider']=='rules'
    assert first['events']==[]
    response=client.post('/reference/standard/questions',json={'question':'Which technologies are declared and what roles do they serve?'}).json()
    assert response['status']=='completed' and response['answer']['findings']
    assert client.get('/reference').json()['report']==first['report']
    assert queued==[]
    with factory() as db:
        assert list(db.scalars(select(Investigation)))==[]
        assert list(db.scalars(select(Evidence)))==[]
        assert list(db.scalars(select(Question)))==[]


def test_pricing_comparison_maps_only_explicit_terms(context):
    client,_,_=context
    register(client)
    text='# Subscription plans\n| Feature | Free | Business |\n| --- | --- | --- |\n| Audit history | Not included | Included |\n| Workspaces | Up to 3 workspaces | Unlimited |\n| Unsettled option | Contact us | Maybe |\n'
    _,detail=run(client,[{'title':'Pricing','origin':'local:pricing.md','content':text}])
    features=detail['report']['features']
    assert len(features)==4
    assert {row['tier'] for row in features}=={'Free','Business'}
    assert all(row['commercial_scope']=='declared' for row in features)
    assert next(row for row in features if row['tier']=='Free' and row['feature']=='Workspaces')['limitation']=='Up to 3 workspaces'


def test_malformed_observation_contract_does_not_abort_other_documents(context):
    client,_,_=context
    register(client)
    malformed={'contract':'prisma.public-observation.v1','url':'https://example.com','responses':None,'resources':[],'signals':[]}
    _,detail=run(client,[{'title':'Broken observation','origin':'local:observation.json','format':'json','content':json.dumps(malformed)}, {'title':'Manifest','origin':'local:package.json','content':json.dumps({'name':'project','dependencies':{'react':'19.1.0'}})}])
    assert detail['status']=='completed' and {row['name'].casefold() for row in detail['report']['technologies']}=={'react'}


def test_har_assets_are_delivery_evidence_not_api_operations(context):
    client,_,_=context
    register(client)
    capture={'log':{'entries':[{'request':{'method':'GET','url':url},'response':{'status':200,'content':{'mimeType':mime}}} for url,mime in [('https://example.com/app.js','application/javascript'),('https://example.com/photo.png','image/png'),('https://example.com/orders','application/json')]]}}
    _,detail=run(client,[{'title':'Traffic','origin':'local:network.har','format':'json','content':json.dumps(capture)}])
    assert [row['path'] for row in detail['report']['api_endpoints']]==['/orders']


def test_browser_routes_use_pinned_reads_and_block_credentials_and_side_effects(monkeypatch):
    import asyncio
    import importlib.util
    import sys
    from pathlib import Path
    from types import ModuleType
    from unittest.mock import AsyncMock
    from app.public_files import PublicFileError

    calls, fulfilled, aborted = [], [], []
    class Route:
        def __init__(self, url, kind='script', method='GET'):
            self.request = SimpleNamespace(url=url, resource_type=kind, method=method, headers={'Cookie':'private-session', 'Authorization':'secret'})
        async def abort(self): aborted.append(self.request.url)
        async def fulfill(self, **kwargs): fulfilled.append((self.request.url, kwargs))
    class Session:
        async def send(self, *args): pass
        def on(self, event, callback): self.callback = callback
    session = Session()
    class Page:
        url = 'https://example.com/'
        def on(self, *args): pass
        async def goto(self, url, **kwargs):
            self.url = url
            await context.callback(Route(url, 'document'))
            for route in [Route('https://example.com/orders','fetch'), Route('https://cdn.example.com/app.js'), Route('http://127.0.0.1/secret','fetch'), Route('https://example.com/logout','fetch','POST'), Route('https://example.com/photo.png','image')]:
                session.callback({'request': {'url': route.request.url, 'method': route.request.method}, 'initiator': {'type':'script', 'stack':{'callFrames':[{'url':'https://cdn.example.com/app.js','lineNumber':10,'columnNumber':2}]}}, 'requestId':'captured'})
                await context.callback(route)
        def locator(self, *args): return SimpleNamespace(count=AsyncMock(return_value=0))
        async def wait_for_timeout(self, *args): await asyncio.sleep(0)
        async def evaluate(self, *args): return '<html><body>Rendered public document</body></html>'
        async def title(self): return 'Public page'
    class Context:
        def set_default_timeout(self, *args): pass
        async def route_web_socket(self, *args): pass
        async def route(self, pattern, callback): self.callback = callback
        async def new_page(self): return Page()
        async def new_cdp_session(self, page): return session
        def on(self, *args): pass
        async def close(self): pass
    context = Context()
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    chromium = SimpleNamespace(launch=AsyncMock(return_value=browser))
    class Runtime:
        async def __aenter__(self): return SimpleNamespace(chromium=chromium)
        async def __aexit__(self, *args): pass
    fake = ModuleType('playwright.async_api'); fake.Error = RuntimeError; fake.TimeoutError = RuntimeError; fake.async_playwright = Runtime
    monkeypatch.setitem(sys.modules, 'playwright', ModuleType('playwright'))
    monkeypatch.setitem(sys.modules, 'playwright.async_api', fake)
    path = Path(__file__).resolve().parents[2]/'browser/service.py'
    spec = importlib.util.spec_from_file_location('prisma_test_observer', path)
    observer = importlib.util.module_from_spec(spec); spec.loader.exec_module(observer)
    def read(url, **kwargs):
        assert 'headers' not in kwargs and 'cookies' not in kwargs
        calls.append(url); kwargs['before_request']()
        if '127.0.0.1' in url: raise PublicFileError('Non-public target address.')
        if url.endswith('/orders'): return b'{"token":"secret-value","items":[{"id":1}]}',url,'application/json',{},200
        if url.endswith('.js'): return b'Symbol.for("react.transitional.element"); fetch("/orders");',url,'application/javascript',{},200
        return b'<html><script src="https://cdn.example.com/app.js"></script></html>','https://example.com/','text/html',{},200
    monkeypatch.setattr(observer, 'read_public', read)
    result = asyncio.run(observer.capture(observer.Observation(url='http://example.com/',external_resources=True)))
    assert calls.count('http://example.com/') == 1 and 'https://example.com/' not in calls
    assert 'https://example.com/logout' not in calls and 'https://example.com/photo.png' not in calls
    assert 'http://127.0.0.1/secret' in aborted and 'https://example.com/logout' in aborted
    assert chromium.launch.call_args.kwargs['chromium_sandbox'] is True
    assert chromium.launch.call_args.kwargs['proxy']['server'] == 'http://127.0.0.1:9'
    assert browser.new_context.call_args.kwargs['service_workers'] == 'block'
    assert result['snapshot']['coverage']['status'] == 'partial'
    assert 'secret-value' not in json.dumps(result['snapshot'])
    assert all('set-cookie' not in row[1]['headers'] for row in fulfilled)
    observed = next(row for row in result['snapshot']['responses'] if row['url'].endswith('/orders'))
    assert observed['initiator']['url'] == 'https://cdn.example.com/app.js' and observed['response_shape']['token'] == 'string'
    assert result['scripts'][0]['content'].endswith('fetch("/orders");')
    browser.close.assert_awaited_once()


def test_html_framework_examples_are_not_shipped_markers():
    example='<html><pre>&lt;script src="/_next/static/app.js"&gt;&lt;/script&gt;</pre><p>react.element __NUXT__</p><script type="application/ld+json">{"example":"react.transitional.element"}</script></html>'
    assert signatures(example,'https://example.com/docs','text/html')==[]
    angular='<html><main ng-version="20.1.0"></main><script>self.__next_f.push([]);</script></html>'
    assert {row['name'] for row in signatures(angular,'https://example.com','text/html')}=={'Angular','Next.js'}
