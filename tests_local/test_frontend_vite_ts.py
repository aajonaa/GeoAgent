"""P2-3 verification: Vite + TypeScript frontend bundles, manifest integrity, CSP & dual-mode serving."""
import hashlib
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from geological_agent.team.server import create_app
from geological_agent.team.server_helpers import _PLAN_TEXT_LIMITS


class _DummyRunner:
    def stop(self, rid):
        pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bundles_dir() -> Path:
    return _repo_root() / 'geological_agent' / 'team' / 'web' / 'bundles'


def test_vite_bundle_manifest_integrity_and_csp_safety():
    bundles = _bundles_dir()
    manifest_path = bundles / 'bundles-manifest.json'
    assert manifest_path.is_file(), 'Expected Vite build output bundles-manifest.json'

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['schema'] == 1
    assert manifest['entry'] == 'core-bridge.js'
    assert manifest['globalNamespace'] == 'OreBogaoCore'
    assert manifest['cspSafe'] is True
    assert 'core-bridge.js' in manifest['files']

    for filename, meta in manifest['files'].items():
        file_path = bundles / filename
        assert file_path.is_file(), f'Manifest entry missing on disk: {filename}'
        raw = file_path.read_bytes()
        assert len(raw) == meta['size']
        assert hashlib.sha256(raw).hexdigest() == meta['sha256']

    js_text = (bundles / 'core-bridge.js').read_text(encoding='utf-8')
    assert 'OreBogaoCore' in js_text
    assert 'eval(' not in js_text
    assert 'new Function(' not in js_text


def test_dual_mode_bundle_serving_security_headers_and_traversal_block(tmp_path):
    app = create_app(tmp_path / 'state', runner=_DummyRunner())
    try:
        with TestClient(app, base_url='http://127.0.0.1') as client:
            # Built Vite bundle served with strict security headers
            js_resp = client.get('/assets/bundles/core-bridge.js')
            assert js_resp.status_code == 200
            assert 'javascript' in js_resp.headers['content-type']
            assert js_resp.headers['cache-control'] == 'no-store'
            assert js_resp.headers['referrer-policy'] == 'no-referrer'
            csp = js_resp.headers['content-security-policy']
            assert "script-src 'self'" in csp and 'unsafe-inline' not in csp

            manifest_resp = client.get('/assets/bundles/bundles-manifest.json')
            assert manifest_resp.status_code == 200
            assert manifest_resp.json()['entry'] == 'core-bridge.js'

            # Path traversal and disallowed extensions fail closed
            for bad_path in (
                '/assets/bundles/..%2findex.html',
                '/assets/bundles/..%2fapp.js',
                '/assets/bundles/nonexistent.js',
                '/assets/bundles/.hidden.js',
                '/assets/bundles/server.py',
            ):
                assert client.get(bad_path).status_code == 404, f'Expected 404 for {bad_path}'

            # Legacy static assets and index page continue working untouched
            assert client.get('/').status_code == 200
            for legacy in ('app.js', 'drafts.js', 'recovery.js', 'research-plan.js', 'presentation-state.js'):
                assert client.get('/assets/' + legacy).status_code == 200
    finally:
        app.state.store.close()


def test_typescript_plan_limits_stay_synced_with_backend():
    ts_path = _repo_root() / 'frontend' / 'src' / 'modules' / 'researchPlan.ts'
    assert ts_path.is_file()
    source = ts_path.read_text(encoding='utf-8')
    for field, limit in _PLAN_TEXT_LIMITS.items():
        pattern = rf'\b{re.escape(field)}\s*:\s*{limit}\b'
        assert re.search(pattern, source), f'TS PLAN_TEXT_LIMITS mismatch for {field}: expected {limit}'
