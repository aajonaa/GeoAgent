"""Registration and library entries for the OreSage research workflow."""

from .research_literature import WORK_ID, citation_audit, openalex_search
from .research_plan import research_plan
from .research_slides import ppt_master
from .skills import Skill, SkillSummary
from .tools import Tool, ToolDefinition, object_schema


def _text(limit):
    return {"type": "string", "minLength": 1, "maxLength": limit, "pattern": r"\S"}


def _list(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
WORK_IDS = {**_list({"type": "string", "pattern": f"^{WORK_ID}$"}, 4), "uniqueItems": True}
RESULT = {"type": "object"}
PLAN = "GeoResearchPlan"
SEARCH = "GeoOpenAlexSearch"
AUDIT = "GeoResearchCitationAudit"
SLIDES = "GeoPPTMaster"

SKILLS = (
    Skill(
        SkillSummary("planning_with_files", "文件式研究计划",
                     "用工作区 Markdown 文件记录研究目标、阶段状态和证据，支持等待确认后续跑。",
                     "多阶段研究、长程任务、查文献到汇报，或需要暂停等待用户决定。"),
        ("研究目标",),
        "先用 GeoResearchPlan 读取当前计划。没有计划时，写入目标和可核验的阶段。"
        "阶段完成或证据变化后，带上上一版 sha256 更新状态和证据。"
        "提出必须由用户回答的问题前先写入当前状态，恢复后先读取计划，从未完成的阶段继续。"
        "证据填写已取得的文件路径或来源 ID。文献汇报任务依次调用 OpenAlex 检索、引用核对和 PPT Master，"
        "待核对文件及 PPTX 确认后才标记对应阶段为完成。",
        ("计划是工作记录，按用户的最新决定更新。",),
        (PLAN, SEARCH, AUDIT, SLIDES), ("可续跑的 Markdown 研究计划",),
    ),
    Skill(
        SkillSummary("openalex_academic_search", "OpenAlex 文献检索",
                     "从 OpenAlex 检索论文及开放获取和书目信息。",
                     "学术文献检索、综述、DOI 或论文来源查找。"),
        ("公开检索关键词",),
        "用简短的公开学术关键词检索，可用年份约束。保留 OpenAlex Work ID、题名、年份和 DOI。"
        "检索结果是候选书目。打开论文原文或摘要核对相关性和关键结论，记录撤稿及缺失来源。",
        ("只发送公开搜索词。", "书目命中只证明可检索到该来源。"),
        (SEARCH,), ("可追溯的 OpenAlex 文献结果",),
    ),
    Skill(
        SkillSummary("scientific_writing", "科学写作与引用核对",
                     "逐条复核引用元数据，生成可追踪的科研文稿和引用审计。",
                     "科研摘要、文献综述、研究汇报与引用核对。"),
        ("研究主题", "逐条论点和对应的 OpenAlex Work ID"),
        "按问题、证据、结论和局限组织文稿。通过原文或摘要核对论点，区分直接证据和推断。"
        "将论点和实际观察到的 Work ID 交给 GeoResearchCitationAudit 复查，"
        "说明哪些引用缺失或已撤稿，对未查看全文的论点如实标注。交付引用清单与 Markdown 文稿。",
        ("引用工具核对书目信息。原文对论点的支持程度需要阅读原文判断。",),
        (SEARCH, AUDIT), ("Markdown 文稿", "JSON 引用审计及 SHA-256"),
    ),
    Skill(
        SkillSummary("ppt_master", "PPT Master",
                     "用 PPT Master 生成带引用的可编辑 PowerPoint。",
                     "将核对过的科研文稿、文献综述或研究结果制作成 PPTX。"),
        ("引用审计 JSON 路径和 SHA-256", "逐页标题、简洁要点及引用 Work ID"),
        "从引用审计的已核对 Work ID 组织逐页内容。每页只讲一个要点，密集内容拆页，至少一页有出处。"
        "将 citation audit 路径和哈希连同逐页大纲交给 GeoPPTMaster。"
        "工具会自动生成参考文献页。交付工具返回的 PPTX 路径和来源。",
        ("引用必须来自核对通过的 Work ID。", "标题与正文会生成为 PowerPoint 原生文字对象。"),
        (AUDIT, SLIDES), ("可编辑 PPTX",),
    ),
)


def skill_specs():
    return tuple({
        "id": s.summary.id.replace("_", "-"), "name": s.summary.name,
        "description": s.summary.description, "metadata": {"domain": {"primary": "科研工作流"}},
    } for s in SKILLS)


def register_research(registry, skills):
    step = object_schema({"task": _text(180), "status": {"enum": ["pending", "in_progress", "done", "blocked"]}},
                         ("task", "status"))
    plan_schema = object_schema({"objective": _text(300), "steps": _list(step, 12, 1),
                                 "evidence": _list(_text(250), 12),
                                 "expected_sha256": {"anyOf": [SHA, {"type": "null"}]}})
    plan_schema["dependentRequired"] = {"steps": ["objective"], "objective": ["steps"]}
    claim = object_schema({"text": _text(650), "work_ids": {**WORK_IDS, "minItems": 1}}, ("text", "work_ids"))
    slide = object_schema({"title": _text(120), "bullets": _list(_text(210), 5, 1),
                           "work_ids": WORK_IDS}, ("title", "bullets", "work_ids"))
    tools = (
        Tool(ToolDefinition(PLAN, "Read or update the current run’s research plan, progress and evidence.",
                            "At the start of a multi-stage research task, after milestones, and before or after a pause.",
                            plan_schema, RESULT), research_plan),
        Tool(ToolDefinition(SEARCH, "Search OpenAlex for candidate papers and bibliographic metadata.",
                            "Find published sources using public search terms.",
                            object_schema({"query": _text(200), "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                                           "since_year": {"type": "integer", "minimum": 1600, "maximum": 2100}}, ("query",)),
                            RESULT), openalex_search),
        Tool(ToolDefinition(AUDIT, "Verify OpenAlex IDs, flag missing or retracted works, and write a cited Markdown draft and JSON audit.",
                            "Prepare a traceable scientific draft and its reference list.",
                            object_schema({"title": _text(150), "claims": _list(claim, 12, 1)}, ("title", "claims")),
                            RESULT), citation_audit),
        Tool(ToolDefinition(SLIDES, "Generate an editable PPTX and reference slides with the PPT Master engine.",
                            "Export a research outline after citation review.",
                            object_schema({"audit_path": _text(240), "audit_sha256": SHA, "slides": _list(slide, 16, 1)},
                                          ("audit_path", "audit_sha256", "slides")),
                            RESULT), ppt_master, input_paths=("audit_path",)),
    )
    for tool in tools:
        registry.register(tool)
    for skill in SKILLS:
        skills.registry.register(skill)
