"""Execute the sealer's exact pre-document check body, never document/seal.

Only the nested check's Flow decorator is removed in memory. All source,
receipt, cohort and semantic comparisons remain the actual sealer code.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', type=Path, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    assert sys.flags.isolated and sys.flags.no_site and not sys.flags.optimize
    os.environ.update(CUDA_VISIBLE_DEVICES='', NVIDIA_VISIBLE_DEVICES='void', HIP_VISIBLE_DEVICES='',
                      ROCR_VISIBLE_DEVICES='', JAX_PLATFORMS='cpu')
    def audit(event, values):
        if event in ('socket.connect', 'socket.bind') or (event == 'import' and str(values[0]).split('.')[0] in {'torch', 'cupy', 'jax', 'tensorflow', 'pycuda'}):
            raise PermissionError('Offline CPU-only source checks')
        if event == 'open' and isinstance(values[0], (str, bytes, os.PathLike)):
            if (values[2] or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if Path(os.fsdecode(values[0])).resolve() != args.report.resolve():
                    raise PermissionError('CHECK-only cannot modify application or evidence')
    sys.addaudithook(audit)
    load('flowing', args.sources / 'flowing.py')
    load('stage_remediation', args.sources / 'stage_remediation.py')
    subject = load('seal_release', args.sources / 'seal_release.py')
    source = (args.sources / 'seal_release.py').read_bytes()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    prefix = []
    for statement in fn.body:
        if isinstance(statement, ast.FunctionDef) and statement.name == 'document':
            break
        if isinstance(statement, ast.FunctionDef) and statement.name == 'check':
            statement.decorator_list = []
        prefix.append(statement)
    assert any(isinstance(n, ast.FunctionDef) and n.name == 'check' for n in prefix)
    fn.body = prefix + [ast.Return(ast.Call(ast.Name('check', ast.Load()), [], []))]
    check_tree = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(check_tree, str(args.sources / 'seal_release.py') + ':CHECK-only', 'exec'), subject.__dict__)
    report = {'status': 'running', 'gpu_used': False, 'document_executed': False, 'seal_executed': False,
              'source_sha256': hashlib.sha256(source).hexdigest(), 'config': str(args.config),
              'config_sha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
              'check_ast_sha256': hashlib.sha256(ast.dump(check_tree).encode()).hexdigest(),
              'python': sys.executable, 'python_version': sys.version}
    try:
        result = subject.main(args.config)
        tools = list(result['tools'].values())
        report.update(status='passed', tool_count=len(tools),
                      passed_calls=sum(t['passed_calls'] for t in tools),
                      failed_calls=sum(t['failed_calls'] for t in tools),
                      skipped_calls=sum(t['skipped_calls'] for t in tools),
                      evidence_file_count=len(result['evidence_hashes']),
                      evidence_hashes_sha256=hashlib.sha256(json.dumps(result['evidence_hashes'], sort_keys=True).encode()).hexdigest(),
                      semantic_checks=result['semantic_checks'])
    except Exception:
        report.update(status='failed', traceback=traceback.format_exc())
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'semantic_checks'}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
