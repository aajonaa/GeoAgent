# MemoraX workbench check, 2026-10-29

The current simplified workbench is https://text-preview.memorax.net/.
The developer workbench is https://text-preview.memorax.net/dev.
Both returned HTTP 200 during this check. The developer page's published
DEFAULTS.baseUrl still names http://preview-text.memorax.net, distinct from
the workbench hostname. OreSage continues using the existing secure API origin
https://preview-text.memorax.net; no downgrade to HTTP or speculative hostname
replacement was made.

Existing account settings, conversation memory bindings and server credentials
are preserved by the release. This check read only public workbench pages and
did not upload conversations, create memories or send the saved API key to the
new workbench. A changed UI is not evidence of a changed API request/response
contract. The captured public pages and hashes are kept with the local release
evidence, outside Git.
