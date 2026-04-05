import os
import json
import logging
import re
import requests
from typing import Any, TypedDict
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

# === 1. STATE DEFINITION ===
class FootballSubState(TypedDict):
    messages: list  
    query: str
    entities: dict[str, Any]
    final_response: str
    feedback: str         # Critic's feedback for self-correction
    revision_count: int   # Prevents infinite loops

load_dotenv()

# === 2. LLM SETUP ===
extract_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_tokens=150)
api_llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, max_tokens=1000)

def parse_json_safely(text: str) -> dict:
    """Helper to extract and parse JSON even if the LLM adds text."""
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"JSON Parse Error: {e}")
        return {"league": None, "team": None, "year": None, "is_live": False}

# === 3. DIRECT API TOOLS (Mocked for testing) ===
def get_league_standings(league_name: str, season: int) -> str:
    """
    Fetches the current Premier League standings, points, wins, and goal differential.
    """
    print(f"\n>>> [API CALL] Fetching {season} PL standings from football-data.org...")
    
    api_key = os.getenv("FOOTBALL_DATA_API_KEY")
    print(f">>> DEBUG: API Key Loaded: {'YES' if api_key else 'NO (Check .env)'}")
    headers = {"X-Auth-Token": api_key}
    
    # Using 'PL' for Premier League
    url = f"https://api.football-data.org/v4/competitions/PL/standings?season={season}"
    
    try:
        response = requests.get(url, headers=headers)
        print(f">>> DEBUG: API Response Code: {response.status_code}")
        if response.status_code != 200:
            return json.dumps({"error": f"API returned {response.status_code}: {response.text}"})
            
        data = response.json()
        
        # football-data.org returns home/away splits, we just want the TOTAL table (index 0)
        table = data['standings'][0]['table']
        
        # We parse the massive JSON into a tiny, token-friendly list
        condensed_standings = []
        for team in table:
            condensed_standings.append({
                "rank": team['position'],
                "team": team['team']['shortName'],
                "points": team['points'],
                "gd": team['goalDifference'],
                "played": team['playedGames']
            })
            
        return json.dumps(condensed_standings)
        
    except Exception as e:
        return json.dumps({"error": f"Failed to connect to API: {str(e)}"})


@tool
def get_live_match_data(team_name: str) -> str:
    """
    Fetches live, in-game match statistics and current scores for Chelsea.
    Use this ONLY if the user asks about a game happening "right now" or "today".
    """
    print(f"\n>>> [API CALL] Fetching live match data for Chelsea (ID: 61)...")
    
    api_key = os.getenv("FOOTBALL_DATA_API_KEY")
    headers = {"X-Auth-Token": api_key}
    
    # 61 is Chelsea's exact ID. We filter for matches happening RIGHT NOW.
    url = "https://api.football-data.org/v4/teams/61/matches?status=IN_PLAY"
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return json.dumps({"error": f"API returned {response.status_code}: {response.text}"})
            
        data = response.json()
        matches = data.get("matches", [])
        
        if not matches:
            return json.dumps({"message": "Chelsea is not currently playing a live match. They are off the pitch."})
            
        # If they are playing, grab the current match
        match = matches[0]
        score = match['score']['fullTime'] 
        
        return json.dumps({
            "status": match['status'],
            "home_team": match['homeTeam']['name'],
            "away_team": match['awayTeam']['name'],
            "score": f"{score.get('home', 0)} - {score.get('away', 0)}"
        })
        
    except Exception as e:
        return json.dumps({"error": f"Failed to connect to API: {str(e)}"})
# === 4. AGENT EXECUTOR SETUP ===
football_tools = [get_league_standings, get_live_match_data]

system_prompt = """You are the Official TWG Global Chelsea FC Analyst. 
CRITICAL RULE: You are ONLY allowed to answer questions about Chelsea FC. 
If the user asks about ANY other team (like Arsenal, Spurs, etc.) without relating it to a Chelsea fixture, you must politely refuse, do not call any tools, and state that your mandate is strictly limited to Chelsea FC.

Rules:
1. Read the user's question carefully.
2. Choose the correct API tool.
3. Base your final answer strictly on the API JSON response.
4. Do not invent scores or standings."""

# create_react_agent completely replaces the old AgentExecutor
football_agent_executor = create_react_agent(
    model=api_llm, 
    tools=football_tools,
    prompt=system_prompt
)

# football_api_agent = create_tool_calling_agent(api_llm, football_tools, prompt)
# football_agent_executor = AgentExecutor(agent=football_api_agent, tools=football_tools, verbose=False)

# === 5. NODES ===
def football_extract_node(state: FootballSubState) -> dict:
    print("\n--- NODE 1: Football Entity Extraction ---")
    query = state.get("query", "")
    
    extraction_prompt = f"""
    Analyze this Football (Soccer) query: "{query}"
    Extract these entities:
    - league (e.g., "Premier League")
    - team (e.g., "Arsenal")
    - year (Integer, default to 2024 if current/now is implied)
    - is_live (Boolean: true if asking for a live score right now)

    Respond with ONLY a valid JSON object. No markdown, no notes.
    """
    response = extract_llm.invoke([HumanMessage(content=extraction_prompt)]).content
    entities = parse_json_safely(response)
    # Initialize revision count to 0 for a fresh run
    return {"entities": entities, "revision_count": 0, "feedback": ""}

