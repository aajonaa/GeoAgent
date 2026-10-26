"""Offline, real-file semantic gates for all four final457-r2 report producers.

No application imports, scientific reruns, source mocks, or source writes.
Geophysics' failed group receipt must reject. Its individual rows are also
tested through an explicitly labelled tool-only projection, never published.
"""
import argparse
from copy import copy, deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path('/data/wangjian/remediate121-20261026-r1')
APP = Path('/data/wangjian/github-tools121-remediation-20261026-r2/app')
RECEIPTS = {
    'geology': ROOT / 'geology/parent-replay/final-r2/release-receipt.json',
    'remote': ROOT / 'remote/parent-replay/final-r2/release-receipt.json',
    'geophysics': ROOT / 'geophysics/release-replay-r1/release-receipt.json',
    'spatial': ROOT / 'spatial/parent-replay/final457-all27-r1.d/release-receipt.json',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for name in ('home', 'cache', 'tmp', 'cases'):
        (args.output / name).mkdir()
    for name in ('HOME', 'MPLCONFIGDIR', 'NUMBA_CACHE_DIR', 'XDG_CACHE_HOME', 'TMPDIR'):
        os.environ[name] = str(args.output / ('home' if name == 'HOME' else 'tmp' if name == 'TMPDIR' else 'cache'))
    os.environ.update(CUDA_VISIBLE_DEVICES='', NVIDIA_VISIBLE_DEVICES='void', HIP_VISIBLE_DEVICES='',
                      ROCR_VISIBLE_DEVICES='', JAX_PLATFORMS='cpu')
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.optimize == 0

    def audit(event, values):
        if event in ('socket.connect', 'socket.bind') or (event == 'import' and str(values[0]).split('.')[0] in {'torch', 'cupy', 'jax', 'tensorflow', 'pycuda'}):
            raise PermissionError('Offline CPU-only gate tests')
        if event == 'open' and isinstance(values[0], (str, bytes, os.PathLike)):
            if (values[2] or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not Path(os.fsdecode(values[0])).resolve().is_relative_to(args.output.resolve()):
                    raise PermissionError('Write outside private controls directory')
    sys.addaudithook(audit)
    flow = load('flowing', args.sources / 'flowing.py')
    load('stage_remediation', args.sources / 'stage_remediation.py')
    subject = load('seal_release', args.sources / 'seal_release.py')
    report = {'gpu_used': False, 'test_only': True, 'application_executed': False,
              'target_sha256': sha(args.sources / 'seal_release.py'), 'cases': [],
              'python': sys.executable, 'python_prefix': sys.prefix,
              'python_realpath': str(Path(sys.executable).resolve()), 'python_version': sys.version,
              'command': sys.argv, 'source_root': str(APP),
              'group_receipts': {k: {'path': str(p), 'sha256': sha(p)} for k, p in RECEIPTS.items()},
              'geophysics_projection': 'Individual raw-tool validation only; failed original group receipt remains rejected.'}
    original_hashes = {}
    bases = {}

    def case(name, expected, operation, **details):
        error = None
        try:
            operation()
        except PermissionError:
            raise
        except (AssertionError, KeyError, ValueError, FileNotFoundError) as exc:
            error = exc
        accepted = error is None
        result = {'name': name, 'expected': 'accepted' if expected else 'rejected',
                  'actual': 'accepted' if accepted else 'rejected',
                  'status': 'passed' if accepted == expected else 'failed', **details}
        if error:
            result['exception_type'] = type(error).__name__
            result['error'] = str(error)[:1200]
        report['cases'].append(result)
        print(json.dumps(result), flush=True)
        return result

    @flow.task
    def originals():
        for group, path in RECEIPTS.items():
            receipt = read(path)
            original_hashes[str(path)] = sha(path)
            case(group + '/original_group_status', receipt.get('status', 'passed') == 'passed',
                 lambda receipt=receipt: subject.Evidence(APP, receipt))
            projection = {k: deepcopy(receipt[k]) for k in ('source_root', 'gpu_used', 'source_files', 'tools')}
            validator = subject.Evidence(APP, projection)
            first = None
            for row in receipt['tools']:
                expected = row['status'] == 'passed'
                result = case(group + '/original/' + row['id'], expected,
                              lambda row=row: validator.tool(row), report=row['report'], report_sha256=row['report_sha256'])
                if expected and result['status'] == 'passed' and first is None:
                    first = row
            original_hashes.update(validator.files)
            if first is not None:
                bases[group] = (validator, first, read(first['report']))
        return len(bases)

    def require_four(originals):
        assert originals == 4, 'Each real producer needs a passing untouched example before mutation tests'

    def mutate(group, name, change):
        base, original_row, original_raw = bases[group]
        directory = args.output / 'cases' / (group + '-' + name)
        directory.mkdir()
        row, raw = deepcopy(original_row), deepcopy(original_raw)
        validator = copy(base)
        validator.files, validator.blobs = dict(base.files), dict(base.blobs)
        if group == 'geology':
            raw_path = directory / 'results' / row['id'] / 'result.json'
            raw_path.parent.mkdir(parents=True)
        else:
            raw_path = directory / 'raw.json'
        change(row, raw, directory)
        dump(raw_path, raw)
        row.update(report=str(raw_path), report_sha256=sha(raw_path))
        if group == 'geology':
            aggregate = read(Path(original_row['report']).parents[2] / 'execution-report.json')
            aggregate['tools'] = [raw if t['tool_id'] == original_row['id'] else t for t in aggregate['tools']]
            aggregate['checks'] = sum(len(t['checks']) for t in aggregate['tools'])
            dump(directory / 'execution-report.json', aggregate)
        return case(group + '/' + name, name == 'unchanged_private_copy', lambda: validator.tool(row),
                    report=str(raw_path), report_sha256=row['report_sha256'])

    def result_mutation(group, mutate_value):
        def change(row, raw, directory):
            if group == 'spatial':
                mutate_value(raw['cases'][0]['result'])
                return
            if group in ('geology', 'remote'):
                c = raw['calls'][0]
                path = c['response']['path'] if group == 'geology' else c['raw_result']
                value = read(path)
                mutate_value(value)
                new = directory / 'changed-response.json'
                dump(new, value)
                if group == 'geology':
                    c['response'] = {'path': str(new), 'sha256': sha(new)}
                else:
                    c.update(raw_result=str(new), raw_result_sha256=sha(new))
                return
            c = next(c for c in raw['cases'] if c['mode'].startswith('runtime_') and not c['negative'])
            call_dir = directory / 'call'
            call_dir.mkdir()
            old_files = deepcopy(c['raw_files'])
            c['evidence'] = str(call_dir)
            new_files = []
            for f in old_files:
                dest = call_dir / Path(f['path']).name
                if dest.name == 'runtime-result.json':
                    value = read(f['path'])
                    mutate_value(value)
                    dump(dest, value)
                elif dest.name == 'replay-check.json':
                    dump(dest, {k: v for k, v in c.items() if k != 'raw_files'})
                else:
                    dest.write_bytes(Path(f['path']).read_bytes())
                new_files.append({'path': str(dest), 'sha256': sha(dest)})
            c['raw_files'] = new_files
        return change

    @flow.task(depends_on=[originals], validate=require_four)
    def negatives(originals):
        for group in bases:
            good = mutate(group, 'unchanged_private_copy', lambda *args: None)
            assert good['status'] == 'passed', 'Invalid mutation harness baseline: ' + group
            mutate(group, 'raw_failed_rehashed', lambda row, raw, d: raw.update(status='failed'))
            mutate(group, 'wrong_tool_rehashed', lambda row, raw, d: raw.update(tool_id='WrongTool', id='WrongTool'))
            mutate(group, 'wrong_source_rehashed', lambda row, raw, d: raw.update(source_root='/wrong/app'))
            mutate(group, 'empty_execution_rehashed', lambda row, raw, d: raw.update({('calls' if 'calls' in raw else 'cases'): []}))
            mutate(group, 'count_inflated', lambda row, raw, d: row.update(passed_calls=row['passed_calls'] + 1))
            mutate(group, 'skipped_receipt', lambda row, raw, d: row.update(skipped_calls=1))
            mutate(group, 'failed_receipt_count', lambda row, raw, d: row.update(failed_calls=1))
            mutate(group, 'case_skipped', lambda row, raw, d: (raw['checks'] if group == 'geology' else raw.get('calls', raw.get('cases')))[0].update(status='skipped'))
            mutate(group, 'duplicate_case', lambda row, raw, d: raw.get('calls', raw.get('cases')).append(deepcopy(raw.get('calls', raw.get('cases'))[0])))
            for name, operation in [
                ('nested_wrong_tool', lambda r: r.update(name='WrongTool')),
                ('nested_cached_success', lambda r: r.update(cached=True)),
                ('nested_no_execution', lambda r: r.update(evidence={'execution': 'not_executed'})),
                ('nested_import_only', lambda r: r.update(data={'provenance': r['data']['provenance']})),
                ('nested_wrong_source', lambda r: r['data']['provenance'].update(implementation_sha256='0' * 64)),
                ('nested_failed_positive', lambda r: r.update(status='error', error={'code': 'unexpected_failure'})),
            ]:
                mutate(group, name, result_mutation(group, operation))
            def bad_hash(row, raw, directory):
                if group == 'spatial':
                    raw['frozen_reference']['sha256'] = '0' * 64
                elif group == 'geology':
                    raw['calls'][0]['response']['sha256'] = '0' * 64
                elif group == 'remote':
                    raw['calls'][0]['raw_result_sha256'] = '0' * 64
                else:
                    raw['cases'][0]['raw_files'][0]['sha256'] = '0' * 64
            mutate(group, 'nested_hash_mismatch', bad_hash)
        stage = read(APP.parent / 'stage-receipt.json')
        tools = {t: {} for t in stage['passed_tool_ids']}
        exclusions = [{'id': t, 'status': 'excluded', 'reason': 'Cohort gate test only'} for t in stage['excluded_tool_ids']]
        case('cohort/original_exact121', True, lambda: subject.validate_cohort(stage, tools, exclusions))
        for name in ('passed_duplicate', 'excluded_duplicate', 'overlap', 'missing_tool', 'extra_tool', 'duplicate_exclusion_row', 'added_outside', 'only120'):
            s, t, e = deepcopy(stage), deepcopy(tools), deepcopy(exclusions)
            if name == 'passed_duplicate': s['passed_tool_ids'].append(s['passed_tool_ids'][0])
            elif name == 'excluded_duplicate': s['excluded_tool_ids'][-1] = s['excluded_tool_ids'][0]
            elif name == 'overlap': s['excluded_tool_ids'][-1] = s['passed_tool_ids'][0]
            elif name == 'missing_tool': t.pop(next(iter(t)))
            elif name == 'extra_tool': t['UnexpectedTool'] = {}
            elif name == 'duplicate_exclusion_row': e.append(deepcopy(e[0]))
            elif name == 'added_outside': s['added_tool_ids'].append('UnexpectedTool')
            elif name == 'only120': s['excluded_tool_ids'].pop(); e.pop()
            case('cohort/' + name, False, lambda: subject.validate_cohort(s, t, e))
        # Actual files, not mocked hashes: a compact receipt intentionally omits
        # one profile-closure source. Both stage and file bytes must bind it.
        for name in ('matching_omitted_source', 'wrong_profile_hash', 'wrong_stage_hash',
                     'changed_actual_bytes', 'missing_stage_entry', 'escaping_path'):
            directory = args.output / 'cases' / ('closure-' + name)
            app = directory / 'app'
            (app / 'catalog').mkdir(parents=True)
            dump(app / 'catalog/registry.json', {'tools': []})
            source = app / 'closure.py'
            source.write_text('VALUE = 7\n', encoding='ascii')
            catalog_sha, source_sha = sha(app / 'catalog/registry.json'), sha(source)
            hashes = {'catalog/registry.json': catalog_sha, 'closure.py': source_sha}
            staged = deepcopy(hashes)
            if name == 'wrong_profile_hash': hashes['closure.py'] = '0' * 64
            elif name == 'wrong_stage_hash': staged['closure.py'] = '0' * 64
            elif name == 'changed_actual_bytes': source.write_text('VALUE = 8\n', encoding='ascii')
            elif name == 'missing_stage_entry': staged.pop('closure.py')
            elif name == 'escaping_path': hashes['../closure.py'] = hashes.pop('closure.py')
            dump(directory / 'stage-receipt.json', {'source_files': staged})
            compact = {'source_root': str(app), 'gpu_used': False,
                       'source_files': {'catalog/registry.json': catalog_sha}}
            validator = subject.Evidence(app, compact)
            case('closure/' + name, name == 'matching_omitted_source', lambda: validator.source_map(hashes))
        return True

    @flow.task(depends_on=[negatives])
    def finish(negatives):
        report['status'] = 'passed' if all(c['status'] == 'passed' for c in report['cases']) else 'failed'
        return report['status']

    try:
        results = flow.Flow(finish).run()
        for step in results.values():
            if step.error is not None:
                raise step.error
    except Exception:
        report['status'] = 'test_execution_failed'
        report['traceback'] = traceback.format_exc()
    report['original_files_unchanged'] = all(sha(p) == h for p, h in original_hashes.items())
    if not report['original_files_unchanged']:
        report['status'] = 'unexpected_original_change'
    report['tests'] = len(report['cases'])
    report['failed_tests'] = sum(c['status'] != 'passed' for c in report['cases'])
    report['validated_original_file_count'] = len(original_hashes)
    dump(args.output / 'results.json', report)
    print(json.dumps({k: report[k] for k in ('status', 'tests', 'failed_tests', 'original_files_unchanged')}), flush=True)
    print(json.dumps({'report': str(args.output / 'results.json'), 'sha256': sha(args.output / 'results.json')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
