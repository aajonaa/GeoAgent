"""Bounded real-file gate tests; never edit a parent script or release candidate.

The only test seam replaces seal_release.Path('/data/wangjian') with the
current private fixture parent. All other Path calls, source_hashes, sha,
Flow tasks, archive generation, and sealing are the original implementations.
An additional case runs without the seam and verifies root rejection.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import traceback

BASE = Path('C:/Users/jona/g121fix1/tests_local/remediate121')
OWN = BASE / 'spatial/parent-review'
PARENT = BASE / 'parent'
FLOW = BASE / 'spatial/handoffs/spatial20-r3-v1/flowing.py'
OLD_RECEIPT = BASE / 'spatial/parent-replay/handoffs/final434-spatial27-r1-v1/release-receipt.json'
ACCEPTED = 'FixtureAddTwoNumbers'
CASES = (
    'unadapted_production_anchor', 'wrong_root_prefix',
    'candidate_source_mutated', 'candidate_source_added', 'candidate_source_removed',
    'live_source_mutated', 'receipt_source_digest_bad', 'missing_tool',
    'failed_receipt_status', 'zero_calls_receipt', 'failed_calls_receipt',
    'skipped_calls_receipt', 'evidence_digest_bad', 'evidence_bytes_changed',
    'registry_failed', 'controls_skipped',
    'raw_report_failed_valid_hash', 'raw_report_skipped_valid_hash',
    'raw_report_wrong_source_valid_hash', 'raw_report_no_execution_valid_hash',
    'raw_report_wrong_tool_valid_hash', 'cohort_overlap', 'excluded_duplicates',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture(directory, source_hashes):
    directory.mkdir()
    root = directory / 'github-tools121-remediation-fixture-only'
    app = root / 'app'
    live = directory / 'live-fixture'
    (app / 'catalog').mkdir(parents=True)
    live.mkdir()
    module = app / 'fixture_operation.py'
    module.write_text('def add(a, b):\n    return a + b\n', encoding='ascii')
    (live / 'baseline.py').write_text('BASELINE = 1\n', encoding='ascii')
    contract = app / 'geological_agent/geology/collection_contracts.py'
    contract.parent.mkdir(parents=True)
    contract.write_text('# Private real-file fixture contract.\n', encoding='ascii')
    dump(app / 'catalog/registry.json', {'tools': [{'id': ACCEPTED, 'source_interface': {
        'entrypoint': {'callable': 'fixture_operation:add'}}}], 'skills': []})
    # The successful toy operation is actually executed; its files and output
    # are real test inputs, never claimed as GeoAgent scientific acceptance.
    operation = runpy.run_path(str(module))['add']
    actual = operation(1, 2)
    assert actual == 3
    reference_path = directory / 'independent-reference.json'
    dump(reference_path, {'id': ACCEPTED, 'status': 'passed', 'gpu_used': False,
                         'calls': [{'actual': operation(1, 2)}, {'actual': operation(1, 2)}]})
    cases = []
    for mode in (False, True):
        cases.append({'label': 'positive-0', 'json': mode, 'input_json': '[1,2]',
                      'reference_indices': [int(mode)], 'status': 'passed',
                      'result': {'name': ACCEPTED, 'status': 'ok', 'cached': False,
                                 'error': None, 'evidence': {'execution': 'executed'},
                                 'data': {'sum': operation(1, 2), 'provenance': {
                                     'tool': ACCEPTED, 'network_required': False,
                                     'implementation_sha256': sha(module), 'contract_sha256': sha(contract)}}}})
    raw = {'test_only': True, 'tool_id': ACCEPTED, 'source_root': str(app),
           'source_sha256': sha(module), 'status': 'passed', 'gpu_used': False,
           'passed_calls': 2, 'failed_calls': 0, 'skipped_calls': 0, 'model_calls': False,
           'parent': {'pythonpath': str(app) + ':private-test-only'},
           'frozen_reference': {'path': str(reference_path), 'sha256': sha(reference_path)},
           'coverage': {'reference_call_count': 2, 'distinct_positive_inputs': 1, 'frozen_negative_calls': 0},
           'cases': cases}
    raw_path = directory / 'raw-tool-report.json'
    dump(raw_path, raw)
    stage = {'test_only': True, 'source_files': source_hashes(app),
             'live_root': str(live), 'live_files': source_hashes(live),
             'passed_tool_ids': [ACCEPTED],
             'excluded_tool_ids': ['ExcludedFixture%03d' % i for i in range(120)],
             'added_tool_ids': [ACCEPTED], 'professional_tools': 1, 'skills': 0,
             'expected_live_pid': 0, 'dependency_paths': []}
    dump(root / 'stage-receipt.json', stage)
    (root / 'registry-validation-r1').mkdir()
    registry = {'state': 'passed', 'source_root': str(app), 'gpu_used': False,
                'checks': [{'name': 'real_tiny_catalog', 'status': 'passed'}]}
    dump(root / 'registry-validation-r1/result.json', registry)
    controls = {'source_root': str(app), 'gpu_used': False, 'returncode': 0,
                'tests': 1, 'failed': 0, 'errors': 0, 'skipped': 0}
    dump(root / 'new-controls.json', controls)
    receipt = {'source_root': str(app), 'gpu_used': False,
               'source_files': deepcopy(stage['source_files']),
               'tools': [{'id': ACCEPTED, 'status': 'passed', 'passed_calls': 2,
                          'failed_calls': 0, 'skipped_calls': 0,
                          'report': str(raw_path), 'report_sha256': sha(raw_path)}]}
    receipt_path = directory / 'group-receipt.json'
    dump(receipt_path, receipt)
    exclusions = [{'id': name, 'status': 'excluded', 'reason': 'Outside this synthetic unit fixture'}
                  for name in stage['excluded_tool_ids']]
    exclusions_path = directory / 'exclusions.json'
    dump(exclusions_path, exclusions)
    config = {'root': str(root), 'group_receipts': [str(receipt_path)],
              'exclusions': str(exclusions_path)}
    config_path = directory / 'config.json'
    dump(config_path, config)
    return locals()


def mutate(name, f):
    row = f['receipt']['tools'][0]
    if name == 'wrong_root_prefix':
        other = f['directory'] / 'not-an-authorized-release'
        (other / 'app').mkdir(parents=True)
        dump(other / 'stage-receipt.json', f['stage'])
        f['config']['root'] = str(other)
    elif name == 'candidate_source_mutated':
        f['module'].write_text('def add(a, b):\n    return a - b\n', encoding='ascii')
    elif name == 'candidate_source_added':
        (f['app'] / 'unreviewed.py').write_text('UNREVIEWED = True\n', encoding='ascii')
    elif name == 'candidate_source_removed':
        f['module'].unlink()
    elif name == 'live_source_mutated':
        (f['live'] / 'baseline.py').write_text('BASELINE = 2\n', encoding='ascii')
    elif name == 'receipt_source_digest_bad':
        f['receipt']['source_files']['fixture_operation.py'] = '0' * 64
    elif name == 'missing_tool':
        f['receipt']['tools'] = []
    elif name == 'failed_receipt_status':
        row['status'] = 'failed'
    elif name == 'zero_calls_receipt':
        row['passed_calls'] = 0
    elif name == 'failed_calls_receipt':
        row['failed_calls'] = 1
    elif name == 'skipped_calls_receipt':
        row['skipped_calls'] = 1
    elif name == 'evidence_digest_bad':
        row['report_sha256'] = '0' * 64
    elif name == 'evidence_bytes_changed':
        f['raw']['unexpected_change'] = True
        dump(f['raw_path'], f['raw'])
    elif name == 'registry_failed':
        f['registry']['checks'][0]['status'] = 'failed'
    elif name == 'controls_skipped':
        f['controls']['skipped'] = 1
    elif name.startswith('raw_report_'):
        raw = f['raw']
        if name == 'raw_report_failed_valid_hash':
            raw.update(status='failed', passed_calls=0, failed_calls=1,
                       cases=[{'status': 'failed', 'error': 'fixture numerical failure'}])
        elif name == 'raw_report_skipped_valid_hash':
            raw.update(status='skipped', passed_calls=0, skipped_calls=1, cases=[])
        elif name == 'raw_report_wrong_source_valid_hash':
            other = f['directory'] / 'different-real-source'
            other.mkdir()
            wrong_module = other / 'fixture_operation.py'
            wrong_module.write_text('def add(a, b):\n    return a - b\n', encoding='ascii')
            raw.update(source_root=str(other), source_sha256=sha(wrong_module))
        elif name == 'raw_report_no_execution_valid_hash':
            raw.update(passed_calls=0, cases=[])
        elif name == 'raw_report_wrong_tool_valid_hash':
            raw['tool_id'] = 'NotThePublishedTool'
        dump(f['raw_path'], raw)
        row['report_sha256'] = sha(f['raw_path'])
    elif name == 'cohort_overlap':
        f['stage']['excluded_tool_ids'][-1] = ACCEPTED
        f['exclusions'][-1]['id'] = ACCEPTED
    elif name == 'excluded_duplicates':
        f['stage']['excluded_tool_ids'][-1] = f['stage']['excluded_tool_ids'][0]
        f['exclusions'][-1]['id'] = f['exclusions'][0]['id']
    elif name not in ('complete_fixture', 'unadapted_production_anchor'):
        raise AssertionError('Unknown bounded case: ' + name)
    dump(f['root'] / 'stage-receipt.json', f['stage'])
    dump(f['receipt_path'], f['receipt'])
    dump(f['root'] / 'registry-validation-r1/result.json', f['registry'])
    dump(f['root'] / 'new-controls.json', f['controls'])
    dump(f['exclusions_path'], f['exclusions'])
    dump(f['config_path'], f['config'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='Fresh private run directory name')
    args = parser.parse_args()
    assert args.run and '/' not in args.run and '\\' not in args.run
    root = OWN / 'runs' / args.run
    root.mkdir(parents=True)
    for directory in ('sources', 'cases', 'logs', 'home', 'cache', 'tmp'):
        (root / directory).mkdir()
    for name in ('HOME', 'USERPROFILE', 'MPLCONFIGDIR', 'NUMBA_CACHE_DIR', 'XDG_CACHE_HOME', 'TMPDIR', 'TMP', 'TEMP'):
        os.environ[name] = str(root / ('home' if name in ('HOME', 'USERPROFILE') else 'tmp' if name in ('TMPDIR', 'TMP', 'TEMP') else 'cache'))
    os.environ.update(CUDA_VISIBLE_DEVICES='', NVIDIA_VISIBLE_DEVICES='void', HIP_VISIBLE_DEVICES='',
                      ROCR_VISIBLE_DEVICES='', JAX_PLATFORMS='cpu', JAX_PLATFORM_NAME='cpu')
    originals = [PARENT / 'seal_release.py', PARENT / 'stage_remediation.py', FLOW, OLD_RECEIPT]
    before = {str(path): sha(path) for path in originals}
    report = {'status': 'running', 'gpu_used': False, 'test_only': True, 'cases': [],
              'target': str(originals[0]), 'target_sha256': before[str(originals[0])],
              'original_hashes': before, 'python': sys.executable, 'python_version': sys.version,
              'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site,
              'optimization': sys.flags.optimize, 'scope': __doc__}
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.optimize == 0
    for source in originals[:3]:
        target = root / 'sources' / source.name
        shutil.copyfile(source, target)
        assert sha(target) == before[str(source)]
    text = (root / 'sources/seal_release.py').read_text(encoding='utf-8')
    report['source_locations'] = {
        needle: next(i for i, line in enumerate(text.splitlines(), 1) if needle in line)
        for needle in ('assert sha(row[\'report\'])', 'assert set(tools)',
                       'assert len(tools)', "assert {row['id'] for row in exclusions}",
                       'for relative, digest in receipt', 'assert source_hashes(app)')}

    def audit(event, values):
        if event in ('socket.connect', 'socket.bind') or (event == 'import' and str(values[0]).split('.')[0] in {'torch', 'cupy', 'jax', 'tensorflow', 'pycuda'}):
            raise PermissionError('Offline CPU-only test policy')
        if event == 'open' and isinstance(values[0], (str, bytes, os.PathLike)):
            flags = values[2] or 0
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(values[0])).resolve()
                if not path.is_relative_to(OWN.resolve()):
                    raise PermissionError('Test writes must remain under parent-review: ' + str(path))
    sys.addaudithook(audit)
    flowing = load('flowing', root / 'sources/flowing.py')
    stage = load('stage_remediation', root / 'sources/stage_remediation.py')
    subject = load('seal_release_under_test', root / 'sources/seal_release.py')

    def run_case(name):
        f = fixture(root / 'cases' / name, stage.source_hashes)
        mutate(name, f)
        expected = 'accepted' if name == 'complete_fixture' else 'rejected'
        anchor = f['directory']
        def private_path(value='.'):
            return anchor if str(value) == '/data/wangjian' else Path(value)
        subject.Path = Path if name == 'unadapted_production_anchor' else private_path
        log_path = root / 'logs' / (name + '.log')
        evidence = {'name': name, 'expected': expected, 'config': str(f['config_path']),
                    'fixture_root': str(f['root']), 'root_anchor_mapped': name != 'unadapted_production_anchor',
                    'log': str(log_path), 'before_candidate_hashes': stage.source_hashes(f['app'])}
        error = None
        with log_path.open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
            try:
                code = subject.main(f['config_path'])
                evidence['returncode'] = code
            except PermissionError:
                evidence['policy_denied'] = True
                raise
            except Exception as exc:
                error = exc
                evidence['exception_type'] = type(exc).__name__
                evidence['traceback'] = traceback.format_exc()
                log.write(evidence['traceback'])
            finally:
                subject.Path = Path
        sealed = f['root'] / 'SEALED.json'
        accepted = error is None and evidence.get('returncode') == 0 and sealed.is_file()
        rejected = isinstance(error, AssertionError) and not sealed.exists()
        evidence.update(actual='accepted' if accepted else 'rejected' if rejected else 'harness_or_unexpected_error',
                        sealed_path=str(sealed) if sealed.exists() else None,
                        sealed_sha256=sha(sealed) if sealed.exists() else None)
        evidence['status'] = 'passed' if evidence['actual'] == expected else 'failed'
        if expected == 'rejected' and accepted:
            evidence['finding'] = 'Unexpected acceptance: original sealing workflow wrote SEALED.json'
        report['cases'].append(evidence)
        print(json.dumps({key: evidence[key] for key in ('name', 'expected', 'actual', 'status')}), flush=True)
        return evidence

    @flowing.task
    def positive():
        return run_case('complete_fixture')

    def require_positive(positive):
        assert positive['status'] == 'passed' and positive['actual'] == 'accepted', 'Cannot trust rejection tests without a passing real-file baseline'

    @flowing.task(depends_on=[positive], validate=require_positive)
    def negative(positive):
        return [run_case(name) for name in CASES]

    @flowing.task(depends_on=[negative])
    def summary(negative):
        assert len(report['cases']) == 24
        report['test_count'] = len(report['cases'])
        report['passed_tests'] = sum(case['status'] == 'passed' for case in report['cases'])
        report['failed_tests'] = report['test_count'] - report['passed_tests']
        report['unexpected_acceptances'] = [case['name'] for case in report['cases'] if case.get('finding')]
        report['status'] = 'defects_found' if report['failed_tests'] else 'passed'
        return report['status']

    try:
        result = flowing.Flow(summary).run()
        for step in result.values():
            if step.error is not None:
                raise step.error
    except Exception:
        report['status'] = 'test_execution_failed'
        report['traceback'] = traceback.format_exc()
    finally:
        after = {str(path): sha(path) for path in originals}
        report['originals_unchanged'] = before == after
        report['preserved_612_receipt_sha256'] = after[str(OLD_RECEIPT)]
        if before != after:
            report['status'] = 'original_changed_abort'
        dump(root / 'results.json', report)
        print(json.dumps({'report': str(root / 'results.json'), 'report_sha256': sha(root / 'results.json'),
                          'status': report['status'], 'tests': report.get('test_count'),
                          'failed_tests': report.get('failed_tests'), 'originals_unchanged': report['originals_unchanged']}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
