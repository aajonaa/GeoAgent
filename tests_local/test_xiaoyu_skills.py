"""Real registry and source-bundle checks; no model calls or scientific execution."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from threading import Event
import zipfile

import pytest

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor, ToolFailure
from geological_agent.skill_resources import operate, ROOT as RESOURCES
from geological_agent.team.library import LibraryCatalog
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog

ROOT=Path(__file__).resolve().parents[1]
IMPORTS=ROOT/'catalog/imports/xiaoyu'
REPORT=json.loads((IMPORTS/'integration.json').read_text(encoding='utf-8'))
INDEX=json.loads((IMPORTS/'source-index.json').read_text(encoding='utf-8'))
IDS=[s['runtime_id'] for s in REPORT['skills']]

def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False).encode()
def ctx(path, names=('SkillReadResource',)):
    return ToolExecutionContext('xiaoyu-resource-tests',path,names,Settings(),Event())

@pytest.fixture(scope='module')
def runtime():return build_registry(human_input=True)

def test_all_original_packages_and_duplicate_occurrences_accounted():
    records=INDEX['records']
    assert {r['number'] for r in records}==set(range(1,111))
    assert len(records)==132
    assert len({r['skill_sha'] for r in records})==len(IDS)==90
    assert REPORT['duplicate_occurrences']==42
    assert len(INDEX['capture_manifest']['files'])==222
    assert Counter(Path(x['local']).suffix for x in INDEX['capture_manifest']['files'])=={'.zip':110,'.json':110,'.xlsx':1,'.pdf':1}
    assert REPORT['deployed'] is False and REPORT['scientific_workflow_validation']=='not_run'

def test_existing_catalog_entries_preserved_except_explicit_availability_repair():
    current=catalog()
    assert sha(canonical(current['tools']))==REPORT['original_tools_sha256']
    original_skills=deepcopy(current['skills'][:97])
    repaired=next(s for s in original_skills if s['id']=='github-geophysics-grain-fracture')
    assert repaired['delivery']['availability_status']=='partially_blocked'
    assert repaired['delivery']['unavailable_references']==['GeoRockStressAnisotropy']
    assert 'GeoRockStressAnisotropy' not in repaired['tool_references']
    repaired['delivery']['availability_status']='tool_candidates_available_workflow_unverified'
    assert sha(canonical(original_skills))==REPORT['original_skills_sha256']
    assert len(current['tools'])==457 and len(current['skills'])==187
    assert {s['id'] for s in current['skills'][97:]}=={x['id'] for x in REPORT['skills']}

@pytest.mark.parametrize('sid',IDS)
def test_registered_skill_sources_resources_and_dependencies(sid,runtime,tmp_path):
    registry,loader,_=runtime
    skill=loader.load(sid)
    assert 'SkillReadResource' in skill.tool_names
    assert all(registry.get(n) for n in skill.tool_names)
    item=next(s for s in REPORT['skills'] if s['runtime_id']==sid)
    listing=operate({'skill_id':sid,'action':'list'},ctx(tmp_path)).data
    assert listing['total']==item['resource_count']
    manifest=json.loads((RESOURCES/item['id']/'resources.json').read_text(encoding='utf-8'))
    archive=RESOURCES/item['id']/'resources.zip'
    assert sha(archive.read_bytes())==manifest['archive_sha256']
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist())=={r['path'] for r in manifest['files']}
        for row in manifest['files']:
            raw=z.read(row['path'])
            assert len(raw)==row['bytes'] and sha(raw)==row['sha256']
        assert sha(z.read('SKILL.md'))==item['source_skill_sha256']
    read=operate({'skill_id':sid,'action':'read','path':'SKILL.md','offset':0,'limit':12000},ctx(tmp_path)).data
    assert read['text'] and read['execution_performed'] is False
    assert not list(tmp_path.iterdir()), 'Reading must not materialize or run resources'
    assert 'workflow_unverified' in skill.instructions

def test_resource_visibility_follows_native_skill_loading(runtime,tmp_path):
    registry,loader,base=runtime
    executor=ToolExecutor(registry)
    assert 'SkillReadResource' not in base
    denied=executor.execute(ToolCall('denied','SkillReadResource',{'skill_id':IDS[0]}),ctx(tmp_path,base))
    assert denied.status=='error' and denied.error.code=='tool_not_exposed'
    load=executor.execute(ToolCall('load','skill_load',{'skill_id':IDS[0]}),ctx(tmp_path,base))
    assert load.status=='ok' and 'SkillReadResource' in load.data['tool_names']
    exposed=executor.execute(ToolCall('allowed','SkillReadResource',{'skill_id':IDS[0],'action':'read','path':'SKILL.md'}),ctx(tmp_path,tuple(load.data['tool_names'])))
    assert exposed.status=='ok' and exposed.data['execution_performed'] is False

def test_library_shows_all_skills_and_real_validation_scope():
    library=LibraryCatalog(human_input=True)
    assert library.summary()['counts']['skills']==187
    assert library.summary()['counts']['professional_tools']==457
    for sid in IDS:
        detail=library.detail('skills',sid)
        assert detail['status']=='registered' and detail['available_tool_count']==detail['tool_count']
        assert '完整科学工作流' in detail['instructions']
        assert detail['category']!='Other'

@pytest.mark.parametrize('path',['../private','/etc/passwd','C:/secret','..\\secret','a/../b','./SKILL.md','a//b'])
def test_resource_paths_reject_escape(path,tmp_path):
    with pytest.raises(ToolFailure) as e:
        operate({'skill_id':IDS[0],'action':'read','path':path},ctx(tmp_path))
    assert e.value.error.code=='invalid_resource_path'

def test_prepare_is_verified_idempotent_and_does_not_execute(tmp_path):
    sid='xiaoyu_boule'
    result=operate({'skill_id':sid,'action':'prepare'},ctx(tmp_path)).data
    folder=tmp_path/result['workspace_root']
    assert (folder/'SKILL.md').is_file()
    before={p.relative_to(folder).as_posix():sha(p.read_bytes()) for p in folder.rglob('*') if p.is_file()}
    assert len(before)==result['files_copied']
    assert operate({'skill_id':sid,'action':'prepare'},ctx(tmp_path)).data==result
    assert before=={p.relative_to(folder).as_posix():sha(p.read_bytes()) for p in folder.rglob('*') if p.is_file()}
    assert result['execution_performed'] is False
    (folder/'SKILL.md').write_text('User change, preserve me',encoding='utf-8')
    with pytest.raises(ToolFailure) as e:operate({'skill_id':sid,'action':'prepare'},ctx(tmp_path))
    assert e.value.error.code=='resource_destination_conflict'
    assert (folder/'SKILL.md').read_text(encoding='utf-8')=='User change, preserve me'

def test_tampered_bundle_refused_before_materialization(tmp_path):
    root=tmp_path/'catalog';root.mkdir();sid='xiaoyu_boule'
    shutil.copytree(RESOURCES/'xiaoyu-boule',root/'xiaoyu-boule')
    (root/'xiaoyu-boule/resources.zip').write_bytes(b'tampered')
    task=tmp_path/'task';task.mkdir()
    with pytest.raises(ToolFailure) as e:operate({'skill_id':sid,'action':'prepare'},ctx(task),root=root)
    assert e.value.error.code=='resource_integrity' and not list(task.iterdir())

def test_unknown_resource_and_skill_refused(tmp_path):
    with pytest.raises(ToolFailure) as e:operate({'skill_id':IDS[0],'action':'read','path':'missing.py'},ctx(tmp_path))
    assert e.value.error.code=='unknown_skill_resource'
    with pytest.raises(ToolFailure) as e:operate({'skill_id':'../../external'},ctx(tmp_path))
    assert e.value.error.code=='unknown_skill_resources'

def test_pagination_and_native_schema_reject_incomplete_read(runtime,tmp_path):
    registry,_,_=runtime
    a=operate({'skill_id':'xiaoyu_global_geochemical_atlas','action':'list','limit':3},ctx(tmp_path)).data
    b=operate({'skill_id':'xiaoyu_global_geochemical_atlas','action':'list','offset':3,'limit':3},ctx(tmp_path)).data
    assert a['next_offset']==3 and len(a['files'])==len(b['files'])==3
    assert {x['path'] for x in a['files']}.isdisjoint(x['path'] for x in b['files'])
    e=ToolExecutor(registry).execute(ToolCall('bad','SkillReadResource',{'skill_id':IDS[0],'action':'read'}),ctx(tmp_path))
    assert e.status=='error' and e.error.code=='invalid_arguments'

def test_new_and_repaired_legacy_delivery_contracts():
    from source_asset_checks.run import check_assets
    from geological_agent.geology.source_registry import source_tools
    rows=check_assets(catalog(),source_tools())
    new=[r for r in rows if r['skill'].startswith('xiaoyu-')]
    assert len(new)==90 and all(r['status']=='passed' for r in new)
    legacy=[r for r in rows if not r['skill'].startswith('xiaoyu-') and r['status']!='passed']
    baseline=json.loads((IMPORTS/'baseline-diagnostics.json').read_text(encoding='utf-8'))
    assert len(baseline['skill_document_failures'])==20  # Preserve historical failure evidence.
    assert legacy==[], legacy  # Repaired old documents must now pass; no grandfathered failures.

def test_actual_library_routes_with_isolated_authentication():
    from fastapi import FastAPI,HTTPException
    from fastapi.testclient import TestClient
    from geological_agent.team.library import install_library_routes
    app=FastAPI()
    def auth(request):
        if request.headers.get('x-test-user')!='local-fixture':raise HTTPException(401)
        return {'id':'local-fixture'}
    install_library_routes(app,auth,human_input=True)
    with TestClient(app) as client:
        assert client.get('/api/library').status_code==401
        result=client.get('/api/library',headers={'x-test-user':'local-fixture'})
        assert result.status_code==200 and result.json()['counts']['skills']==187
        found={s['id'] for s in result.json()['skills'] if s['id'].startswith('xiaoyu_')}
        assert found==set(IDS)
        detail=client.get('/api/library/skills/xiaoyu_pyrolite',headers={'x-test-user':'local-fixture'})
        assert detail.status_code==200 and 'SkillReadResource' in {t['id'] for t in detail.json()['tools']}
