from langgraph.graph import END, START, StateGraph
from .state import AgentState


def build_graph(model_turn, execute_tools, finalize, *, human_input=None, checkpointer=None, retrieve_knowledge=None):
    graph = StateGraph(AgentState)
    graph.add_node("model", model_turn)
    graph.add_node("tools", execute_tools)
    graph.add_node("finalize", finalize)
    if human_input is not None:
        graph.add_node("human", human_input)
        def after_human(state):
            if state["metadata"].get("runtime_control_resume"):
                return "model"
            return "knowledge" if retrieve_knowledge is not None else "model"
        graph.add_conditional_edges("human", after_human,
            {"model": "model", **({"knowledge": "knowledge"} if retrieve_knowledge is not None else {})})
    if retrieve_knowledge is not None:
        graph.add_node("knowledge", retrieve_knowledge)
        graph.add_edge("knowledge", "model")
    graph.add_edge(START, "knowledge" if retrieve_knowledge is not None else "model")

    def route(state):
        if human_input is not None and state["status"] == "needs_input" and state["metadata"].get("pending_input"):
            return "human"
        if state["status"] != "running":
            return "end"
        if state["pending_tool_calls"]:
            return "tools"
        return "finalize" if state["answer"] else "model"

    routes = {"end": END, "tools": "tools", "finalize": "finalize", "model": "model"}
    if human_input is not None:
        routes["human"] = "human"
    graph.add_conditional_edges("model", route, routes)
    def after_action(state):
        if human_input is not None and state["status"] == "needs_input" and state["metadata"].get("pending_input"):
            return "human"
        return "model" if state["status"] == "running" else "end"
    action_routes = {"model": "model", "end": END, **({"human": "human"} if human_input is not None else {})}
    graph.add_conditional_edges("tools", after_action, action_routes)
    graph.add_conditional_edges("finalize", after_action, action_routes)
    return graph.compile(checkpointer=checkpointer)
