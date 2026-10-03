# GeoAgent

A local-first research agent with a LangGraph runtime, native tool calling,
skills, authenticated conversations, human input, and scientific file outputs.
GeoGPT is one possible model backend; GeoAgent is the application, not its weights.

## What is included

- Native OpenAI-compatible tool calls and per-user model profiles.
- Stateful execution, recovery, completion checks, and optional LangSmith tracing.
- Skills and structured scientific tools with input/output contracts.
- Optional PostgreSQL knowledge retrieval and provenance-aware answers.
- Image inspection, deterministic image transformations, raster previews, and
  image analysis using the user's selected vision-capable model.
- Authenticated image previews, comparison, file downloads, and streamed progress.

Unavailable catalog entries remain explicitly unavailable. A catalog entry is not
a claim that its external data, backend, or algorithm has been supplied.

## Development setup

Use Python 3.11 or newer (deployment currently uses Python 3.12).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[web,hitl,professional,observability,test]'
```

On Windows, activate `.venv\Scripts\Activate.ps1` instead. For PostgreSQL-backed
context/checkpoints, also install `requirements-context-postgres.txt` and configure
a private database. Encoder services and document ingestion are separate services;
installing the application alone does not create a knowledge collection.

## Run the research-group UI

Keep state outside the repository. The administrator command prompts for a password.

```bash
python -m geological_agent.team.server --state /private/geoagent-state create-admin --username admin
python -m geological_agent.team.server --state /private/geoagent-state serve --port 50015
```

Execution mode, model endpoint, database, and tracing configuration must be set for
the deployment. Use the model configuration dialog for a user's external model.
The default sandbox execution mode requires host support. The existing research
deployment uses a trusted shared service account; this is NOT OS-level isolation
and must not be exposed to untrusted users.

To access an SSH-only deployment:

```bash
ssh -p 8203 -N -L 127.0.0.1:15015:127.0.0.1:50015 USER@A100_HOST
```

Then open `http://localhost:15015/`.

## Image workflow

Upload an image to a new conversation and request an inspection or transformation.
`GeoImageAnalyze` sends actual image pixels to the selected model, which must support
vision. `GeoImageTransform` uses deterministic operations, not generative editing.
`GeoRasterPreview` produces a display image; it does not replace the original
georeferenced raster or establish scientific interpretation. Test fixtures are
synthetic and are not geological observations.

## Tests

```bash
python -m pytest tests_local/test_image_workflow.py tests_local/test_scientific_source_tools.py tests_local/test_team.py -q
node --check geological_agent/team/web/app.js
node --check geological_agent/team/web/images.js
```

Integration tests can require PostgreSQL, sandbox support, or model services.
Skipped tests are not successful validation of those services.

## Repository and deployment boundaries

This private repository contains application source, tool contracts, skills, and
tests. It intentionally excludes model weights, API keys, password databases,
user documents, knowledge corpora, execution histories, and server state.
Preserve upstream package notices and licenses; this repository does not grant a
new blanket license for third-party algorithms or datasets.

Before releasing a change: test it, transfer a checksum-recorded candidate, check
for active tasks, then switch only the intended service. Keep user state separate
from release directories. Never commit credentials or force-push over others' work.
