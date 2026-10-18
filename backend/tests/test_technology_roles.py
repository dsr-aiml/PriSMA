import json
from copy import deepcopy
from test_baseline import register
from test_document_intelligence import run
from app.source_semantics import visible_report
from types import SimpleNamespace


def test_python_node_optional_and_container_roles(context):
    client,_,_=context;register(client)
    sources=[
        {'title':'Python','origin':'local:alpha/pyproject.toml','content':'[project]\nname="alpha"\ndependencies=["httpx>=0.27; python_version >= \'3.10\'"]\n[project.optional-dependencies]\ntest=["pytest>=8"]\nextra=["rich>=13"]'},
        {'title':'Development','origin':'local:alpha/requirements-dev.txt','content':'ruff==0.8.0\n# requests==0.0\n'},
        {'title':'Container','origin':'local:alpha/Dockerfile','content':'FROM python:3.12-slim\nWORKDIR /app\n'},
        {'title':'Node','origin':'local:omega/package.json','content':json.dumps({'name':'omega','dependencies':{'react':'19'},'optionalDependencies':{'sharp':'0.33'},'devDependencies':{'typescript':'5.9'}})},
    ]
    _,detail=run(client,sources)
    technologies={row['name']:row for row in detail['report']['technologies']}
    def groups(name):return {d['group'] for d in technologies[name]['declarations']}
    assert groups('httpx')=={'dependencies'}
    assert groups('pytest')=={'test_dependencies'}
    assert groups('rich')=={'optionalDependencies'}
    assert groups('ruff')=={'devDependencies'}
    assert groups('sharp')=={'optionalDependencies'}
    assert groups('python:3.12-slim')=={'container_images'}
    assert 'requests' not in technologies
    assert any(d['version']=='>=0.27' for d in technologies['httpx']['declarations'])


def test_legacy_role_projection_preserves_original_report_and_sources():
    source=SimpleNamespace(id='e',source_url='local:any-project/requirements.txt',source_type='config')
    report={'claims':[{'id':'c','type':'technology','description':'httpx: Declared Python dependency.','supporting_evidence_ids':['e'],'extraction_method':'parser'}],
        'technologies':[{'id':'t','name':'httpx','category':'source_reference','claim_id':'c','declarations':[{'group':'source_reference','claim_id':'c','version':'0.28'}]}],'features':[]}
    original=deepcopy(report)
    projected=visible_report(report,[source])
    assert projected['technologies'][0]['declarations'][0]['group']=='dependencies'
    assert projected['technologies'][0]['declarations'][0]['claim_id']=='c'
    assert report==original


def test_model_mentions_do_not_become_parser_imports():
    source=SimpleNamespace(id='e',source_url='local:any-project/main.py',source_type='python')
    report={'claims':[{'id':'c','description':'Some library imported here.','supporting_evidence_ids':['e'],'extraction_method':'ollama'}],
        'technologies':[{'id':'t','name':'Some library','category':'source_reference','claim_id':'c'}],'features':[]}
    assert visible_report(report,[source]) is report
