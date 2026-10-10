# GeoAgent project management

Use the repository-local backlog/ ledger for non-trivial development work.
This is development tooling, not part of the agent runtime.

- On Windows, invoke .\scripts\backlog.ps1 from this repository.
- Read .\scripts\backlog.ps1 instructions overview before managing tasks.
- Search for an existing task before creating one.
- Keep scope and acceptance criteria concrete; use CLI or Web UI for records.
- Proposed tasks are not authorization to implement, test, deploy, or publish.
- Record coded, verified, released, and deployed states separately.
- Tie evidence to the exact source commit or deployed build. Never reuse an old
  passing report as proof of a new change.
- Historical records explicitly say when they have not been reverified.
- Preserve existing work, files, saved model settings, and original evidence.
- Never place secrets or raw credentials in task records.
- Auto-commit, remote Git operations, and cross-branch scanning are disabled.
- Completing a task does not authorize a commit, push, test, or deployment.
- Do not create tasks for simple explanations or mechanical changes unless requested.

Start the local board with .\scripts\project-board.ps1 at
http://127.0.0.1:6420/. Package version: backlog.md 1.53.0.
Usage, historical baseline, and release template are in backlog/docs/.
Linux: scripts/project-board.sh starts the board with the pinned user-local CLI.
The A100 board is the preferred editable copy after server setup. Before future
synchronization, retrieve and merge server-side record edits; never overwrite them
with an older local snapshot. See the A100 deployment guide in backlog/docs/.
