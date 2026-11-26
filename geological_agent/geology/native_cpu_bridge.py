"""Fixed, hash-bound CPU profile transport. Never installs or compiles tools."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from jsonschema import Draft202012Validator
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

CATALOG_ROOT = Path(__file__).resolve().parents[2]
PROFILE_FILE = Path(__file__).with_name('native-cpu-profiles.json')


def fail(message, code='invalid_arguments'):
    raise ScientificToolError(code, message, retryable=False)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON object key: ' + key)
        result[key] = value
    return result


def strict_json(value):
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        fail('Nonfinite arguments are not accepted.')
    if isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            finite_tree(child)


def binding_for(name):
    if not PROFILE_FILE.is_file() or PROFILE_FILE.is_symlink():
        fail('The reviewed CPU profile has not been prepared.', 'missing_dependency')
    profile = strict_json(PROFILE_FILE.read_text(encoding='utf-8'))
    if profile.get('protocol') != 'fixed-cpu-arguments-json-v1' or name not in profile.get('operations', {}):
        fail('No fixed CPU profile exists for this operation.', 'missing_dependency')
    binding = profile['operations'][name]
    for key in ('root', 'python', 'entrypoint'):
        if not isinstance(binding.get(key), str) or not Path(binding[key]).is_absolute():
            fail('CPU profile contains an invalid fixed path.', 'integrity_error')
    try:
        root = Path(binding['root']).resolve(strict=True)
        entrypoint = Path(binding['entrypoint']).resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        fail('Prepared CPU dependency directory or fixed entrypoint is unavailable.', 'missing_dependency')
    if not entrypoint.is_relative_to(root) or Path(binding['entrypoint']).is_symlink():
        fail('CPU entrypoint escapes its reviewed profile.', 'integrity_error')
    files = binding.get('files_sha256', {})
    if not files or str(entrypoint) not in files or binding['python'] not in files:
        fail('CPU profile lacks executable/source integrity bindings.', 'integrity_error')
    for absolute, expected in files.items():
        path = Path(absolute)
        if not path.is_absolute() or not path.is_file() or digest(path) != expected:
            fail('CPU dependency/source integrity mismatch: ' + path.name, 'integrity_error')
    return binding


def specification(name):
    catalog = strict_json((CATALOG_ROOT / 'catalog/registry.json').read_text(encoding='utf-8'))
    rows = [row for row in catalog['tools'] if row['id'] == name]
    if len(rows) != 1:
        fail('CPU operation must have exactly one reviewed schema.', 'integrity_error')
    return rows[0]


def arguments(spec, value, args):
    if value is not None and args is not None:
        fail('Supply either the positional object or args=, not both.')
    value = args if args is not None else value
    if isinstance(value, str):
        if len(value.encode('utf-8')) > 262144:
            fail('Argument JSON exceeds the fixed 256 KiB bound.', 'resource_limit')
        try:
            value = strict_json(value)
        except (ValueError, TypeError, RecursionError):
            fail('Arguments must be valid finite JSON with unique keys.')
    if not isinstance(value, dict):
        fail('Arguments must be a JSON object.')
    try:
        finite_tree(value)
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError, RecursionError, OverflowError):
        fail('Arguments must contain bounded JSON-compatible values.')
    if len(encoded) > 262144:
        fail('Argument JSON exceeds the fixed 256 KiB bound.', 'resource_limit')
    errors = list(Draft202012Validator(spec['input_schema']).iter_errors(value))
    if errors:
        fail('Arguments do not satisfy the reviewed schema: ' + errors[0].message)
    return encoded


def invoke(name, value=None, *, args=None, output_dir=None, implementation_path=None):
    if output_dir is not None:
        fail('This CPU kernel returns JSON and does not write artifacts.')
    spec = specification(name)
    encoded = arguments(spec, value, args)
    binding = binding_for(name)
    root = Path(binding['root']).resolve(strict=True)
    cache = root / 'runtime-private-cache'
    cache.mkdir(mode=0o700, exist_ok=True)
    if cache.is_symlink() or not cache.resolve().is_relative_to(root):
        fail('CPU cache root is not private to the reviewed profile.', 'integrity_error')
    with tempfile.TemporaryDirectory(prefix='call-', dir=cache) as directory:
        private = Path(directory)
        env = {key: os.environ[key] for key in ('PATH', 'LD_LIBRARY_PATH') if key in os.environ}
        env.update(CUDA_VISIBLE_DEVICES='', NVIDIA_VISIBLE_DEVICES='none', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONPATH=str(CATALOG_ROOT), PYTHONUTF8='1', LANG='C.UTF-8', LC_ALL='C.UTF-8', LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false', GEOTOOL_LANGSMITH_ENABLED='0', PROJ_NETWORK='OFF', OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', NUMBA_NUM_THREADS='4')
        for key, suffix in [('MPLCONFIGDIR', 'matplotlib'), ('NUMBA_CACHE_DIR', 'numba'), ('XDG_CACHE_HOME', 'xdg'), ('HOME', 'home'), ('TMPDIR', 'tmp')]:
            target = private / suffix
            target.mkdir(mode=0o700)
            env[key] = str(target)
        try:
            process = subprocess.run([binding['python'], binding['entrypoint'], name], input=encoded, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root, env=env, timeout=binding.get('timeout_seconds'), check=False)
        except subprocess.TimeoutExpired:
            fail('The administrator-configured CPU execution allowance was exceeded.', 'resource_limit')
        except OSError as error:
            fail('Prepared CPU entrypoint could not start: ' + str(error), 'missing_dependency')
    if len(process.stdout) > 2097152 or len(process.stderr) > 2097152:
        fail('CPU response exceeded the fixed output bound.', 'resource_limit')
    try:
        response = strict_json(process.stdout.decode('utf-8', errors='strict'))
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        fail('CPU entrypoint returned an invalid JSON protocol response.', 'invalid_result')
    if not isinstance(response, dict):
        fail('CPU entrypoint response must be an object.', 'invalid_result')
    if response.get('status') == 'error' and process.returncode != 0:
        error = response.get('error', {})
        allowed = set(spec['error_contract']['codes'])
        code = error.get('code')
        if code not in allowed or not isinstance(error.get('message'), str) or error.get('retryable') is not False:
            fail('CPU error response does not match its declared error contract.', 'invalid_result')
        fail(error['message'], code)
    if process.returncode != 0 or response.get('status') != 'ok' or response.get('tool') != name:
        fail('CPU process exit status and operation response disagree.', 'invalid_result')
    result = response.get('data')
    if not isinstance(result, dict) or not isinstance(result.get('provenance'), dict):
        fail('CPU result lacks structured execution provenance.', 'invalid_result')
    proof = result['provenance']
    if proof.get('tool') != name or proof.get('binary_sha256') != binding['binary_sha256'] or proof.get('build_receipt_sha256') != binding['build_receipt_sha256']:
        fail('CPU response is not bound to the reviewed kernel build.', 'integrity_error')
    if proof.get('output_sha256') != {} or result.get('artifacts') not in (None, []):
        fail('This kernel must not claim file artifacts.', 'invalid_result')
    result['artifacts'] = []
    proof['upstream_adapter_sha256'] = proof.get('implementation_sha256')
    proof['implementation_sha256'] = digest(implementation_path or Path(__file__))
    proof['cpu_bridge_sha256'] = digest(Path(__file__))
    proof['cpu_profile_sha256'] = digest(PROFILE_FILE)
    proof['execution_mode'] = 'fixed_cpu_dependency_profile'
    proof['gpu_used'] = False
    proof['runtime_install'] = False
    proof['runtime_compile'] = False
    errors = list(Draft202012Validator(spec['output_schema']).iter_errors(result))
    if errors:
        fail('CPU result violates the registered output schema: ' + errors[0].message, 'invalid_result')
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        fail('CPU result contains invalid or nonfinite JSON.', 'invalid_result')
    return result
