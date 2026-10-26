"""Real r3 cold-cache field controls; all mutations are private evidence copies."""
import argparse
from copy import copy, deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

APP = Path('/data/wangjian/github-tools121-remediation-20261026-r3/app')
RECEIPT = Path('/data/wangjian/remediate121-20261026-r1/geophysics/r4/final-parent-r3/release-receipt.json')


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
    assert sys.flags.isolated and sys.flags.no_site and not sys.flags.optimize
    os.environ.update(CUDA_VISIBLE_DEVICES='', NVIDIA_VISIBLE_DEVICES='void', HIP_VISIBLE_DEVICES='',
                      ROCR_VISIBLE_DEVICES='', JAX_PLATFORMS='cpu')
    def audit(event, values):
        if event in ('socket.connect', 'socket.bind') or (event == 'import' and str(values[0]).split('.')[0] in {'torch', 'cupy', 'jax', 'tensorflow', 'pycuda'}):
            raise PermissionError('Offline CPU-only controls')
        if event == 'open' and isinstance(values[0], (str, bytes, os.PathLike)):
            if (values[2] or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not Path(os.fsdecode(values[0])).resolve().is_relative_to(args.output.resolve()):
                    raise PermissionError('Mutation outside private evidence copies')
    sys.addaudithook(audit)
    flow = load('flowing', args.sources / 'flowing.py')
    load('stage_remediation', args.sources / 'stage_remediation.py')
    subject = load('seal_release', args.sources / 'seal_release.py')
    receipt = read(RECEIPT)
    original_row = receipt['tools'][0]
    original_raw = read(original_row['report'])
    base = subject.Evidence(APP, receipt)
    report = {'status': 'running', 'gpu_used': False, 'test_only': True, 'cases': [],
              'source_root': str(APP), 'sealer_sha256': sha(args.sources / 'seal_release.py'),
              'receipt': str(RECEIPT), 'receipt_sha256': sha(RECEIPT),
              'raw_report': original_row['report'], 'raw_report_sha256': sha(original_row['report']),
              'python': sys.executable, 'python_version': sys.version}
    original_hashes = {str(RECEIPT): sha(RECEIPT), original_row['report']: sha(original_row['report'])}

    def run(name):
        directory = args.output / name
        directory.mkdir()
        row, raw = deepcopy(original_row), deepcopy(original_raw)
        validator = copy(base)
        validator.files, validator.blobs = dict(base.files), dict(base.blobs)
        validator.receipt, validator.cold_jobs = deepcopy(receipt), set()
        c = next(c for c in raw['cases'] if 'cold_cache_evidence' in c)
        cold = c['cold_cache_evidence']
        if name == 'wrong_directory':
            cold['job'] = next(x['cold_cache_evidence']['job'] for x in raw['cases']
                               if 'cold_cache_evidence' in x and x['cold_cache_evidence']['job'] != cold['job'])
        elif name == 'wrong_source_hash':
            cold['source_binding']['sha256'] = '0' * 64
            validator.receipt['source_binding'] = deepcopy(cold['source_binding'])
        elif name == 'missing_field':
            c.pop('cold_cache_evidence')
        elif name == 'unknown_extra':
            cold['unrecognized'] = True
        elif name == 'unknown_case_extra':
            c['unrecognized'] = True
        elif name == 'false_fresh_flag':
            cold['fresh_private_worker_job'] = False
        elif name == 'missing_job_key':
            cold.pop('job')
        elif name in ('wrong_source_root', 'wrong_manifest_root', 'preexisting_job', 'missing_manifest_tool', 'wrong_registry_hash'):
            binding = read(cold['source_binding']['path'])
            if name == 'wrong_source_root': binding['source_root'] = '/wrong/app'
            elif name == 'wrong_manifest_root': binding['cold_cache_baseline'][row['id']]['root'] = '/wrong/jobs'
            elif name == 'preexisting_job': binding['cold_cache_baseline'][row['id']]['preexisting_jobs'].append(cold['job'])
            elif name == 'missing_manifest_tool': binding['cold_cache_baseline'].pop(row['id'])
            elif name == 'wrong_registry_hash': binding['profile_registry']['sha256'] = '0' * 64
            path = directory / 'source-binding.json'
            dump(path, binding)
            descriptor = {'path': str(path), 'sha256': sha(path)}
            validator.receipt['source_binding'] = descriptor
            for call in raw['cases']:
                if 'cold_cache_evidence' in call:
                    call['cold_cache_evidence']['source_binding'] = deepcopy(descriptor)
        path = directory / 'raw.json'
        dump(path, raw)
        row.update(report=str(path), report_sha256=sha(path))
        error = None
        try:
            validator.tool(row)
        except PermissionError:
            raise
        except (AssertionError, KeyError, ValueError, FileNotFoundError) as exc:
            error = exc
        expected = name == 'complete_real_copy'
        result = {'name': name, 'expected': 'accepted' if expected else 'rejected',
                  'actual': 'accepted' if error is None else 'rejected',
                  'status': 'passed' if (error is None) == expected else 'failed',
                  'report': str(path), 'report_sha256': sha(path)}
        if error:
            result.update(exception_type=type(error).__name__, error=str(error)[:1000])
        report['cases'].append(result)
        if expected and error is None:
            original_hashes.update({p: h for p, h in validator.files.items() if not Path(p).is_relative_to(args.output)})
        print(json.dumps(result), flush=True)
        return result

    @flow.task
    def positive():
        return run('complete_real_copy')

    def require_positive(positive):
        assert positive['status'] == 'passed', 'Real positive required before negative controls'

    @flow.task(depends_on=[positive], validate=require_positive)
    def negatives(positive):
        return [run(name) for name in ('wrong_directory', 'wrong_source_hash', 'missing_field', 'unknown_extra',
                'unknown_case_extra', 'false_fresh_flag', 'missing_job_key', 'wrong_source_root',
                'wrong_manifest_root', 'preexisting_job', 'missing_manifest_tool', 'wrong_registry_hash')]

    try:
        results = flow.Flow(negatives).run()
        for step in results.values():
            if step.error is not None:
                raise step.error
        report['status'] = 'passed' if all(c['status'] == 'passed' for c in report['cases']) else 'failed'
    except Exception:
        report.update(status='test_execution_failed', traceback=traceback.format_exc())
    report['tests'] = len(report['cases'])
    report['failed_tests'] = sum(c['status'] != 'passed' for c in report['cases'])
    report['original_files_unchanged'] = all(sha(p) == h for p, h in original_hashes.items())
    if not report['original_files_unchanged']:
        report['status'] = 'unexpected_original_change'
    dump(args.output / 'results.json', report)
    print(json.dumps({k: report[k] for k in ('status', 'tests', 'failed_tests', 'original_files_unchanged')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
