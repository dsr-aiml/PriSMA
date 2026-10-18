import csv
import io
import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app import jobs, model_gateway as gateway, web_observation
from app.collection import TinyFishCollector
from app.exports import evidence_matrix_csv
from app.models import Evidence, Investigation, Question, User, now
from app.public_code import public_code_facts, inline_sources, source_map_sources
from app.schemas import ImportedSource
from app.source_analysis import prepare_source
from app.traffic_intake import sanitize_har
from test_baseline import register
from test_document_intelligence import run
from test_saved_sources import imported


def test_browser_bodies_and_indexed_source_maps_reach_saved_analysis(context, monkeypatch):
    client, factory, _ = context
    register(client)
    url = 'https://independent.example/'
    snapshot = web_observation.new_snapshot(url, 'chromium_public_pages')
    web_observation.append_response(snapshot, url, url, 'text/html', {}, 200, '<html>Public site</html>')
    snapshot['coverage'] = {'status': 'partial', 'pages': 2, 'requests': 4}
    source_map = {'version': 3, 'sections': [{'offset': {'line': 0, 'column': 0}, 'map': {'version': 3, 'sources': ['src/app.ts', '../credentials.json', 'node_modules/lib/index.js'], 'sourcesContent': ['export const app = 1;', 'secret', 'dependency']}}]}
    monkeypatch.setattr(web_observation, 'collect_browser', lambda *args: {'snapshot': snapshot, 'pages': [{'url': url, 'html': '<html><h1>Independent application</h1><script>fetch("/api/records")</script></html>', 'title': 'Independent app'}], 'scripts': [{'url': url + 'app.js', 'page_url': url, 'content': 'fetch("/api/records"); axios.post("https://api.independent.example/events", {});'}], 'source_maps': [{'url': url + 'app.js.map', 'content': json.dumps(source_map)}]})
    with factory() as db:
        collector = TinyFishCollector(db, db.scalar(select(User)).id, budget=object(), options={'browser_page_limit': 2})
        sources = []
        collector.collect_browser_observation(url, sources, set(), lambda *_: None)
        assert collector.record['browser']['analysis_retained'] == {'pages': 1, 'scripts': 2, 'source_map_modules': 1}
        script = next(source for source, _, meta in sources if source.origin.endswith('app.js'))
        facts = list(public_code_facts(SimpleNamespace(id='script', source_url=script.origin, content=script.content, source_type='javascript', signals={'collection_method': 'browser_script', 'public_page': url})))
        assert {(row['method'], row['path']) for row in facts if row['kind'] == 'endpoint'} == {('GET', '/api/records'), ('POST', '/events')}
        assert all(script.content[row['offset']:row['offset'] + len(row['quote'])] == row['quote'] for row in facts)
        assert not any(source.content == 'secret' or source.content == 'dependency' for source, _, _ in sources)


def test_dynamic_fetch_method_is_not_invented_and_prose_is_not_client_code():
    text = 'fetch("/dynamic", options); fetch("/known", {method: "PATCH"}); new WebSocket("wss://socket.independent.example/events");'
    item = SimpleNamespace(id='client', source_url='https://independent.example/main.js', source_type='javascript', content=text, signals={'collection_method': 'browser_script', 'public_page': 'https://independent.example/'})
    facts = list(public_code_facts(item))
    assert [(f['method'], f['path']) for f in facts if f['kind'] == 'endpoint'] == [('PATCH', '/known')]
    assert any(f['attributes']['transport'] == 'websocket' for f in facts)
    item.signals = {}
    assert list(public_code_facts(item)) == []


def test_observed_shapes_attempts_and_initiators_are_distinct(context):
    client, _, _ = context
    register(client)
    snapshot = web_observation.new_snapshot('https://unrelated.example/', 'chromium_public_pages')
    web_observation.append_response(snapshot, snapshot['url'], snapshot['url'], 'text/html', {}, 200, '<html>Application</html>')
    web_observation.append_response(snapshot, 'https://unrelated.example/api/list', 'https://unrelated.example/api/list', 'application/json', {}, 200, '', 'fetch')
    snapshot['responses'][-1].update(response_shape={'items': [{'id': 'number'}], 'total': 'number'}, page_url=snapshot['url'], initiator={'type': 'script', 'url': 'https://unrelated.example/main.js'})
    snapshot['coverage'] = {'blocked': [{'url': 'https://unrelated.example/api/checkout', 'method': 'POST', 'resource_type': 'fetch'}]}
    _, detail = run(client, [{'title': 'Observed traffic', 'origin': 'local:traffic.json', 'format': 'json', 'content': json.dumps(snapshot)}])
    report = detail['report']
    assert {row['path'] for row in report['api_endpoints']} == {'/api/list', '/api/checkout'}
    attrs = [row.get('attributes', {}) for row in report['claims']]
    assert any(row.get('contract_basis') == 'observed_response' for row in attrs)
    assert any(row.get('contract_basis') == 'observed_request_attempt' and row['executed'] is False for row in attrs)
    assert {f['name'] for f in report['fields']} == {'items', 'total'}
    assert any(row['title'] == 'Client request trace' for row in detail['analysis']['insights'])
    source = detail['evidence'][0]['content']
    assert all(source[c['start']:c['end']] == c['quote'] for claim in report['claims'] for c in claim['citations'])


