from langgraph.graph import StateGraph, END, START
from state import AgentState
from f1_agent import f1_sector_graph
# from soccer_agent import soccer_node
# from baseball_agent import baseball_node
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq


llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.3)


# --- 1. THE ROUTER (The Decision Maker) ---
def supervisor_router(state: AgentState):
    """
    Analyzes the query and routes to the correct sector.
    In production, this could be a small LLM call or a regex check.
    """
    router_prompt = f"""
    You are a sports query router. Categorize the user's query into one of these three sectors:
    1. 'f1_sector' (Formula 1, drivers, teams, telemetry, races)
    2. 'soccer_sector' (Football, goals, transfers, leagues)
    3. 'baseball_sector' (MLB, home runs, innings)

    If the query is ambiguous, default to 'f1_sector'.
    
    User Query: "{state['query']}"

    Respond with ONLY the string of the sector name. No preamble or explanation.
    """

    response = llm.invoke([HumanMessage(content=router_prompt)]).content.strip().lower()
    print(response)
    # Validation: Ensure the LLM didn't hallucinate a sector name
    valid_sectors = ["f1_sector", "soccer_sector", "baseball_sector"]
    
    for sector in valid_sectors:
        if sector in response:
            print(f">>> ROUTING TO: {sector}")
            return sector

    # query = state["query"].lower()
    # if any(word in query for word in ["f1", "lap", "prix", "race"]):
    #     return "f1_sector"
    



    # elif any(word in query for word in ["soccer", "goal", "transfer", "market"]):
    #     return "soccer_sector"
    # return "baseball_sector"

# --- 2. THE GRAPH ASSEMBLY ---
builder = StateGraph(AgentState)



builder.add_node("f1_sector", f1_sector_graph)

# Register the "Worker" Nodes we built
# builder.add_node("f1_sector", f1_node)
# builder.add_node("soccer_sector", soccer_node)
# builder.add_node("baseball_sector", baseball_node)

builder.add_conditional_edges(
    START, 
    supervisor_router,
    {
        "f1_sector": "f1_sector",
        # "soccer_sector": "f1_sector", # Placeholder until you build soccer
        # "baseball_sector": "f1_sector", # Placeholder
        END:END
    }
)

# After a sector finishes, it goes to the END (or a summarizer)
builder.add_edge("f1_sector", END)
# --- 4. COMPILE & EXECUTE ---
graph = builder.compile()
try:
    # Get the visual representation of the graph as PNG bytes
    image_bytes = graph.get_graph(xray=True).draw_mermaid_png()
    
    # Save the bytes to a file in your project directory
    with open("twg_architecture.png", "wb") as f:
        f.write(image_bytes)
        
    print("✅ Successfully generated twg_architecture.png")
except Exception as e:
    print(f"⚠️ Could not draw graph (You may need to `pip install grandalf` or check dependencies): {e}")

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
    run_sports_ai("Which team was lewis hamilton part of in 2022?")