# Unified skill catalog

All 34 skills are registered in catalog/registry.json and load their instructions from catalog/skills/*/SKILL.md. There is no separate runtime-bundled skill discovery pass. Existing public IDs remain stable through the existing alias mapping. The library rejects undisclosed registered skills rather than silently appending a Runtime category.

Skill tool_references can reference professional catalog IDs or already registered native workspace tools. Basic file/image dependencies are not duplicated as professional algorithms. Totals remain 116 professional tools plus 12 base/runtime tools with HITL enabled, and 34 skills.

Geological table analysis and image workflow now use the same catalog as every other skill. Their native dependency lists, scientific caveats and existing public IDs are preserved. The former seven local copies were consolidated; the canonical documents are packaged through the existing catalog package-data configuration. No model invocation, execution permission, algorithm, user file or credential setting changes. Registration is not scientific or external platform certification.