def test_har_sanitization_precedes_storage_and_remains_idempotent(context):
    client, _, _ = context
    register(client)
    raw = {'log': {'entries': [{'request': {'method': 'POST', 'url': 'https://other.example/api/items?token=secret-token&email=private@example.com', 'headers': [{'name': 'Authorization', 'value': 'Bearer secret-header'}], 'cookies': [{'value': 'private-cookie'}], 'postData': {'mimeType': 'application/json', 'text': '{"name":"customer-name"}'}}, 'response': {'status': 200, 'headers': [{'name': 'Set-Cookie', 'value': 'private-cookie'}], 'content': {'mimeType': 'application/json', 'text': '{"token":"response-secret","items":[{"id":12}]}'}}}]}}
    first = sanitize_har(raw)
    assert sanitize_har(first) == first
    source, _ = prepare_source(ImportedSource(title='Traffic', origin='local:network.har', format='json', content=json.dumps(raw)))
    assert not any(value in source.content for value in ['secret-token', 'private@example.com', 'secret-header', 'private-cookie', 'customer-name', 'response-secret'])
    _, detail = run(client, [source.model_dump()])
    assert all(not any(value in json.dumps(e) for value in ['secret-token', 'private@example.com', 'response-secret']) for e in detail['evidence'])
    assert detail['report']['api_endpoints'][0]['path'] == '/api/items'


def test_inline_hydration_retains_shape_not_values():
    rows = list(inline_sources('<script id="state" type="application/json">{"session":"private-value","count":4}</script><script>fetch("/api/status")</script>', 'https://app.example/'))
    assert len(rows) == 2 and 'private-value' not in rows[0][0].content
    assert json.loads(rows[0][0].content)['shape'] == {'session': 'string', 'count': 'number'}


def test_matrix_export_is_complete_grouped_and_spreadsheet_safe(context):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    response = client.get(f'/investigations/{identifier}/export/matrix')
    assert response.status_code == 200 and response.headers['content-type'].startswith('text/csv')
    rows = list(csv.reader(io.StringIO(response.text.lstrip('\ufeff'))))
    detail = client.get(f'/investigations/{identifier}').json()
    assert len(rows) - 1 == len(detail['report']['claims'])
    assert len(rows[0]) - 6 == len({e['content_hash'] or e['id'] for e in detail['evidence']})
    with factory() as db:
        inv = db.get(Investigation, identifier)
        evidence = list(db.scalars(select(Evidence).where(Evidence.investigation_id == identifier)))
        claim = dict(inv.report['claims'][0], description='=HYPERLINK("bad")', confidence=0, supporting_evidence_ids=[evidence[0].id], contradicting_evidence_ids=['mirror'])
        inv.report = {**inv.report, 'claims': [claim]}
        mirror = SimpleNamespace(**{key:getattr(evidence[0],key) for key in ('content_hash','signals','source_url','source_type','content','collection_method')}, id='mirror')
        csv_rows = list(csv.reader(io.StringIO(evidence_matrix_csv(inv, [evidence[0], mirror]).lstrip('\ufeff'))))
        assert csv_rows[1][3].startswith("'=") and csv_rows[1][5] == '0' and csv_rows[1][6] == 'Both'
    assert client.get('/reference/standard/export/matrix').status_code == 200
    client.post('/auth/logout')
    assert client.get(f'/investigations/{identifier}/export/matrix').status_code == 401


def test_markdown_is_reader_oriented_without_new_provider_calls(context, monkeypatch):
    client, _, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    monkeypatch.setattr(gateway, 'generate', lambda *a: pytest.fail('Export must not generate'))
    text = client.get(f'/investigations/{identifier}/export/markdown').text
    assert '# Architecture assessment:' in text
    assert all(title in text for title in ['## Executive summary', '## Technology profile', '## Finding register', '## Source register'])
    assert text.count('**Scope.**') == 1
    assert 'Classification:' not in text and '```json' not in text


