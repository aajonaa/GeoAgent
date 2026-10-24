# Earth tools 220: source and release record

## Scope

- Frozen tool candidate: 220 professional tools and 47 canonical Skills.
- Earth-science collection coverage: 84 original operations and 2 explicitly identified replacements; 15 of the 101 source projects remain outside this union.
- Unrelated MemoraX, memory, account settings, conversations and knowledge data are not included in the source change.
- This is not a claim that every operation of each upstream project has been ported, or that the receiving AI Lab has accepted the delivery.

## Evidence

- Historical independent candidate union: 1,034 unique actual passing cases. This combines preserved positive execution records and repaired-node reruns; it is not a fresh 1,034-case test of the release.
- Fresh merged-release tests: 285 actual call-phase passes, including native ToolExecutor execution of all 220 professional catalog entries. Zero failures and skips.
- Fixtures are explicitly synthetic. Mocked USGS transport and protocol controls do not establish availability of third-party live services.
- The first release environment had 33 failures caused by old dependency paths overriding reviewed releases. Its original evidence is retained. The clean retry uses the reviewed dependency versions without changing pins, algorithms or assertions.
- Published scientific source bytes are verified against Git index blobs as well as working-copy SHA-256. Original newline styles are retained.
- See earth-tools220-source-manifest.json and earth-tools220-publication-check.json.

## Runtime and delivery constraints

- Private CPU environments and reviewed fixed-entry workers remain required on the A100 host. Source publication is not a portable binary/runtime distribution.
- Existing PostgreSQL driver components are reused separately from the old mixed dependency layers.
- Application deployment does not restart GeoGPT, Qwen retrieval, AcaAgent or the project board, and does not allocate any GPU.
- Original upstream sources, copyright notices and licenses remain attached. The existing HPGL commercial-distribution wording review remains pending; no lab or commercial-distribution approval is asserted.
- Model workflow validation and receiving-lab acceptance remain separate from source, native-tool and UI checks.

## Delivery state at source commit

- Implementation and fresh native-tool tests: passed.
- Production switch: pending, to be recorded in earth-tools220-deployment.json.
- Browser acceptance: blocked by a saved origin permission for http://127.0.0.1:18015/; not reported as passed.
- GitHub publication: pending the explicit push step.

