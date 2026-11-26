"""Gated local verification and additive integration delta; no deploy or push."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MODIFIED=('geological_agent/bootstrap.py','pyproject.toml','tests_local/test_unified_skills.py',
          'tests_local/test_professional_catalog.py','tests_local/test_library.py','catalog/registry.json')
NEW=('geological_agent/skill_resources.py','scripts/import_xiaoyu_skills.py','scripts/verify_xiaoyu_skills.py',
     'tests_local/test_xiaoyu_skills.py','docs/xiaoyu-skills-integration.md')

def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--flowing-directory',type=Path,required=True);a=p.parse_args()
    evidence=a.evidence.resolve();evidence.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(a.flowing_directory.resolve()))
    from flowing import Flow,task
    baseline=json.loads(a.baseline.read_text(encoding='utf-8'));original={r['path']:r['sha256'] for r in baseline['files']}
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',TEMP=str(evidence),TMP=str(evidence))
    files=list(MODIFIED)+list(NEW)
    files += [p.relative_to(ROOT).as_posix() for p in (ROOT/'catalog/skills').glob('xiaoyu-*/*') if p.is_file()]
    files += [p.relative_to(ROOT).as_posix() for p in (ROOT/'catalog/imports/xiaoyu').glob('*') if p.is_file()]

    @task
    def source_gate():
        env_check=subprocess.run([sys.executable,'-m','pip','check'],env=env,capture_output=True)
        (evidence/'pip-check.txt').write_bytes(env_check.stdout+env_check.stderr)
        if env_check.returncode:raise RuntimeError('Independent test environment has conflicting dependencies')
        lock=subprocess.check_output([sys.executable,'-m','pip','freeze'],env=env)
        (evidence/'test-environment.txt').write_bytes(lock)
        # Original tracked files not listed in this request are untouched in the candidate.
        changed=[]
        for rel,digest in original.items():
            if sha((ROOT/rel).read_bytes())!=digest:changed.append(rel)
        if set(changed)!=set(MODIFIED):raise ValueError(('Unexpected changed files',changed))
        hashes={rel:sha((ROOT/rel).read_bytes()) for rel in files}
        write(evidence/'source-hashes.json',hashes)
        return hashes

    @task(depends_on=[source_gate])
    def regressions(source_gate):
        selection=['tests_local/test_xiaoyu_skills.py','tests_local/test_unified_skills.py',
                   'tests_local/test_catalog_metadata.py','tests_local/test_library.py',
                   'tests_local/test_professional_catalog.py::test_all_registered_source_tools_are_discoverable']
        result=subprocess.run([sys.executable,'-B','-m','pytest',*selection,'-q',
            '--basetemp='+str(evidence/'temp-tests'),'--junitxml='+str(evidence/'junit.xml'),
            '-o','cache_dir='+str(evidence/'pytest-cache')],cwd=ROOT,env=env,capture_output=True)
        (evidence/'pytest.stdout.txt').write_bytes(result.stdout);(evidence/'pytest.stderr.txt').write_bytes(result.stderr)
        cases=list(ET.parse(evidence/'junit.xml').getroot().iter('testcase'))
        def issues(items):
            return {(c.get('classname'),c.get('name'),k) for c in items for k in ('failure','error','skipped') if c.find(k) is not None}
        baseline_cases=list(ET.parse(a.baseline.parent/'baseline-junit.xml').getroot().iter('testcase'))
        actual=issues(cases);known=issues(baseline_cases)
        if not cases or any(c.find('skipped') is not None for c in cases):raise ValueError('Empty or skipped test result')
        if result.returncode not in (0,1) or actual!=known:raise RuntimeError('New or changed failures; original logs preserved')
        if any(c.find(k) is not None for c in cases if 'test_xiaoyu_skills' in c.get('classname','') for k in ('failure','error','skipped')):raise RuntimeError('New collection acceptance failed')
        for c in cases:
            if c.find('error') is not None and "No module named 'geological_agent.team.memorax'" not in c.find('error').get('message',''):
                raise RuntimeError('Existing fixture now has a different failure cause')
        return {'passed':len(cases)-len(actual),'failed':sum(k=='failure' for _,_,k in actual),
            'errors':sum(k=='error' for _,_,k in actual),'skipped':0,'baseline_failures_unchanged':True,
            'new_collection_passed':sum('test_xiaoyu_skills' in c.get('classname','') for c in cases),
            'full_regression_passed':not actual}

    def unchanged(source_gate,regressions):
        if source_gate!={rel:sha((ROOT/rel).read_bytes()) for rel in files}:raise ValueError('Sources changed during acceptance')

    @task(depends_on=[source_gate,regressions],validate=unchanged)
    def delta(source_gate,regressions):
        manifest={'base_git_head':baseline['git_head'],'candidate':str(ROOT),'modified':[], 'new':[],
                  'tests':regressions,'deployed':False,'pushed':False,'gpu_used':False,'model_called':False}
        for rel in files:
            row={'path':rel,'sha256':source_gate[rel]}
            if rel in original:row['base_sha256']=original[rel];manifest['modified'].append(row)
            else:manifest['new'].append(row)
        write(evidence/'integration-delta.json',manifest)
        with zipfile.ZipFile(evidence/'xiaoyu-integration-delta.zip','w',zipfile.ZIP_DEFLATED) as z:
            for rel in files:z.write(ROOT/rel,rel)
            z.write(evidence/'integration-delta.json','integration-delta.json')
        manifest['delta_sha256']=sha((evidence/'xiaoyu-integration-delta.zip').read_bytes())
        write(evidence/'acceptance.json',manifest)
        return manifest

    f=Flow(delta,max_workers=1,fail_fast=True);f.run()
    (evidence/'flow-summary.txt').write_text(f.summary(),encoding='utf-8')
    try:result=f.value(delta)
    except KeyError:
        print(f.summary());raise SystemExit('Verification stopped at a failed gate; see preserved logs.')
    if not result:raise RuntimeError('Integration gate did not finish; inspect evidence')
    print(json.dumps({'tests':result['tests'],'modified_files':len(result['modified']),'new_files':len(result['new']),
                      'deployed':False,'candidate':str(ROOT),'delta_sha256':result['delta_sha256']},ensure_ascii=False))

if __name__=='__main__':main()
