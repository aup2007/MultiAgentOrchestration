from graphviz import Digraph

def build_agentic_architecture():
    dot = Digraph("LangGraph_Agent_Architecture", format="png")
    dot.attr(rankdir="TB", splines="ortho", nodesep="0.5", ranksep="0.8")
    dot.attr(label="Supervisor + Subgraph Agent Architecture", labelloc="t", fontsize="20")

    dot.attr("node", shape="box", style="rounded,filled", fillcolor="#F8F5FF", color="#7C3AED", fontname="Helvetica")
    dot.attr("edge", color="#444444", arrowsize="0.8")

    dot.node("start", "START", shape="oval", fillcolor="#EDE9FE")
    dot.node("end", "END", shape="oval", fillcolor="#EDE9FE")

    with dot.subgraph(name="cluster_shared") as s:
        s.attr(label="Shared / Supervisor State", style="rounded,filled", color="#C4B5FD", fillcolor="#FAF5FF")
        s.node(
            "shared_state",
            """AgentState
- messages
- query
- user_role
- domain_detected
- final_response""",
            shape="note",
            fillcolor="#FFFFFF"
        )

    with dot.subgraph(name="cluster_supervisor") as sup:
        sup.attr(label="Supervisor Layer", style="rounded,filled", color="#A78BFA", fillcolor="#F5F3FF")
        sup.node("input_guard", "Input / Preprocess")
        sup.node("supervisor", "Supervisor Router")
        sup.node("route_check", "Route by domain_detected?", shape="diamond", fillcolor="#FEF3C7", color="#D97706")

    with dot.subgraph(name="cluster_f1") as f1:
        f1.attr(label="F1 Subgraph", style="rounded,filled", color="#86EFAC", fillcolor="#F0FDF4")
        f1.node(
            "f1_state",
            """F1SubState
- query
- year
- location
- f1_response""",
            shape="note",
            fillcolor="#FFFFFF",
            color="#16A34A"
        )
        f1.node("f1_extract", "Extract Params\n(year, location)")
        f1.node("f1_validate", "Validate Params", shape="diamond", fillcolor="#FEF3C7", color="#D97706")
        f1.node("f1_sync", "Sync / Normalize")
        f1.node("f1_sql", "SQL Query")
        f1.node("f1_format", "Format F1 Result")
        f1.node("f1_return", "Return to Supervisor")

    with dot.subgraph(name="cluster_other") as other:
        other.attr(label="Other Domain Agent(s)", style="rounded,dashed", color="#CBD5E1", fillcolor="#F8FAFC")
        other.node("other_agent", "Other Agent / Subgraph", fillcolor="#FFFFFF")

    dot.node("finalize", "Finalize Response")

    dot.edge("start", "input_guard")
    dot.edge("input_guard", "supervisor")
    dot.edge("supervisor", "route_check")

    dot.edge("shared_state", "supervisor", style="dashed", label="read/write state")
    dot.edge("shared_state", "f1_extract", style="dashed", label="query")
    dot.edge("f1_return", "shared_state", style="dashed", label="update final_response")

    dot.edge("route_check", "f1_extract", label="F1")
    dot.edge("route_check", "other_agent", label="Other")
    dot.edge("other_agent", "finalize")

    dot.edge("f1_state", "f1_extract", style="dashed")
    dot.edge("f1_extract", "f1_validate")
    dot.edge("f1_validate", "f1_sync", label="valid")
    dot.edge("f1_validate", "f1_extract", label="missing / retry")
    dot.edge("f1_sync", "f1_sql")
    dot.edge("f1_sql", "f1_format")
    dot.edge("f1_format", "f1_return")
    dot.edge("f1_return", "finalize")

    dot.edge("finalize", "end")

    return dot

if __name__ == "__main__":
    diagram = build_agentic_architecture()
    diagram.render("diagrams/agent_architecture", cleanup=True)
    print("Saved diagram to diagrams/agent_architecture.png")