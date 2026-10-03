from dataclasses import dataclass
from pathlib import Path
import re
import yaml


@dataclass(frozen=True)
class SkillSummary:
    id: str
    name: str
    description: str
    when_to_use: str


@dataclass(frozen=True)
class Skill:
    summary: SkillSummary
    required_inputs: tuple[str, ...]
    instructions: str
    constraints: tuple[str, ...]
    tool_names: tuple[str, ...]
    expected_outputs: tuple[str, ...]


class SkillRegistry:
    def __init__(self):
        self._skills = {}

    def register(self, skill: Skill):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", skill.summary.id):
            raise ValueError("Invalid skill ID")
        if skill.summary.id in self._skills:
            raise ValueError("Duplicate skill ID")
        if not skill.instructions.strip() or not skill.tool_names:
            raise ValueError("A skill needs instructions and tool references")
        self._skills[skill.summary.id] = skill

    def list(self, query: str | None = None):
        summaries = tuple(skill.summary for skill in self._skills.values())
        if not query:
            return summaries
        words = query.casefold().split()
        matches = tuple(s for s in summaries if any(w in " ".join((s.id, s.name, s.description, s.when_to_use)).casefold() for w in words))
        # Small V0 registry: no semantic scoring and no hidden automatic selection.
        return matches


class SkillLoader:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def load(self, skill_id: str) -> Skill:
        try:
            return self.registry._skills[skill_id]
        except KeyError:
            raise ValueError(f"Unknown skill: {skill_id}; use skill_find") from None

    @classmethod
    def from_directory(cls, root: Path):
        registry = SkillRegistry()
        for path in sorted(root.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            parts = text.split("---", 2)
            if len(parts) != 3 or parts[0].strip():
                raise ValueError(f"Missing skill frontmatter: {path}")
            metadata = yaml.safe_load(parts[1])
            summary = SkillSummary(*(metadata[k] for k in ("id", "name", "description", "when_to_use")))
            registry.register(Skill(summary, tuple(metadata.get("required_inputs", [])), parts[2].strip(),
                                    tuple(metadata.get("constraints", [])), tuple(metadata["tools"]),
                                    tuple(metadata.get("expected_outputs", []))))
        return cls(registry)
