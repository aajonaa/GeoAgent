from dataclasses import asdict, replace
import os
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


def build_registry(*, human_input=False, mcp_servers=None, skill_encoder=None, subagents=None, todo_tracking=None, codeact=None):
    """Shared native registrations for execution and the read-only asset library."""
    registry = ToolRegistry()
    register_file_tools(registry)
    from .imaging import register_image_tools
    register_image_tools(registry)
    from .scientific_imaging import register_scientific_image_tools
    register_scientific_image_tools(registry)
    professional = register_professional(registry)
    from .skill_resources import register_skill_resources
    register_skill_resources(registry)
    from .general_artifacts import register_general_tools
    register_general_tools(registry)
    skill_registry = SkillRegistry()
    if skill_encoder is not None:
        from .skill_search import SkillHybridIndex
        skill_registry.set_hybrid_index(SkillHybridIndex(encoder=skill_encoder))
    skills = load_source_skills(SkillLoader(skill_registry), professional, runtime_registry=registry)
    from .research_skills import register_research
    register_research(registry, skills)
    for summary in skills.registry.list():
        for name in skills.load(summary.id).tool_names:
            registry.require_registered(name)

    def find(args, context):
        limit = args.get("limit")
        return ToolOutput({"skills": [asdict(s) for s in skills.registry.list(args.get("query"), limit=limit)],
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
    registry.register(Tool(ToolDefinition("skill_find", "Discover concise skill summaries via hybrid semantic + lexical BM25 ranking; does not load all instructions or tools.",
        "Find procedures relevant to a geological task; an empty query lists the small local registry.",
        object_schema({"query": {**text, "description": "Optional keywords or natural-language query for hybrid semantic + BM25 lexical ranking with English suffix folding, Chinese bigrams, and bilingual geoscience concept matching. No match returns an empty skills array, not unrelated entries. An empty query lists the registry; these entries are not relevance-ranked."},
                       "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Optional maximum number of top-ranked skills to return."}}),
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
    from .mcp_client import register_mcp_tools
    mcp_tool_names, mcp_manager = register_mcp_tools(registry, configs=mcp_servers)
    if mcp_tool_names:
        base_tools = (*base_tools, *mcp_tool_names)
        registry.mcp_manager = mcp_manager
    if human_input:
        from .agent.human_input import register_human_input
        register_human_input(registry)
        base_tools = (*base_tools, "request_user_input")
    enable_todo = (todo_tracking is True or
                   (todo_tracking is None and os.environ.get("GEOTOOL_TODO_RECITATION", "1") != "0"))
    if enable_todo:
        from .agent.todo import register_todo_tool
        base_tools = (*base_tools, *register_todo_tool(registry))
    enable_subagents = (subagents is True or
                        (subagents is None and os.environ.get("GEOTOOL_SUBAGENTS", "1") != "0"))
    if enable_subagents:
        from .agent.subagent import register_subagent_tools
        base_tools = (*base_tools, *register_subagent_tools(registry))
    enable_codeact = (codeact is True or
                      (codeact is None and os.environ.get("GEOTOOL_CODEACT", "1") != "0"))
    if enable_codeact:
        from .agent.codeact import register_codeact_tool
        base_tools = (*base_tools, *register_codeact_tool(registry))
    return registry, skills, base_tools


def _build_read_only_registry(*, mcp_servers=None):
    """Fast path for Ask mode: register only read-only tools, skipping 457+ catalog tools."""
    full = ToolRegistry()
    register_file_tools(full)
    from .web_tools import register_web_tools
    web_tools = register_web_tools(full)
    allowed = ["read_file", *web_tools]
    from .mcp_client import register_mcp_tools
    mcp_tool_names, mcp_manager = register_mcp_tools(full, configs=mcp_servers)
    if mcp_manager is not None:
        for name in mcp_tool_names:
            if name in mcp_manager.read_only_tools:
                allowed.append(name)
    registry = ToolRegistry()
    for name in allowed:
        registry.register(full.get(name), validate_schema=False)
    if mcp_manager is not None:
        registry.mcp_manager = mcp_manager
    return registry, SkillLoader(SkillRegistry()), tuple(allowed)


def create_agent(model, *, settings=None, memory=None, knowledge=None, trace_factory=None, completion_checks=(), human_input=False, context_store=None, read_only=False, mcp_servers=None, skill_encoder=None, subagents=None, todo_tracking=None, codeact=None):
    settings = settings or Settings()
    if read_only:
        registry, skills, base_tools = _build_read_only_registry(mcp_servers=mcp_servers)
    else:
        registry, skills, base_tools = build_registry(
            human_input=human_input,
            mcp_servers=mcp_servers,
            skill_encoder=skill_encoder,
            subagents=subagents,
            todo_tracking=todo_tracking,
            codeact=codeact,
        )
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
    if not read_only:
        completion_checks = (validate_energy_answer, *completion_checks)
    return AgentRuntime(model, settings, registry, skills, memory or NullMemoryStore(), knowledge or NullKnowledgeRetriever(), base_tools, trace_factory,
                        completion_checks=completion_checks, context_store=context_store, read_only=read_only)
