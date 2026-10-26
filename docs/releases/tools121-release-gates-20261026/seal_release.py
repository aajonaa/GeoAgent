"""Seal only source-bound, independently replayed operations for publication."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import sys
from flowing import Flow, task
from stage_remediation import source_hashes


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def count(value):
    require(type(value) is int and value >= 0, 'Invalid execution count')
    return value


def unique(values, label):
    require(isinstance(values, list) and all(isinstance(v, str) and v for v in values), label)
    require(len(values) == len(set(values)), 'Duplicate ' + label)
    return set(values)


def validate_cohort(stage, tools, exclusions):
    passed = unique(stage['passed_tool_ids'], 'passed tool IDs')
    excluded = unique(stage['excluded_tool_ids'], 'excluded tool IDs')
    require(not passed & excluded, 'Accepted and excluded cohorts overlap')
    require(len(passed | excluded) == 121, 'Cohort must contain exactly 121 unique IDs')
    require(set(tools) == passed, 'Published cohort is not exactly replayed')
    require(unique(stage['added_tool_ids'], 'added tool IDs') <= passed, 'Added tool outside accepted cohort')
    require(unique([r['id'] for r in exclusions], 'exclusion rows') == excluded, 'Exclusions differ from stage')
    require(all(r['reason'] and r['status'] != 'passed' for r in exclusions), 'Invalid exclusion')


class Evidence:
    """Read actual files once, bind every nested byte stream, and fail closed.

    These four adapters describe the actual final-r2 producer formats, not a
    permissive generic test-result schema. Expected negative API responses are
    successful checks only when the producer explicitly identifies the negative.
    """

    PROFILE = 'catalog/source_delivery/expansion501-20261026/shared-isolation-v2/profiles.json'
    CONTRACT = 'geological_agent/geology/collection_contracts.py'

    def __init__(self, app, receipt):
        self.app, self.receipt = Path(app), receipt
        self.files, self.blobs = {}, {}
        self.cold_jobs = set()
        require(receipt['source_root'] == str(self.app) and receipt['gpu_used'] is False, 'Receipt source/CPU mismatch')
        require(receipt.get('status', 'passed') == 'passed', 'Group receipt is not passed')
        self.sources = receipt['source_files']
        require(bool(self.sources) and 'catalog/registry.json' in self.sources, 'Missing source binding')
        for relative, digest in self.sources.items():
            p = Path(relative)
            require(not p.is_absolute() and '..' not in p.parts, 'Unsafe source path')
            require((self.app / p).resolve().is_relative_to(self.app.resolve()), 'Source escapes app')
            self.bytes(self.app / p, digest)
        catalog = self.json(self.app / 'catalog/registry.json')
        unique([t['id'] for t in catalog['tools']], 'catalog IDs')
        self.specs = {t['id']: t for t in catalog['tools']}
        self.profiles = self.json(self.app / self.PROFILE)['profiles'] if self.PROFILE in self.sources else {}
        if 'source_binding' in receipt or 'fresh_positive_worker_jobs' in receipt:
            require('source_binding' in receipt and count(receipt['fresh_positive_worker_jobs']) > 0,
                    'Incomplete cold-cache group binding')

    def bytes(self, path, expected=None):
        p = Path(path)
        require(p.is_absolute() and p.is_file(), 'Missing absolute evidence file: ' + str(p))
        key = str(p)
        if key not in self.blobs:
            self.blobs[key] = p.read_bytes()
            self.files[key] = hashlib.sha256(self.blobs[key]).hexdigest()
        if expected is not None:
            require(isinstance(expected, str) and len(expected) == 64 and self.files[key] == expected,
                    'Evidence hash mismatch: ' + key)
        return self.blobs[key]

    def json(self, path, expected=None):
        def pairs(items):
            out = {}
            for k, v in items:
                require(k not in out, 'Duplicate JSON key: ' + k)
                out[k] = v
            return out
        def nonfinite(value):
            raise AssertionError('Non-finite evidence JSON: ' + value)
        return json.loads(self.bytes(path, expected), object_pairs_hook=pairs, parse_constant=nonfinite)

    def link(self, descriptor, parse=True):
        require(isinstance(descriptor, dict) and {'path', 'sha256'} <= descriptor.keys(), 'Unbound evidence link')
        return self.json(descriptor['path'], descriptor['sha256']) if parse else self.bytes(descriptor['path'], descriptor['sha256'])

    def source_map(self, values):
        require(isinstance(values, dict) and values and 'catalog/registry.json' in values, 'Missing raw source map')
        stage = self.json(self.app.parent / 'stage-receipt.json')
        for path, digest in values.items():
            relative = Path(path)
            require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe closure source path')
            actual = self.app / relative
            require(actual.resolve().is_relative_to(self.app.resolve()), 'Closure source escapes app')
            require(stage['source_files'].get(path) == digest, 'Staged closure source mismatch: ' + path)
            if path in self.sources:
                require(self.sources[path] == digest, 'Group closure source mismatch: ' + path)
            # Compact group receipts need not duplicate the entire hash-bound
            # profile closure. Its extra files still require stage AND bytes.
            self.bytes(actual, digest)

    def provenance(self, data, tool):
        require(isinstance(data, dict) and set(data) - {'provenance', 'artifacts'}, 'No scientific result')
        p = data['provenance']
        require(p['tool'] == tool and p['network_required'] is False, 'Result tool/network mismatch')
        module = self.specs[tool]['source_interface']['entrypoint']['callable'].split(':')[0]
        source = module.replace('.', '/') + '.py'
        require(source in self.sources and p['implementation_sha256'] == self.sources[source], 'Wrong implementation source')
        require(p['contract_sha256'] == self.sources[self.CONTRACT], 'Wrong contract source')
        profiles = [(k, v) for k, v in self.profiles.items() if v['tool'] == tool]
        require(len(profiles) <= 1, 'Ambiguous CPU profile')
        if profiles:
            profile_id, profile = profiles[0]
            proof = p['isolation']
            require(profile['source_root'] == str(self.app) and profile['catalog_sha256'] == self.sources['catalog/registry.json'], 'Wrong profile app/catalog')
            require(proof['profile_id'] == profile_id and proof['profile_sha256'] == self.sources[self.PROFILE], 'Wrong profile binding')
            require(proof['protocol'] == 'geoagent-isolated-cpu-v2' and proof['gpu_requested'] is False
                    and proof['runtime_install'] is False, 'Invalid CPU proof')
            for key in ('build_receipt_sha256', 'worker_sha256', 'python_sha256', 'python_version'):
                require(proof[key] == profile[key], 'Wrong CPU proof ' + key)
            spec_sha = hashlib.sha256(json.dumps(self.specs[tool], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            require(proof['spec_sha256'] == spec_sha, 'Wrong tool spec')
            for key in ('build_receipt', 'dependency_lock'):
                self.bytes(profile[key], profile[key + '_sha256'])
            self.source_map({'catalog/registry.json': profile['catalog_sha256'], **profile['source_files']})
            private = Path(profile['private_root']).resolve()
            require(Path(proof['evidence_directory']).resolve().is_relative_to(private), 'Wrong CPU execution root')
        else:
            require('isolation' not in p, 'Undeclared CPU profile')

    def response(self, response, tool, negative, codes=None):
        require(response['name'] == tool and response['cached'] is False, 'Wrong tool or cached-only execution')
        require(response['status'] == ('error' if negative else 'ok'), 'Unexpected API outcome')
        if negative:
            error = response['error']
            require(isinstance(error, dict) and isinstance(error.get('code'), str) and error['code'], 'Missing negative error')
            if codes is not None:
                require(error['code'] in codes, 'Unexpected negative error code')
        else:
            require(response['error'] is None and response['evidence']['execution'] == 'executed', 'No successful execution')
            self.provenance(response['data'], tool)
        return not negative

    def cold_cache(self, case, inner, tool):
        cold = case['cold_cache_evidence']
        require(set(cold) == {'fresh_private_worker_job', 'job', 'source_binding'}, 'Unknown/incomplete cold-cache evidence')
        require(cold['fresh_private_worker_job'] is True, 'Worker job is not declared fresh')
        require(set(cold['source_binding']) == {'path', 'sha256'} and
                cold['source_binding'] == self.receipt['source_binding'], 'Cold-cache source descriptor mismatch')
        binding = self.link(cold['source_binding'])
        require(set(binding) == {'cold_cache_baseline', 'core_runner', 'gpu_used', 'profile_input',
                                'profile_registry', 'source_files', 'source_root', 'stage_receipt',
                                'started_epoch', 'wrapper_runner'}, 'Unknown/incomplete cold-cache manifest')
        require(binding['source_root'] == str(self.app) and binding['gpu_used'] is False, 'Cold-cache source/CPU mismatch')
        self.source_map(binding['source_files'])
        require(binding['profile_registry'] == self.receipt['profile_registry'] == {
            'path': str(self.app / self.PROFILE), 'sha256': self.sources[self.PROFILE]}, 'Cold-cache registry mismatch')
        require(binding['stage_receipt'] == self.receipt['stage_receipt'] and
                Path(binding['stage_receipt']['path']) == self.app.parent / 'stage-receipt.json', 'Cold-cache stage mismatch')
        require(binding['profile_input'] == self.receipt['profile_input'], 'Cold-cache profile input mismatch')
        for key in ('profile_registry', 'stage_receipt', 'profile_input', 'core_runner', 'wrapper_runner'):
            self.link(binding[key], parse=False)
        proof = inner['isolation']
        require(case['isolation'] == proof and cold['job'] == proof['evidence_directory'], 'Cold-cache job differs from actual inner execution')
        profile = self.profiles[proof['profile_id']]
        require(profile['tool'] == tool and profile['source_root'] == str(self.app), 'Cold-cache profile/tool mismatch')
        job, private = Path(cold['job']), Path(profile['private_root']).resolve()
        require(job.is_absolute() and job.is_dir() and not job.is_symlink() and job.resolve().parent == private
                and job.name.startswith('v2-'), 'Invalid actual worker directory')
        baseline = binding['cold_cache_baseline'][tool]
        require(set(baseline) == {'root', 'preexisting_jobs'} and Path(baseline['root']).resolve() == private,
                'Cold-cache baseline root mismatch')
        old = unique(baseline['preexisting_jobs'], 'preexisting worker jobs')
        require(all(Path(p).is_absolute() and Path(p).resolve().parent == private for p in old), 'Invalid baseline job')
        require(job.resolve() not in {Path(p).resolve() for p in old}, 'Worker job existed before replay')
        require(str(job.resolve()) not in self.cold_jobs, 'Worker job reused for another call')
        started = binding['started_epoch']
        require(type(started) in (int, float) and started > 0 and
                (job / 'status.json').stat().st_mtime >= started, 'Worker completion predates cold-cache manifest')
        status = self.json(job / 'status.json')
        require(status['tool'] == tool and status['status'] == 'ok' and type(status['exit_code']) is int
                and status['exit_code'] == 0, 'Actual worker did not succeed')
        self.bytes(job / 'control/registry.json', self.sources[self.PROFILE])
        self.cold_jobs.add(str(job.resolve()))

    def tool(self, row):
        tool = row['id']
        require(tool in self.specs and row['status'] == 'passed', 'Tool missing or not passed')
        n = count(row['passed_calls'])
        require(n > 0 and count(row['failed_calls']) == count(row['skipped_calls']) == 0, 'Failed/skipped/empty receipt')
        raw = self.json(row['report'], row['report_sha256'])
        require(raw.get('tool_id', raw.get('id')) == tool and raw['status'] == 'passed', 'Raw report identity/status')
        for key in ('tool_id', 'id'):
            if key in raw:
                require(raw[key] == tool, 'Conflicting tool identity')
        if 'source_root' in raw:
            require(raw['source_root'] == str(self.app), 'Wrong raw source root')
        if 'gpu_used' in raw:
            require(raw['gpu_used'] is False, 'Raw GPU execution')
        for key, expected in [('passed_calls', n), ('failed_calls', 0), ('skipped_calls', 0)]:
            if key in raw:
                require(count(raw[key]) == expected, 'Raw/receipt count mismatch: ' + key)
        modes, identities = set(), []
        if 'checks' in raw and 'calls' in raw:
            kind, cases = 'geology', raw['calls']
            require(raw['checks'] and all(c['status'] == 'passed' for c in raw['checks']), 'Failed/empty geology checks')
            unique([c['name'] for c in raw['checks']], 'geology checks')
            bundle = Path(row['report']).parents[2]
            aggregate = self.json(bundle / 'execution-report.json')
            require(aggregate['app'] == str(self.app) and aggregate['status'] == 'passed'
                    and aggregate['gpu_used'] is False and not aggregate['failed_tools'], 'Geology parent failed/wrong source')
            require(count(aggregate['checks']) == sum(len(t['checks']) for t in aggregate['tools']), 'Geology aggregate check count')
            matches = [t for t in aggregate['tools'] if t['tool_id'] == tool]
            require(matches == [raw], 'Geology raw/parent execution mismatch')
            for binding in aggregate['candidate_bindings'].values():
                self.link(binding, parse=False)
                rel = Path(binding['path']).relative_to(self.app).as_posix()
                require(self.sources.get(rel) == binding['sha256'], 'Geology parent source binding')
            for c in cases:
                require(c['route'] == 'ToolExecutor' and type(c['json_input']) is bool, 'Wrong geology route')
                self.link(c['input'], parse=False)
                response = self.link(c['response'])
                codes = c.get('expected_error_codes')
                if codes is not None:
                    require(isinstance(codes, list) and codes, 'Empty expected errors')
                require(c['status'] == response['status'], 'Geology response mismatch')
                if self.response(response, tool, codes is not None, codes):
                    modes.add(c['json_input'])
                identities.append(response['call_id'])
        elif 'parent_run' in raw and 'calls' in raw:
            kind, cases = 'remote', raw['calls']
            require(count(raw['expected_calls']) == n and raw['candidate_source_changes'] == [], 'Remote count/source changes')
            run = raw['parent_run']
            require(run['status'] == 'pass' and type(run['returncode']) is int and run['returncode'] == 0 and run['error'] is None, 'Remote parent failed')
            parent = self.json(run['report'])
            require(parent['status'] == 'pass', 'Remote nested parent failed')
            if 'app' in parent:
                require(parent['app'] == str(self.app), 'Remote parent wrong source')
            else:
                require(parent['PYTHONPATH'].split(':')[0] == str(self.app), 'Remote native parent wrong source')
            oracle = self.json(parent['oracle_report'])
            require(oracle['status'] == 'pass' and oracle['cases'], 'Remote oracle failed/empty')
            for source in oracle['oracle_sources']:
                self.link(source, parse=False)
            selected = [c for c in oracle['cases'] if c['tool'] == tool]
            require(len(selected) == n, 'Remote oracle count mismatch')
            oracle_by_case = {c['case']: c for c in selected}
            require(len(oracle_by_case) == n, 'Duplicate oracle case')
            if isinstance(parent['cases'], list):
                require(len([c for c in parent['cases'] if c['tool'] == tool]) == n, 'Remote native execution count')
            else:
                require(count(parent['cases']) == len(oracle['cases']), 'Remote parent/oracle count mismatch')
            for c in cases:
                require(c['tool'] == tool and c['status'] == 'pass', 'Remote failed/wrong case')
                independent = c['independent_oracle']
                require(independent == oracle_by_case[c['case']] and independent['status'] == 'pass', 'Remote oracle identity/status mismatch')
                checks = independent['checks']
                negative = checks == ['exact_original_negative_error_code']
                require(negative or checks == ['original_artifact_contract', 'CRS_dtype_nodata_affine', 'unchanged_independent_numerical_reference'], 'Unknown remote assertion contract')
                response = self.json(c['raw_result'], c['raw_result_sha256'])
                if self.response(response, tool, negative):
                    require(c['case'].endswith(('_dict', '_json')), 'Unknown remote positive mode')
                    modes.add(c['case'].endswith('_json'))
                    artifacts = {Path(a['path']).name: a for a in response['artifacts']}
                    require(len(artifacts) == len(response['artifacts']) and set(artifacts) == set(c['artifact_sha256']), 'Remote artifact inventory mismatch')
                    for name, digest in c['artifact_sha256'].items():
                        path = Path(c['workspace']) / artifacts[name]['path']
                        require(path.resolve().is_relative_to(Path(c['workspace']).resolve()), 'Artifact escapes workspace')
                        self.bytes(path, digest)
                identities.append(c['case'])
        elif 'parent_preflight' in raw and 'cases' in raw:
            kind, cases = 'geophysics', raw['cases']
            self.source_map(raw['source_files'])
            self.link(raw['accepted_independent_reference'])
            preflight = self.link(raw['parent_preflight'])
            require(preflight['status'] == 'passed' and preflight['app'] == str(self.app) and preflight['gpu_used'] is False, 'Geophysics parent failed/wrong source')
            self.link(preflight['stage_receipt'])
            for c in cases:
                require(c['status'] == 'passed' and c['tool'] == tool and type(c['negative']) is bool, 'Geophysics failed/wrong case')
                require(c['mode'] in ('direct_dict', 'direct_json', 'runtime_dict', 'runtime_json'), 'Unknown execution mode')
                files = {Path(f['path']).name: f for f in c['raw_files']}
                require(len(files) == len(c['raw_files']), 'Duplicate raw call file')
                for f in files.values():
                    require(Path(f['path']).parent == Path(c['evidence']), 'Wrong raw call directory')
                    self.link(f, parse=False)
                self.link(files['request.txt'], parse=False)
                check = self.link(files['replay-check.json'])
                cold_required = ('source_binding' in self.receipt and not c['negative'] and
                                 any(p['tool'] == tool for p in self.profiles.values()))
                require(('cold_cache_evidence' in c) == cold_required, 'Missing or unexpected cold-cache evidence')
                require(check == {k: v for k, v in c.items() if k not in ('raw_files', 'cold_cache_evidence')},
                        'Nested replay check mismatch')
                if cold_required:
                    self.cold_cache(c, check, tool)
                if c['mode'].startswith('runtime_'):
                    response = self.link(files['runtime-result.json'])
                    if self.response(response, tool, c['negative']):
                        modes.add(c['mode'].endswith('_json'))
                elif c['negative']:
                    error = self.link(files['direct-error.json'])
                    require(error['type'] and error['code'] and error['message'], 'Missing direct rejection')
                    require('direct-result.json' not in files, 'Negative also reports success')
                else:
                    self.provenance(self.link(files['direct-result.json']), tool)
                    require('direct-error.json' not in files, 'Positive also reports error')
                identities.append(c['evidence'])
        elif 'frozen_reference' in raw and 'coverage' in raw and 'cases' in raw:
            kind, cases = 'spatial', raw['cases']
            require('calls' not in raw and raw['model_calls'] is False, 'Ambiguous spatial evidence')
            require(raw['parent']['pythonpath'].startswith(str(self.app) + ':'), 'Spatial parent wrong source')
            module = self.specs[tool]['source_interface']['entrypoint']['callable'].split(':')[0].replace('.', '/') + '.py'
            require(raw['source_sha256'] == self.sources[module], 'Spatial raw source mismatch')
            reference = self.link(raw['frozen_reference'])
            require(reference['id'] == tool and reference['status'] == 'passed' and reference['gpu_used'] is False, 'Wrong/failed independent reference')
            coverage = raw['coverage']
            require(count(coverage['reference_call_count']) == len(reference['calls']) > 0, 'Frozen reference count mismatch')
            positives = [c for c in cases if c['label'].startswith('positive-')]
            negatives = [c for c in cases if c['label'].startswith('frozen-negative-')]
            require(len(positives) == 2 * count(coverage['distinct_positive_inputs']) > 0, 'Missing spatial positives')
            require(len(negatives) == count(coverage['frozen_negative_calls']), 'Missing spatial negatives')
            extras = len(cases) - len(positives) - len(negatives)
            require(extras == (8 if 'content_hash_controls' in raw else 0), 'Missing content-hash controls')
            for c in cases:
                require(c['status'] == 'passed' and type(c['json']) is bool and isinstance(c['input_json'], str), 'Spatial failed/invalid case')
                label = c['label']
                negative = label.startswith('frozen-negative-') or label in ('truncated-cbc', 'absolute-cbc')
                require(negative or label.startswith('positive-') or label in ('same-path-content-mutation', 'same-path-content-restored'), 'Unknown spatial case')
                if self.response(c['result'], tool, negative):
                    modes.add(c['json'])
                for index in c['reference_indices']:
                    require(type(index) is int and 0 <= index < len(reference['calls']), 'Invalid reference index')
                identities.append(label + ':' + str(c['json']))
        else:
            raise AssertionError('Unsupported raw report format: ' + tool)
        require(len(cases) == n and n > 0, 'Executed call count differs from receipt')
        require(len(identities) == len(set(identities)), 'Duplicated execution evidence')
        require(modes == {False, True}, 'Missing successful uncached dict/JSON executions')
        return {'id': tool, 'format': kind, 'passed_calls': n, 'failed_calls': 0, 'skipped_calls': 0}


def main(config_path):
    require(sys.flags.optimize == 0, 'Sealing requires assertions enabled')
    config = read(config_path)
    root = Path(config['root']).resolve(strict=True)
    app = root / 'app'
    stage = read(root / 'stage-receipt.json')
    assert root.parent == Path('/data/wangjian') and root.name.startswith('github-tools121-remediation-')

    @task
    def check():
        assert source_hashes(app) == stage['source_files'], 'Candidate changed after staging'
        assert source_hashes(Path(stage['live_root'])) == stage['live_files'], 'Live baseline changed'
        registry = read(root / 'registry-validation-r1/result.json')
        assert registry['state'] == 'passed' and registry['source_root'] == str(app)
        assert registry['gpu_used'] is False
        assert all(row['status'] == 'passed' for row in registry['checks'])
        controls = read(root / 'new-controls.json')
        assert controls['source_root'] == str(app) and controls['gpu_used'] is False
        assert controls['returncode'] == 0 and controls['tests'] > 0
        assert all(controls[key] == 0 for key in ('failed', 'errors', 'skipped'))
        tools, evidence = {}, [root / 'registry-validation-r1/result.json', root / 'new-controls.json']
        nested_hashes, semantic_checks = {}, []
        for report_path in config['group_receipts']:
            receipt = read(report_path)
            assert receipt['source_root'] == str(app) and receipt['gpu_used'] is False
            assert receipt['source_files'] and 'catalog/registry.json' in receipt['source_files']
            for relative, digest in receipt['source_files'].items():
                assert stage['source_files'][relative] == digest, relative
                assert sha(app / relative) == digest
            evidence.append(Path(report_path))
            validator = Evidence(app, receipt)
            for row in receipt['tools']:
                assert row['id'] not in tools
                assert row['status'] == 'passed' and row['passed_calls'] > 0
                assert row['failed_calls'] == 0 and row['skipped_calls'] == 0
                assert sha(row['report']) == row['report_sha256']
                semantic_checks.append(validator.tool(row))
                tools[row['id']] = row
                evidence.append(Path(row['report']))
            if 'fresh_positive_worker_jobs' in receipt:
                require(count(receipt['fresh_positive_worker_jobs']) == len(validator.cold_jobs), 'Fresh worker count mismatch')
            nested_hashes.update(validator.files)
        assert set(tools) == set(stage['passed_tool_ids']), 'Published cohort is not exactly replayed'
        assert len(tools) + len(stage['excluded_tool_ids']) == 121
        exclusions = read(config['exclusions'])
        assert {row['id'] for row in exclusions} == set(stage['excluded_tool_ids'])
        assert all(row['reason'] and row['status'] != 'passed' for row in exclusions)
        validate_cohort(stage, tools, exclusions)
        evidence.append(Path(config['exclusions']))
        evidence.extend(nested_hashes)
        evidence = list(dict.fromkeys(map(str, evidence)))
        for path in evidence:
            actual = sha(path)
            require(path not in nested_hashes or nested_hashes[path] == actual, 'Evidence changed during validation')
            nested_hashes[path] = actual
        return {'tools': tools, 'exclusions': exclusions, 'evidence': evidence,
                'evidence_hashes': nested_hashes, 'semantic_checks': semantic_checks,
                'registry': registry, 'controls': controls}

    @task(depends_on=[check])
    def document(check):
        report = {
            'state': 'accepted_for_internal_release',
            'source_root': str(app), 'professional_tools': stage['professional_tools'], 'skills': stage['skills'],
            'cohort_size': 121, 'accepted_cohort': len(check['tools']), 'newly_accepted': len(stage['added_tool_ids']),
            'tools': [check['tools'][name] for name in sorted(check['tools'])], 'excluded': check['exclusions'],
            'gpu_used': False, 'model_calls': False, 'deployment': 'pending', 'git_push': 'pending',
            'browser_acceptance': 'blocked_saved_site_permission', 'ai_lab_certified': False,
            'historical_failures_retained': True,
            'registry_validation': check['registry'], 'new_control_tests': check['controls'],
            'semantic_evidence_checks': check['semantic_checks'],
        }
        relative = 'docs/releases/tools121-remediation-20261026-acceptance.json'
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path, report)
        md = path.with_suffix('.md')
        lines = ['# Tools121 remediation acceptance', '',
                 f"Professional tools: {stage['professional_tools']}; Skills: {stage['skills']}.",
                 f"This release adds {len(stage['added_tool_ids'])} operations; {len(check['tools'])}/121 cohort operations passed.",
                 'All published cohort operations were replayed through the protected production parent runtime.',
                 'No GPU or model calls were used. Deployment, push, and browser acceptance are separate gates.',
                 'Original failed attempts are retained. Internal acceptance is not AI Lab certification.', '',
                 '## Excluded operations', '', '| Tool | Status | Reason |', '| --- | --- | --- |']
        for row in check['exclusions']:
            lines.append('| `' + row['id'] + '` | ' + row['status'] + ' | ' + row['reason'].replace('|', '\\|').replace('\n', ' ') + ' |')
        if not check['exclusions']:
            lines.append('| None | All cohort tools accepted | No exclusion |')
        with md.open('x', encoding='utf-8') as stream:
            stream.write('\n'.join(lines) + '\n')
        return check

    @task(depends_on=[document])
    def seal(document):
        for path, digest in document['evidence_hashes'].items():
            require(sha(path) == digest, 'Evidence changed before seal: ' + path)
        require(source_hashes(Path(stage['live_root'])) == stage['live_files'], 'Live baseline changed before seal')
        stage['source_files'] = source_hashes(app)
        stage['published_files'] = sorted(name for name, digest in stage['source_files'].items()
                                          if stage['live_files'].get(name) != digest)
        stage['state'] = 'release_accepted_pending_commit_and_switch'
        # Retain the staging receipt as immutable evidence before replacing its derived state.
        write(root / 'stage-receipt-original.json', read(root / 'stage-receipt.json'))
        # Raw preflight reports hash-bind stage-receipt.json. Never invalidate
        # that chain by overwriting it; publish the derived state separately.
        write(root / 'stage-receipt-sealed.json', stage)
        patch = root / 'tool-source-patch.tar.gz'
        with tarfile.open(patch, 'w:gz') as archive:
            for relative in stage['published_files']:
                archive.add(app / relative, arcname=relative, recursive=False)
        receipt = {key: stage[key] for key in ('passed_tool_ids', 'excluded_tool_ids', 'professional_tools',
                    'skills', 'source_files', 'live_root', 'live_files', 'expected_live_pid', 'dependency_paths')}
        receipt.update(state='accepted_for_internal_release', source_commit=None,
                       scientific_failed_in_published_subset=0, runtime_failed_in_published_subset=0,
                       formal_skipped_in_published_subset=0, gpu_used=False,
                       evidence_files=[{'path': path, 'sha256': document['evidence_hashes'][path]} for path in document['evidence']],
                       semantic_evidence_checks=document['semantic_checks'])
        write(root / 'acceptance-template.json', receipt)
        result = {'state': stage['state'], 'root': str(root), 'new_tools': len(stage['added_tool_ids']),
                  'accepted_cohort': len(stage['passed_tool_ids']), 'excluded': len(stage['excluded_tool_ids']),
                  'professional_tools': stage['professional_tools'], 'skills': stage['skills'],
                  'patch_sha256': sha(patch), 'changed_files': len(stage['published_files'])}
        write(root / 'SEALED.json', result)
        print(json.dumps(result))

    results = Flow(seal).run()
    for step in results.values():
        if step.error is not None:
            raise step.error
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    raise SystemExit(main(parser.parse_args().config))