@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_research_provider_outage_is_private_and_bounded(monkeypatch, hosted_query, status):
    from app.model_profiles import snapshot, using
    from app import research_budget
    monkeypatch.setattr(research_budget,"admit",lambda *a:0)
    monkeypatch.setattr(gateway.time,"sleep",lambda _:None)
    client_class = httpx.Client
    requests = []
    options = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={'error': {'message': 'private provider contents'}})
    def client(**kwargs):
        options.append(kwargs)
        return client_class(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(httpx, 'Client', client)
    monkeypatch.setattr(gateway, 'model_slot', nullcontext)
    with using({'model_settings': snapshot('gemini', purpose='query')}):
        with pytest.raises(gateway.ModelFailure) as error:
            gateway.generate('gemini', 'A report question', {})
    assert error.value.code == 'service_unavailable' and error.value.http_status == status
    assert 'private provider' not in str(error.value) and len(requests) == (1 if status==504 else 3)
    assert options[0]['timeout'].read == 45


def test_failed_queue_retains_chat_and_unknown_delivery_remains_pending(context, monkeypatch, hosted_query):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    def offline(*args): raise RuntimeError('private queue detail')
    monkeypatch.setattr(jobs, 'enqueue_question', offline)
    response = client.post(f'/investigations/{identifier}/questions', json={'question':'Explain the main dependencies.'})
    assert response.status_code == 503
    detail = response.json()['detail']
    assert detail['chat_id'] and detail['question_id'] and 'private queue' not in response.text
    with factory() as db:
        question = db.get(Question, detail['question_id'])
        question.status = 'queued'; question.created_at = now() - timedelta(minutes=6); db.commit()
    import rq.job
    monkeypatch.setattr(rq.job.Job, 'fetch', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('queue unavailable')))
    chats = client.get(f'/investigations/{identifier}/chats').json()
    assert chats[0]['pending']
    with factory() as db:
        assert db.get(Question, detail['question_id']).status == 'queued'
    monkeypatch.setattr(rq.job.Job, 'fetch', lambda *a, **k: SimpleNamespace(get_status=lambda **options: 'failed'))
    assert not client.get(f'/investigations/{identifier}/chats').json()[0]['pending']


def test_large_har_is_sanitized_before_the_normal_source_limit():
    from app.source_intake import inspect_upload
    raw = json.dumps({'log': {'entries': [{'request': {'url': 'https://app.example/api/list', 'method': 'GET'}, 'response': {'status': 200, 'content': {'mimeType': 'text/plain', 'text': 'private-value' * 180000}}}]}}).encode()
    assert len(raw) > 2000000
    reviewed = inspect_upload('capture.har', raw)
    assert reviewed['retained'] == 1 and reviewed['characters'] < 2000
    assert 'private-value' not in reviewed['sources'][0]['source']['content']


def test_source_map_chunks_share_safe_original_paths_and_parent_refs():
    first = {'version': 3, 'sources': ['../../src/main.ts'], 'sourcesContent': ['import {value} from "./value"; export const app = value;']}
    second = {'version': 3, 'sources': ['../src/value.ts'], 'sourcesContent': ['export const value = 1;']}
    a = next(source_map_sources(json.dumps(first), 'https://cdn.example/assets/main.js.map'))[0]
    b = next(source_map_sources(json.dumps(second), 'https://cdn.example/assets/value.js.map'))[0]
    assert a.origin.rsplit('/src/', 1)[0] == b.origin.rsplit('/src/', 1)[0]
    assert a.origin.endswith('/src/main.ts') and b.origin.endswith('/src/value.ts')
    unsafe = {'version': 3, 'sources': ['../../.env.production'], 'sourcesContent': ['private configuration']}
    assert list(source_map_sources(json.dumps(unsafe), 'https://cdn.example/app.map')) == []


def test_reanalysis_and_report_import_keep_client_evidence_context(context):
    from app.exports import report_document
    from app.source_intake import inspect_upload
    client, factory, _ = context
    register(client)
    url = 'https://another.example/'
    snapshot = web_observation.new_snapshot(url)
    web_observation.append_response(snapshot, url, url, 'text/html', {}, 200, '<html>Application</html>')
    identifier, _ = run(client, [{'title': 'Page observation', 'origin': 'local:observation.json', 'format': 'json', 'content': json.dumps(snapshot)}, {'title':'Shipped script', 'origin':url + 'app.js', 'format':'javascript', 'content':'fetch("/api/records");'}])
    with factory() as db:
        inv = db.get(Investigation, identifier)
        evidence = list(db.scalars(select(Evidence).where(Evidence.investigation_id == identifier)))
        script = next(source for source in evidence if source.source_type == 'javascript')
        script.collection_method = 'browser_script'
        script.signals = {**script.signals, 'collection_method':'browser_script', 'public_page':url, 'compiled_asset':True}
        db.commit()
        exported = report_document(inv, evidence, compact=True)
    reviewed = inspect_upload('report.json', json.dumps(exported).encode())
    record = next(row for row in reviewed['sources'] if row['source']['format'] == 'javascript')
    assert record['acquisition']['original_collection_method'] == 'browser_script' and record['acquisition']['compiled_asset']
    first = client.post(f'/investigations/{identifier}/reassess', json={'provider':'rules'}).json()['id']
    jobs.process(first)
    detail = client.get(f'/investigations/{first}').json()
    assert any(route['path'] == '/api/records' and route['contract_basis'] == 'static_client_reference' for route in detail['report']['api_endpoints'])
    second = client.post(f'/investigations/{first}/reassess', json={'provider':'rules'}).json()['id']
    jobs.process(second)
    assert client.get(f'/investigations/{second}').json()['report']['api_endpoints'][0]['path'] == '/api/records'
