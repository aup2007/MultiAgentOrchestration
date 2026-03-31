from langgraph.graph import StateGraph, END, START
from state import AgentState
from f1_agent import f1_node
# from soccer_agent import soccer_node
# from baseball_agent import baseball_node

# --- 1. THE ROUTER (The Decision Maker) ---
def supervisor_router(state: AgentState):
    """
    Analyzes the query and routes to the correct sector.
    In production, this could be a small LLM call or a regex check.
    """
    query = state["query"].lower()
    if any(word in query for word in ["f1", "verstappen", "lap", "prix", "race"]):
        return "f1_sector"
    elif any(word in query for word in ["soccer", "goal", "transfer", "market"]):
        return "soccer_sector"
    return "baseball_sector"

# --- 2. THE GRAPH ASSEMBLY ---
builder = StateGraph(AgentState)

# Register the "Worker" Nodes we built
builder.add_node("f1_sector", f1_node)
# builder.add_node("soccer_sector", soccer_node)
# builder.add_node("baseball_sector", baseball_node)

builder.add_conditional_edges(
    START, 
    supervisor_router,
    {
        "f1_sector": "f1_sector",
        "soccer_sector": "f1_sector", # Placeholder until you build soccer
        "baseball_sector": "f1_sector" # Placeholder
    }
)

# After a sector finishes, it goes to the END (or a summarizer)
builder.add_edge("f1_sector", END)

# --- 4. COMPILE & EXECUTE ---
graph = builder.compile()

def run_sports_ai(user_query: str):
    initial_state = {
        "messages": [],
        "query": user_query,
        "user_role": "admin",
        "domain_detected": "",
        "final_response": ""
    }
    
    print(f"\n>>> QUERY: {user_query}")
    for output in graph.stream(initial_state):
        for node_name, state_update in output.items():
            print(f"--- Node '{node_name}' Finished ---")
            if "final_response" in state_update:
                print(f"RESULT: {state_update['final_response']}")

if __name__ == "__main__":
    run_sports_ai("Who had the fastest lap in Monaco 2025?")