def football_api_execution_node(state: FootballSubState) -> dict:
    print("\n--- NODE 2: Direct API Agent Execution ---")
    query = state.get("query", "")
    entities = state.get("entities", {})
    feedback = state.get("feedback", "")
    
    prompt_text = f"User Query: {query}\n\nExtracted Entities: {json.dumps(entities)}"
    
    if feedback:
        print(f">>> Applying Critic Feedback: {feedback}")
        prompt_text += f"\n\nPREVIOUS ATTEMPT FAILED. QA Feedback: {feedback}\nTry a different tool or parameters."

    try:
        result = football_agent_executor.invoke({
            "messages": [
                ("system", system_prompt),
                ("user", prompt_text)
            ]
        })
        
        final_answer = result["messages"][-1].content
        
        # DEBUG: Print the exact text the LLM generated
        print(f">>> DEBUG - LLM RAW OUTPUT: {final_answer}")
        
    except Exception as e:
        # DEBUG: Print the exact Python crash reason
        print(f"\n>>> DEBUG - PYTHON ERROR CAUSING CRASH: {str(e)}")
        final_answer = f"Error: {str(e)}"
        
    return {"final_response": final_answer}

def football_reflection_node(state: FootballSubState) -> dict:
    print("\n--- NODE 2.5: QA Reflection (The Critic) ---")
    query = state.get("query", "")
    response = state.get("final_response", "")
    revision_count = state.get("revision_count", 0)

    critic_prompt = f"""
    You are a strict QA Manager for a Football Analytics company.
    
    User Question: "{query}"
    Agent's Answer: "{response}"
    
    Did the agent successfully and clearly answer the user's question?
    - If the agent answered it, reply EXACTLY with: PASS
    - If the agent gave an error, hallucinated, or failed to answer, reply with a 1-sentence instruction on what it must fix.
    """
    
    critic_evaluation = extract_llm.invoke([HumanMessage(content=critic_prompt)]).content.strip()
    
    if "PASS" in critic_evaluation.upper():
        print(">>> QA Status: PASSED")
        return {"feedback": "PASS", "revision_count": revision_count + 1}
    else:
        print(f">>> QA Status: FAILED. Feedback: {critic_evaluation}")
        return {"feedback": critic_evaluation, "revision_count": revision_count + 1}

def football_finalize_node(state: FootballSubState) -> dict:
    print("\n--- NODE 3: Finalize Response ---")
    return {"final_response": state.get("final_response")}

# === 6. ROUTING LOGIC ===
def should_revise(state: FootballSubState):
    """Routes the graph based on the Critic's feedback."""
    feedback = state.get("feedback", "")
    revision_count = state.get("revision_count", 0)
    
    if revision_count >= 2:
        print("\n>>> Max revisions reached. Forcing completion.")
        return "finalize"
        
    if feedback == "PASS":
        return "finalize"
    else:
        return "api_execute" # Loop back!

# === 7. GRAPH ASSEMBLY ===
football_builder = StateGraph(FootballSubState)

football_builder.add_node("extract", football_extract_node)
football_builder.add_node("api_execute", football_api_execution_node)
football_builder.add_node("reflect", football_reflection_node)
football_builder.add_node("finalize", football_finalize_node)

football_builder.add_edge(START, "extract")
football_builder.add_edge("extract", "api_execute")
football_builder.add_edge("api_execute", "reflect")

football_builder.add_conditional_edges(
    "reflect", 
    should_revise, 
    {"api_execute": "api_execute", "finalize": "finalize"}
)
football_builder.add_edge("finalize", END)

# Initialize memory for the Human-in-the-Loop breakpoint
memory = MemorySaver()

# Compile with the interrupt BEFORE the API executes
football_sector_graph = football_builder.compile(
    checkpointer=memory,
    interrupt_before=["api_execute"]
)

# === 8. EXECUTION & HUMAN-IN-THE-LOOP TEST ===
if __name__ == "__main__":
    # 1. Setup the thread configuration for memory
    config = {"configurable": {"thread_id": "football_test_1"}}
    initial_state = {"query": "What is the live score for Arsenal right now?"}
    
    print("\n==================================================")
    print("🚀 STARTING FOOTBALL GRAPH")
    print("==================================================")
    
    # 2. Run the graph until it hits the breakpoint
    for event in football_sector_graph.stream(initial_state, config):
        pass # We use print statements inside the nodes for cleaner logging
        
    # 3. Retrieve the paused state
    current_state = football_sector_graph.get_state(config)
    
    # 4. Human Interaction Block
    print("\n🚨 GRAPH PAUSED (HUMAN-IN-THE-LOOP) 🚨")
    print(f"The LLM extracted these entities: {json.dumps(current_state.values.get('entities'), indent=2)}")
    print("The graph is about to run the API execution node.")
    
    user_input = input("\nDo you approve these entities for the API call? (y/n): ")
    
    if user_input.lower() == 'y':
        print("\n▶️ RESUMING GRAPH...")
        # Pass None to stream to tell it to resume from the current state
        for event in football_sector_graph.stream(None, config):
            pass 
        
        # Print final result
        final_state = football_sector_graph.get_state(config)
        print("\n==================================================")
        print(f"✅ FINAL RESULT:\n{final_state.values.get('final_response')}")
        print("==================================================")
    else:
        print("\n❌ Execution cancelled by human.")