from dataclasses import asdict, replace
from pathlib import Path
from .agent.runtime import AgentRuntime
from .geology.source_registry import register as register_professional, load_source_skills, find_unavailable
from .geology.validation import validate_energy_answer
from .knowledge import NullKnowledgeRetriever
from .memory import NullMemoryStore
from .settings import Settings
from .skills import SkillLoader, SkillRegistry
from .tools import Tool, ToolDefinition, ToolOutput, ToolRegistry, ToolFailure, object_schema, register_file_tools


BASE_TOOLS = ("skill_find", "skill_load", "read_file", "write_file", "execute_python")


def build_registry(*, human_input=False):
    """Shared native registrations for execution and the read-only asset library."""
    registry = ToolRegistry()
    register_file_tools(registry)
    from .imaging import register_image_tools
    register_image_tools(registry)
    from .scientific_imaging import register_scientific_image_tools
    register_scientific_image_tools(registry)
    professional = register_professional(registry)
    skills = load_source_skills(SkillLoader(SkillRegistry()), professional, runtime_registry=registry)
    for summary in skills.registry.list():
        for name in skills.load(summary.id).tool_names:
            registry.get(name)

    def find(args, context):
        return ToolOutput({"skills": [asdict(s) for s in skills.registry.list(args.get("query"))],
                           "unavailable_skills": find_unavailable(skills, args.get("query"))})

    def load(args, context):
        if any(row["id"] == args["skill_id"] for row in skills.unavailable_skills):
            raise ToolFailure("skill_unavailable", "No executable source tools for this skill; ask for missing prerequisites or choose a grounded alternative.",
                              data=skills.source_statuses[args["skill_id"]])
        skill = skills.load(args["skill_id"])
        return ToolOutput({"skill_id": skill.summary.id, "tool_names": list(skill.tool_names),
                           "unavailable_tools": skills.source_statuses.get(skill.summary.id, {}).get("unavailable_tools", [])})

    text = {"type": "string"}
    summary_schema = object_schema({k: text for k in ("id", "name", "description", "when_to_use")}, ["id", "name", "description", "when_to_use"])
    registry.register(Tool(ToolDefinition("skill_find", "Discover concise skill summaries; does not load all instructions or tools.",
        "Find procedures relevant to a geological task; an empty query lists the small local registry.",
        object_schema({"query": {**text, "description": "Optional keywords for lexical relevance ranking, English suffix folding and Chinese bigram matching. No match returns an empty skills array, not unrelated entries. An empty query lists the registry; these entries are not relevance-ranked."}}),
        object_schema({"skills": {"type": "array", "items": summary_schema},
                       "unavailable_skills": {"type": "array", "items": summary_schema}}, ["skills", "unavailable_skills"])), find))
    registry.register(Tool(ToolDefinition("skill_load", "Load one skill's instructions and disclose its registered tools on the NEXT model turn.",
        "A relevant skill has been identified and its procedure or specialized tools are needed.",
        object_schema({"skill_id": {**text, "description": "Exact ID returned by skill_find."}}, ["skill_id"]),
        object_schema({"skill_id": text, "tool_names": {"type": "array", "items": text},
                       "unavailable_tools": {"type": "array", "items": object_schema({"name": text, "reason": text}, ["name", "reason"])}},
                       ["skill_id", "tool_names", "unavailable_tools"])), load))
    base_tools = BASE_TOOLS
    from .web_tools import register_web_tools
    base_tools = (*base_tools, *register_web_tools(registry))
    if human_input:
        from .agent.human_input import register_human_input
        register_human_input(registry)
        base_tools = (*base_tools, "request_user_input")
    return registry, skills, base_tools


def create_agent(model, *, settings=None, memory=None, knowledge=None, trace_factory=None, completion_checks=(), human_input=False, context_store=None):
    settings = settings or Settings()
    registry, skills, base_tools = build_registry(human_input=human_input)
    if knowledge is None and context_store is not None:
        from .rag.store import configured_index
        knowledge = configured_index(context_store.scope.owner_id)
        if knowledge is not None:
            settings = replace(settings, knowledge_enabled=True)
    from .rag.store import citation_issues
    completion_checks = (*completion_checks, citation_issues)
    if context_store is not None:
        from .context_store import register_context_tools
        register_context_tools(registry, context_store)
        base_tools = (*base_tools, "context_search", "context_read")
    return AgentRuntime(model, settings, registry, skills, memory or NullMemoryStore(), knowledge or NullKnowledgeRetriever(), base_tools, trace_factory,
                        completion_checks=(validate_energy_answer, *completion_checks), context_store=context_store)
