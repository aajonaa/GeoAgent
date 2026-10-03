#!/usr/bin/env bash
# Run real integration tests without using the production database.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
config="${1:-${GEOTOOL_INTEGRATION_ENV_FILE:-}}"
if [[ $# -gt 0 ]]; then
    shift
fi
if [[ -n "$config" ]]; then
    if [[ ! -r "$config" ]]; then
        printf 'Integration configuration is not readable: %s\n' "$config" >&2
        exit 1
    fi
    # This must be an operator-owned shell configuration, not uploaded content.
    set -a
    source "$config"
    set +a
fi

: "${GEOTOOL_TEST_POSTGRES_DSN_FILE:?Set a private DSN file for a separate acceptance database}"
: "${GEOTOOL_ENCODER_SOCKET:?Set the real embedding and reranking service socket}"
python="${PYTHON:-python3}"
report_dir="${GEOTOOL_TEST_REPORT_DIR:-$root/.asset-results/integration/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p -- "$report_dir"
cd -- "$root"

"$python" - "$report_dir" <<'PY'
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict
from geological_agent.context_store import private_dsn

test_dsn = private_dsn(os.environ['GEOTOOL_TEST_POSTGRES_DSN_FILE'])
test_info = conninfo_to_dict(test_dsn)
production_file = os.environ.get('GEOTOOL_KNOWLEDGE_DSN_FILE')
if production_file:
    production_info = conninfo_to_dict(private_dsn(production_file))
    identity = lambda value: (
        value.get('hostaddr') or value.get('host') or '',
        value.get('port', '5432'), value.get('dbname', ''),
    )
    if identity(test_info) == identity(production_info):
        raise SystemExit('Refusing to run integration fixtures in the production database.')

socket = Path(os.environ['GEOTOOL_ENCODER_SOCKET'])
if not socket.is_socket():
    raise SystemExit('The real encoder socket is unavailable; integration tests must not be skipped.')
with psycopg.connect(test_dsn, connect_timeout=5) as connection:
    database, user = connection.execute('SELECT current_database(), current_user').fetchone()
    extensions = [row[0] for row in connection.execute('SELECT extname FROM pg_extension')]
    if database in ('postgres', 'template0', 'template1'):
        raise SystemExit('Use a dedicated application acceptance database, not a PostgreSQL system database.')
    if 'vector' not in extensions:
        raise SystemExit('Enable pgvector in the acceptance database before running real RAG tests.')

report = {'database': database, 'user': user, 'pgvector': True,
          'encoder_socket_available': True, 'production_comparison_performed': bool(production_file)}
Path(sys.argv[1], 'environment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
PY

if [[ $# -eq 0 ]]; then
    set -- tests_local
fi
if "$python" -m pytest -q "$@" "--junitxml=$report_dir/full.xml"; then
    "$python" - "$report_dir" <<'PY'
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

folder = Path(sys.argv[1])
suites = list(ET.parse(folder / 'full.xml').getroot().iter('testsuite'))
counts = {key: sum(int(suite.get(key, '0')) for suite in suites)
          for key in ('tests', 'failures', 'errors', 'skipped')}
if not counts['tests'] or any(counts[key] for key in ('failures', 'errors', 'skipped')):
    raise SystemExit('Integration acceptance requires executed tests with no failures, errors, or skips: '
                     + json.dumps(counts))
result = {'passed': True, **counts}
(folder / 'gate.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
PY
else
    exit 1
fi
