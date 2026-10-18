import json
from sqlalchemy import select, func
from test_baseline import register
from test_document_intelligence import run
from test_saved_sources import imported
from app import jobs, model_gateway as gateway
from app.models import ResearchChat, Question, ModelCache
from app.public_surface import surface_page
from app.web_observation import new_snapshot, append_response
from app.source_intake import inspect_upload
from test_scanner_pipeline import zipped


def test_jvm_modules_imports_build_dependencies_and_exact_fields(context):
    client, _, _ = context
    register(client)
    project=[
        ('repo/app/build.gradle.kts','plugins { id("com.android.application") }\ndependencies { implementation("io.ktor:ktor-client-core:3.0")\n implementation(project(":engine")) }'),
        ('repo/app/src/main/kotlin/org/example/player/ui/Screen.kt','package org.example.player.ui\nimport org.example.player.data.Track\nimport io.ktor.client.HttpClient\nclass Screen { val title = "class Fake" }\n// import org.example.player.missing.Ghost'),
        ('repo/app/src/main/kotlin/org/example/player/data/Track.kt','package org.example.player.data\ndata class Track(val id: String, val duration: Long, val name: String?)'),
        ('repo/engine/src/main/kotlin/org/example/engine/Engine.kt','package org.example.engine\nclass Engine'),
        ('repo/app/src/main/AndroidManifest.xml','<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application><service android:name=".PlaybackService"/></application></manifest>'),
    ]
    preview=inspect_upload('project.zip',zipped(project))
    assert all(row['status']=='retained' for row in preview['inventory'])
    sources=[{'title':p.split('/')[-1], 'origin':'local:'+p,'content':c} for p,c in project]
    _, detail=run(client,sources)
    r=detail['report'];modules=r['repository']['modules']
    assert len(modules)==3 and all(m['status']=='partial' for m in modules)
    assert any(e.get('relationship_kind')=='imports' for e in r['edges'])
    assert any(e.get('relationship_kind')=='build_dependency' for e in r['edges'])
    assert any(t['name']=='io.ktor:ktor-client-core' for t in r['technologies'])
    assert not any(t['name'].endswith('Ghost') or t['name']=='org.example.player' for t in r['technologies'])
    assert not any(s['name']=='Fake' for m in modules for s in m['symbols'])
    assert any(n['label']=='PlaybackService' for n in r['nodes'])
    names={e['id']:e['name'] for e in r['entities']}
    assert {(f['name'], f['type']) for f in r['fields'] if names[f['entity_id']]=='Track'} >= {('id','String'),('duration','Long'),('name','String?')}
    assert next(f for f in r['fields'] if f['name']=='name')['required'] is True
    assert not any(t['name'].startswith('org.example') for t in r['technologies'])


def test_public_forms_navigation_and_no_field_values(context):
    client,_,_=context;register(client)
    html='<html><title>Catalog</title><body><a href="/products">Products</a><form aria-label="Search" action="/search"><input name="q" value="PRIVATEVALUE" required><input type="hidden" name="token" value="SECRET"></form></body></html>'
    page=surface_page(html,'https://example.com/')
    assert 'PRIVATEVALUE' not in json.dumps(page) and 'SECRET' not in json.dumps(page)
    assert len(page['forms'][0]['fields'])==1
    snapshot=new_snapshot('https://example.com/')
    append_response(snapshot,'https://example.com/','https://example.com/','text/html',{},200,html)
    _,detail=run(client,[{'title':'Observed page','origin':'local:observation.json','content':json.dumps(snapshot)}])
    assert {'Page navigation','Search'} <= {n['label'] for n in detail['report']['nodes']}
    assert any(f['name']=='q' and f['required'] for f in detail['report']['fields'])
    assert any(e['path']=='/search' and e['contract_basis']=='form_action' for e in detail['report']['api_endpoints'])


def test_report_chats_followups_isolation_delete_and_exports(context,monkeypatch,hosted_query):
    client,factory,_=context;register(client);identifier=imported(client);jobs.process(identifier)
    queued=[];monkeypatch.setattr(jobs,'enqueue_question',queued.append)
    requests=[]
    def reply(provider,prompt,schema):
        packet=json.loads(prompt.split('\n',1)[1]);requests.append(packet)
        assert packet['report']['counts']['api_endpoints']
        assert len(prompt.encode())<24000
        return {'insufficient_evidence':False,'statements':[{'text':'The report retains an API operation and its source.','evidence':[next(iter(packet['passages']))]}]},{}
    monkeypatch.setattr(gateway,'generate',reply)
    base=f'/investigations/{identifier}'
    first=client.post(base+'/questions',json={'question':'Explain the architecture of this application.'}).json();jobs.process_question(first['id'])
    second=client.post(base+'/questions',json={'question':'How does it work?','chat_id':first['chat_id']}).json()
    assert client.delete(base+'/chats/'+first['chat_id']).status_code==409
    jobs.process_question(second['id'])
    assert requests[1]['conversation'][0]['user']==first['question']
    assert requests[1]['conversation'][0]['assistant']
    chats=client.get(base+'/chats').json();assert len(chats)==1 and chats[0]['message_count']==2
    assert len(client.get(base+'/chats/'+first['chat_id']).json())==2
    export=client.get(base+'/export/json').json();assert all(q['chat_id']==first['chat_id'] for q in export['questions'])
    other=imported(client);jobs.process(other)
    assert client.get(f'/investigations/{other}/chats/'+first['chat_id']).status_code==404
    assert client.post(f'/investigations/{other}/questions',json={'question':'Explain this application.','chat_id':first['chat_id']}).status_code==404
    assert client.delete(base+'/chats/'+first['chat_id']).status_code==204
    assert client.get(base+'/chats').json()==[] and client.get(base+'/questions').json()==[]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ResearchChat))==0
        assert db.scalar(select(func.count()).select_from(Question))==0
        assert not any(row.result.get('chat_id')==first['chat_id'] for row in db.scalars(select(ModelCache)))


def test_new_topics_do_not_reuse_previous_retrieval_words():
    from app.research_context import conversation_query
    history=[{'question':'Explain authentication.'}]
    assert 'authentication' in conversation_query('How does it work?',history)
    assert conversation_query('Describe database tables and their fields.',history)=='Describe database tables and their fields.'
