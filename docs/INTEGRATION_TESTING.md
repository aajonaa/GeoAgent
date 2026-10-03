# Real integration acceptance

The ten previously skipped cases require a real PostgreSQL acceptance database.
One of those cases also requires the real embedding and cross-encoder service.
These dependencies are already running on A100; supplying both the private test
DSN and the encoder socket enables every integration case. Supplying only the
DSN still skips the real hybrid retrieval case. This does not require changing the live agent's database,
model profile, tools, or scientific algorithms.

## Environment

Use a dedicated acceptance database with pgvector installed and the same
application role used by the runtime. Do not grant the test role superuser or
row-security bypass privileges. The tests check tenant isolation, immutable
evidence, exact context recovery, persisted checkpoints, native protocol
pause/resume, real hybrid retrieval, and cross-encoder ranking.

Store the DSN outside the repository in a private file with mode `0600`, inside
an operator-owned directory. Keep configuration and credentials out of Git.
Create a trusted shell configuration such as:

```bash
export GEOTOOL_TEST_POSTGRES_DSN_FILE=/path/to/private/acceptance-dsn
export GEOTOOL_ENCODER_SOCKET=/path/to/private/encoder.sock
export GEOTOOL_KNOWLEDGE_DSN_FILE=/path/to/private/production-dsn
export PYTHON=/path/to/venv/bin/python
# Configure PYTHONPATH when using a deployed release with external dependencies.
export GEOTOOL_TEST_REPORT_DIR=/path/to/private/acceptance-reports
```

`GEOTOOL_KNOWLEDGE_DSN_FILE` is used by the preflight to reject the production
database as a test target and is mandatory. Do not point it at the acceptance DSN. The test DSN
file must actually select the separate acceptance database.

## Run

```bash
bash scripts/test_a100_integration.sh /path/to/private/integration.env
```

The runner also reads `$HOME/.config/geotoolagent/integration.env` when no
configuration path or `GEOTOOL_INTEGRATION_ENV_FILE` is supplied. This private
operator configuration must provide all three database/socket settings above.
Use this runner, rather than an ad hoc `pytest` command, for a release gate:
missing dependencies are errors, and any skipped case rejects acceptance.

On the current A100 deployment, the operator configuration is:

```bash
bash scripts/test_a100_integration.sh \
  /data/wangjian/geotoolagent-test-environment/integration.env
```

The runner executes the entire suite by default. For a targeted integration
check, append explicit test paths after the configuration path:

```bash
bash scripts/test_a100_integration.sh /path/to/private/integration.env \
  tests_local/test_postgres_context.py \
  tests_local/test_knowledge_rag.py \
  tests_local/test_intent_protocol_recovery.py \
  tests_local/test_protocol_pause.py
```

The runner refuses a passing release gate if there are any failed, errored, or
skipped tests. It writes `environment.json`, `full.xml`, and a successful
`gate.json` into the report directory. Credentials are not included in those
reports. The real encoder is exercised by the RAG fixture, not replaced by a
fake vector or fake reranking score.

## Data boundaries

Fixtures use explicitly labeled synthetic data and unique test owners. They
are not scientific source material and must not be imported into the live
knowledge library. Knowledge fixtures remove their own documents after the
test. Immutable context/checkpoint evidence remains in the separate acceptance
database for diagnosis. The runner does not delete databases, restart live
services, change GPU assignments, or call an external paid chat model.
