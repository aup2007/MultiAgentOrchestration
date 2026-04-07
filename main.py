from langgraph.graph import StateGraph, END, START
from state import AgentState
from f1_agent import f1_sector_graph
from baseball_agent import baseball_sector_graph
from football_agent import football_sector_graph
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage
from langchain_groq import ChatGroq
import json
import logging
from tenacity import retry, wait_exponential, stop_after_attempt


logger = logging.getLogger(__name__)

# Use a faster, lighter model for routing (lower latency for classification)
router_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_tokens=20, streaming=True)
# Note: llama-prompt-guard is a classification model and does NOT support streaming
safety_checker = ChatGroq(model="meta-llama/llama-prompt-guard-2-22m", temperature=0)

# Define valid sectors
VALID_SECTORS = ["f1_sector", "football_sector", "baseball_sector"]
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
def supervisor_router(state: AgentState) -> dict:
    """
    LLM-powered intent classifier that routes queries to the correct sector.
    Uses structured output parsing with fallback error handling.
    """
    router_system_prompt = """You are a sports query router with expertise in intent classification.
Your job is to route incoming user queries to the most appropriate sports sector.

AVAILABLE SECTORS:
- f1_sector: Formula 1, F1, drivers, teams, telemetry, races, lap times, pit stops, qualifying
- football_sector: Soccer, football, goals, transfers, leagues, clubs, strikers, defenders, tactical
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
        return {
            "domain_detected": sector
            # Don't add routing message to messages - prevents concatenation with final response
        }

    except Exception as e:
        logger.error(f"Router LLM call failed: {e}. Using default sector: {DEFAULT_SECTOR}")
        return {"domain_detected": DEFAULT_SECTOR}
    

def global_input_guard_node(state: AgentState) -> dict:
    print("--- GLOBAL INPUT GUARDRAIL ---")
    query = state.get("query", "")
    
    # Llama Guard expects a specific format, but standard prompting works well via API
    res = safety_checker.invoke([HumanMessage(content=query)])
    
    if "unsafe" in res.content.lower():
        print(f">>> INPUT BLOCKED by Llama Guard: {res.content}")
        return {
            "is_safe": False, 
            "guardrail_reason": res.content,
            "final_response": "I cannot process this request due to safety policies."
        }
    
    return {"is_safe": True, "guardrail_reason": ""}

# --- Global Output Guardrail Node ---
def global_output_guard_node(state: AgentState) -> dict:
    print("--- GLOBAL OUTPUT GUARDRAIL ---")
    response = state.get("final_response", "")
    
    # Example logic: Ensure PII or toxic content didn't leak
    if "Social Security" in response or "credit card" in response.lower():
        return {"final_response": "I cannot provide that information due to safety policies."}
    return {}

# --- Updating the Main Graph Assembly ---
# 1. Add the new nodes


# --- 2. THE GRAPH ASSEMBLY ---
builder = StateGraph(AgentState)

builder.add_node("input_guard", global_input_guard_node)
builder.add_node("output_guard", global_output_guard_node)

builder.add_node("supervisor_router", supervisor_router)
# Register sector nodes
builder.add_node("f1_sector", f1_sector_graph)
builder.add_node("football_sector", football_sector_graph)  # Uncomment when available
builder.add_node("baseball_sector", baseball_sector_graph)  # Uncomment when available

builder.add_edge(START, "input_guard")

builder.add_conditional_edges(
    "input_guard",
    lambda state: "supervisor_router" if state.get("is_safe", True) else "blocked",
    {
        "supervisor_router": "supervisor_router",
        "blocked": "output_guard"
    }
)



# Conditional routing from START: supervisor_router decides which sector to route to
builder.add_conditional_edges(
    "supervisor_router",
    lambda state: state["domain_detected"],
    {
        "f1_sector": "f1_sector",
        "football_sector": "football_sector", 
        "baseball_sector": "baseball_sector", 
    }
)

# After sector processing, route to END
builder.add_edge("f1_sector", "output_guard")
builder.add_edge("football_sector", "output_guard")  # Uncomment when available
builder.add_edge("baseball_sector", "output_guard")  # Uncomment when available
builder.add_edge("output_guard", END)
# --- 4. COMPILE & EXECUTE ---
memory = MemorySaver()
graph = builder.compile(checkpointer= memory)
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
        "final_response": "",
        "is_safe": True,
        "guardrail_reason": ""
    }
    
    print(f"\n>>> QUERY: {user_query}")
    for output in graph.stream(initial_state):
        for node_name, state_update in output.items():
            print(f"--- Node '{node_name}' Finished ---")
            if "final_response" in state_update:
                print(f"RESULT: {state_update['final_response']}")

if __name__ == "__main__":
    import sys

    config = {"configurable": {"thread_id": "cli_test_1"}}

    # Accept query from command-line argument or stdin
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Enter your sports query: ")

    initial_state = {
        "messages": [],
        "query": query,
        "user_role": "admin",
        "domain_detected": "",
        "final_response": "",
        "is_safe": True,
        "guardrail_reason": ""
    }

    print(f"\n>>> QUERY: {query}")
    
    # 2. Run the graph until it finishes OR hits a breakpoint
    for event in graph.stream(initial_state, config):
        pass # The nodes have their own print statements
    
    MAX_RETRIES = 2
    retry_count = 0

    while retry_count <= MAX_RETRIES:
    # 3. Check the graph's current state to see if it is paused
        current_state = graph.get_state(config)
    
    
    # .next contains the name of the node it is waiting to execute. 
    # If it's not empty, it means we hit our breakpoint!
        if not current_state.next:
            print("\n==================================================")
            print("✅ FINAL RESULT:")
            # Dynamically extract from whichever sector handled it
            result = current_state.values.get('final_response', "No response generated.")
            print(result)
            print("==================================================")
            break
            
        print(f"\n🚨 GRAPH PAUSED (Attempt {retry_count + 1} of {MAX_RETRIES + 1}) 🚨")
        print("The agent is preparing to execute an API call.")
        
        user_input = input("Do you approve the execution? (y/n): ")
        
        if user_input.lower() == 'y':
            print("\n▶️ RESUMING GRAPH...")
            retry_count += 1
            # Resume from the pause
            for event in graph.stream(None, config):
                pass
        else:
            print("\n❌ Execution cancelled by human.")
            break
            
    if retry_count > MAX_RETRIES:
        print("\n⚠️ SYSTEM HALTED: Maximum retries reached. The AI cannot resolve the issue.")