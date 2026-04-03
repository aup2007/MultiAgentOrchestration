from langgraph.graph import StateGraph, END, START
from state import AgentState
from f1_agent import f1_sector_graph
# from soccer_agent import soccer_node
# from baseball_agent import baseball_node
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
import json
import logging
from tenacity import retry, wait_exponential, stop_after_attempt


logger = logging.getLogger(__name__)

# Use a faster, lighter model for routing (lower latency for classification)
router_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0,max_tokens=20)

# Define valid sectors
VALID_SECTORS = ["f1_sector", "soccer_sector", "baseball_sector"]
DEFAULT_SECTOR = "f1_sector"  # Fallback sector


def parse_router_response(response_text: str) -> str:
    """
    Parse the LLM response to extract the sector name.
    Handles both plain text and JSON formats.
    Returns DEFAULT_SECTOR if parsing fails.
    """
    response_text = response_text.strip()

    # Try JSON parsing first
    try:
        parsed = json.loads(response_text)
        sector = parsed.get("sector", "").lower()
        if sector in VALID_SECTORS:
            return sector
    except (json.JSONDecodeError, AttributeError):
        pass

    # Try direct matching (lowercase)
    response_lower = response_text.lower()
    for sector in VALID_SECTORS:
        if response_lower == sector or response_lower.strip() == sector:
            return sector

    # Log fallback and return default
    logger.warning(f"Failed to parse router response: {response_text}. Using fallback: {DEFAULT_SECTOR}")
    return DEFAULT_SECTOR


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10), 
    stop=stop_after_attempt(3),
    reraise=True
)
def safe_route_invoke(prompt_content: str):
    return router_llm.invoke([HumanMessage(content=prompt_content)]).content

# --- 1. THE ROUTER (The Decision Maker) ---
def supervisor_router(state: AgentState) -> str:
    """
    LLM-powered intent classifier that routes queries to the correct sector.
    Uses structured output parsing with fallback error handling.
    """
    router_system_prompt = """You are a sports query router with expertise in intent classification.
Your job is to route incoming user queries to the most appropriate sports sector.

AVAILABLE SECTORS:
- f1_sector: Formula 1, F1, drivers, teams, telemetry, races, lap times, pit stops, qualifying
- soccer_sector: Soccer, football, goals, transfers, leagues, clubs, strikers, defenders, tactical
- baseball_sector: Baseball, MLB, home runs, innings, pitchers, teams, World Series

ROUTING RULES:
1. If the query clearly matches one sector, return that sector name.
2. If the query is ambiguous or off-topic, default to f1_sector.
3. CRITICAL: Respond with ONLY the sector name (e.g., "f1_sector"). No explanation, no preamble.

Output format: plain text sector name or JSON: {"sector": "sector_name"}"""

    user_query = state.get("query", "")
    router_user_prompt = f'Route this query to the appropriate sector: "{user_query}"'

    try:
        # Make fast LLM call with strict parameters
        response = safe_route_invoke(router_system_prompt + "\n\n" + router_user_prompt)
        # response = router_llm.invoke([
        #     HumanMessage(content=router_system_prompt + "\n\n" + router_user_prompt)
        # ]).content

        # Parse and validate response
        sector = parse_router_response(response)
        logger.info(f"Query: '{user_query}' → Routed to: {sector}")
        print(f">>> ROUTING TO: {sector}")
        return sector

    except Exception as e:
        logger.error(f"Router LLM call failed: {e}. Using default sector: {DEFAULT_SECTOR}")
        return DEFAULT_SECTOR

# --- 2. THE GRAPH ASSEMBLY ---
builder = StateGraph(AgentState)

# Register sector nodes
builder.add_node("f1_sector", f1_sector_graph)
# builder.add_node("soccer_sector", soccer_sector_graph)  # Uncomment when available
# builder.add_node("baseball_sector", baseball_sector_graph)  # Uncomment when available

# Conditional routing from START: supervisor_router decides which sector to route to
builder.add_conditional_edges(
    START,
    supervisor_router,
    {
        "f1_sector": "f1_sector",
        "soccer_sector": "f1_sector",  # TODO: Replace with soccer_sector when ready
        "baseball_sector": "f1_sector",  # TODO: Replace with baseball_sector when ready
    }
)

# After sector processing, route to END
builder.add_edge("f1_sector", END)
# builder.add_edge("soccer_sector", END)  # Uncomment when available
# builder.add_edge("baseball_sector", END)  # Uncomment when available
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