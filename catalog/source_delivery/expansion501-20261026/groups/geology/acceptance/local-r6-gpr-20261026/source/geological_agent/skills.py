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
        # Match complete words, excluding single-letter symbols and common
        # connectors. Substring matching let "I", "u" and "v" match almost
        # every description. Keep a simple, observable lexical ranking.
        terms = _search_terms(query)
        scored = []
        for summary in summaries:
            text = " ".join((summary.id, summary.name, summary.description, summary.when_to_use)).casefold()
            tokens = _search_terms(text)
            # Chinese has no word separators: a query bigram matches when it
            # occurs anywhere in the summary text.
            score = sum(term in tokens or (_CJK.match(term) is not None and term in text)
                        for term in terms)
            if score:
                scored.append((score, summary))
        return tuple(s for _, s in sorted(scored, key=lambda item: -item[0]))


_CJK = re.compile(r"[\u3400-\u9fff]")
_IGNORED = {"the", "and", "or", "for", "with", "from", "to", "of", "in", "on"}
# Light English suffix folding so plural and inflected forms meet their stems
# (statistic/statistics, interpolate/interpolated/interpolation). Ordered so the
# longest applicable suffix is removed; a stem keeps at least four letters.
_SUFFIXES = ("ings", "ing", "ions", "ion", "ies", "es", "ed", "s", "e")


def _stem(word):
    for suffix in _SUFFIXES:
        if not word.endswith(suffix) or len(word) - len(suffix) < 4:
            continue
        if suffix == "s" and word.endswith(("ss", "is", "us")):
            continue
        base = word[:-len(suffix)]
        if suffix == "ies":
            return base + "y"
        if suffix in ("ing", "ings", "ed") and len(base) >= 4 and base[-1] == base[-2] and base[-1] not in "lsz":
            return base[:-1]
        return base
    return word


def _search_terms(text):
    terms = set()
    for run in re.findall(r"[\u3400-\u9fff]+|[^\W\u3400-\u9fff]+", text.casefold()):
        if _CJK.match(run):
            # Single characters are as unspecific as single Latin letters.
            terms.update(run[i:i + 2] for i in range(len(run) - 1))
        elif len(run) > 1 and run not in _IGNORED:
            terms.add(_stem(run))
    return terms


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
