import os
import json
import logging
import pandas as pd
import pybaseball
from typing import Any, TypedDict
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langgraph.graph import StateGraph, START, END
from tenacity import retry, wait_exponential, stop_after_attempt
from sqlalchemy import text
from langchain_core.tools import tool
# Import your database engine
from db_utils import engine 

from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.table import Table
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback



logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("groq").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
console = Console()
install_rich_traceback(show_locals=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)

# Enable pybaseball caching to avoid rate limits
pybaseball.cache.enable()

# === STATE DEFINITION ===
class BaseballSubState(TypedDict):
    messages: list  # Memory for pronoun resolution
    query: str
    entities: dict[str, Any]
    schema_grounding: dict[str, Any]
    final_response: str
    db_query_result: str  
    fetch_attempts: int  
    data_synced: bool  

load_dotenv()

# === LLM & DB SETUP ===
extract_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_tokens=150)
sql_llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, max_tokens=1000)

# Restrict the SQL Agent to ONLY the 5 Dodgers tables
dodgers_tables = [
    "dodgers_roster", 
    "dodgers_batting_season", 
    "dodgers_pitching_season", 
    "dodgers_game_logs", 
    "dodgers_statcast"
]

baseball_db = SQLDatabase(engine, include_tables=dodgers_tables)

@tool
def read_init_db_schema() -> str:
    """
    MUST BE CALLED FIRST. Reads the init_baseball_db.py file to provide the exact 
    database schema, DDL, and column definitions for the Dodgers database.
    """
    try:
        with open("baseball_db_init.py", "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading schema file: {str(e)}. Fall back to sql_db_schema tool."

baseball_sql_executor = create_sql_agent(
    llm=sql_llm,
    db=baseball_db,
    agent_type="openai-tools",
    extra_tools = [read_init_db_schema],
    verbose=False
)

# === SAFE WRAPPERS ===
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
def safe_extract_invoke(prompt_content: str):
    return extract_llm.invoke([HumanMessage(content=prompt_content)]).content

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
def safe_sql_invoke(prompt_dict: dict):
    return baseball_sql_executor.invoke(prompt_dict)


def parse_json_safely(text: str) -> dict:
    """Helper to strip markdown backticks from LLM JSON output."""
    try:
        cleaned = text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception as e:
        logger.error(f"JSON Parse Error: {e} - Raw: {text}")
        return {"question_type": "unknown", "relevant_tables": [], "relevant_columns": [], "strategy": "fallback", "needs_validation": True, "reason": "Failed to parse grounding."}


def truncate_text(value: str, max_len: int = 250) -> str:
    if value is None:
        return ""
    value = str(value)
    return value if len(value) <= max_len else value[:max_len] + " ...[truncated]"


def log_node(title: str, body: str, style: str = "cyan") -> None:
    console.print(Panel(body, title=title, border_style=style))


def log_kv_panel(title: str, data: dict, style: str = "cyan") -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for k, v in data.items():
        table.add_row(str(k), truncate_text(v, 300))
    console.print(Panel(table, title=title, border_style=style))


def log_schema_grounding(data: dict) -> None:
    console.print(
        Panel(
            Pretty(data, expand_all=False),
            title="Schema Grounding",
            border_style="magenta"
        )
    )

# === PYBASEBALL SYNC TOOL (DODGERS 5-TABLE ARCHITECTURE) ===
def sync_baseball_data_to_neon(year: int, category: str) -> str:
    """
    Dynamically fetches data via pybaseball, filters ONLY for LA Dodgers, and pushes to Neon.
    """
    # print(f">>> [LAD-SYNC] Fetching {year} Dodgers {category} stats via pybaseball...")
    log_node("PyBaseball Sync", f"Fetching {year} Dodgers {category} stats", "yellow")
    
    try:
        if category == "pitching":
            df = pybaseball.pitching_stats(year)
            df = df[df['Team'].isin(['LAD', 'Dodgers'])]
            table_name = "dodgers_pitching_season"
            
        elif category == "batting":
            df = pybaseball.batting_stats(year)
            df = df[df['Team'].isin(['LAD', 'Dodgers'])]
            table_name = "dodgers_batting_season"
            
        elif category == "team":
            # Fetch Dodgers specific game log / team results for that year
            df = pybaseball.team_results(year, 'LAD')
            table_name = "dodgers_game_logs"
            
        elif category == "statcast":
            # Statcast requires dates. We pull the core regular season.
            start_dt = f"{year}-03-25"
            end_dt = f"{year}-10-31"
            log_node("PyBaseball Sync", "Downloading Statcast data (may take ~30 seconds)", "yellow")
            # print(f">>> [LAD-SYNC] Downloading Statcast data (This may take ~30 seconds)...")
            df = pybaseball.statcast(start_dt=start_dt, end_dt=end_dt)
            # Filter where Dodgers are either hitting or pitching
            df = df[(df['home_team'] == 'LAD') | (df['away_team'] == 'LAD')]
            table_name = "dodgers_statcast"
        elif category == "roster":
            # Fetches active players and their IDs
            from pybaseball import playerid_lookup
            # We can pull the Dodgers active roster (you could use pybaseball's roster function)
            # For simplicity, pybaseball.roster(year) fetches the team roster
            df = pybaseball.roster(year, 'LAD')
            table_name = "dodgers_roster"
        else:
            raise ValueError(f"Unknown category: {category}")
            
        # Clean column names for PostgreSQL
        df.columns = df.columns.str.lower().str.replace(r'[^a-z0-9_]', '_', regex=True)
        df['season_year'] = year
        
        # Push to Neon Database
        df.to_sql(table_name, engine, if_exists='append', index=False, chunksize=500)
        
        msg = f"✅ Successfully synced {len(df)} {category} records for {year} LAD to Neon."
        # print(f">>> {msg}")
        log_node("PyBaseball Sync Success", msg, "green")
        return msg
        
    except Exception as e:
        error_msg = f"❌ Dodgers Sync Failed: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)

# === NODES ===
def baseball_extract_node(state: BaseballSubState) -> dict:
    # print("--- NODE 1: Dodgers Entity Extraction ---")
    log_node("NODE 1", "Dodgers Entity Extraction", "blue")
    messages = state.get("messages", [])
    history_str = "\n".join([f"{m.type}: {m.content}" for m in messages[-4:]]) if messages else "No history."

    extraction_prompt = f"""
    Analyze this LA Dodgers query. Use Chat History to resolve pronouns.
    
    Chat History: {history_str}
    Current Query: "{state['query']}"
    
    Extract these entities:
    - year (as integer, e.g., 2022)
    - player (full name, if asking about a specific player)
    - category (Determine which database table is needed based on the query:
      * "batting" -> HRs, AVG, OPS, wRC+, walks, hits.
      * "pitching" -> ERA, Strikeouts, Saves, WHIP.
      * "team" -> Dodgers wins, losses, streaks, scores, game schedule.
      * "statcast" -> Exit velocity, launch angle, pitch speed, pitch types, or specific pitch-by-pitch events.)

    Respond with ONLY a JSON object. If a field is not found, use null.
    Example: {{"year": 2024, "player": "Shohei Ohtani", "category": "statcast"}}
    """

    response = safe_extract_invoke(extraction_prompt)
    try:
        entities = json.loads(response)
    except json.JSONDecodeError:
        entities = {"year": None, "player": None, "category": "batting"}
    log_kv_panel("Extracted Entities", entities, "blue")
    return {"entities": entities, "fetch_attempts": 0, "data_synced": False}


def baseball_schema_ground_node(state: BaseballSubState) -> dict:
    # print("--- NODE 1.5: Schema Grounding & Strategy Planning ---")
    log_node("NODE 1.5", "Schema Grounding & Strategy Planning", "magenta")
    query_text = state.get("query", "")
    
    # Read the DDL explicitly for grounding
    try:
        with open("init_baseball_db.py", "r") as f:
            schema_text = f.read()
    except Exception as e:
        schema_text = "Schema unavailable."

    grounding_prompt = f"""
You are a TWG Global LA Dodgers Data Architect.
Your job is to analyze the user query against the physical database schema and formulate a pure data strategy. 
Do NOT answer the question. Only map the question to the schema.

User Query: "{query_text}"

Available Database Schema:
{schema_text}

Analyze the schema and output a query strategy in this EXACT JSON format:
{{
  "domain": "baseball",
  "question_type": "direct_lookup|aggregate|comparison|trend|event_level_detail",
  "relevant_tables": ["list_of_string_table_names"],
  "relevant_columns": ["list_of_string_column_names"],
  "strategy": "A concise explanation of how to query this data",
  "needs_validation": true/false,
  "reason": "Briefly explain why validation is or isn't needed based on the schema"
}}

Rules for `needs_validation`:
Set to `true` IF:
- The query requires counting, summing, or aggregating records.
- The question relies on interpreting an ambiguous column (e.g., win/loss indicators).
- The query requires deriving a value not explicitly stored.
Otherwise, set to `false`.

Respond with ONLY the valid JSON object.
"""
    
    # Using the heavy reasoning model to ensure flawless planning
    response_text = sql_llm.invoke([HumanMessage(content=grounding_prompt)]).content
    schema_grounding = parse_json_safely(response_text)
    
    print(f">>> Grounding Strategy: {schema_grounding.get('strategy', 'Failed to plan')}")
    print(f">>> Needs Validation: {schema_grounding.get('needs_validation', True)}")

    return {"schema_grounding": schema_grounding}



def baseball_query_db_node(state: BaseballSubState) -> dict:
    print("--- NODE 2: Query Dodgers Database ---")
    entities = state.get("entities", {})
    query_text = state.get("query", "")
    
    year = entities.get("year")
    category = entities.get("category", "batting")
    
    # Map category to the exact table name for existence check
    category_to_table = {
        "batting": "dodgers_batting_season",
        "pitching": "dodgers_pitching_season",
        "team": "dodgers_game_logs",
        "statcast": "dodgers_statcast"
    }
    table_name = category_to_table.get(category, "dodgers_batting_season")
    
    # Fast existence check to save 70B tokens
    if year:
        try:
            with engine.connect() as conn:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name} WHERE season_year = :y"), {"y": year}).scalar()
            if not count:
                return {"db_query_result": "NO_DATA_IN_DB", "data_synced": False}
        except Exception:
            # Table probably doesn't exist yet, proceed to agent which will return NO_DATA
            pass

    agent_prompt = f"""
You are a TWG Global LA Dodgers Analyst.

User question: '{query_text}'
Context entities: {json.dumps(entities)}

Rules:
1. You MUST call the `read_init_db_schema` tool BEFORE writing any SQL queries to inspect the schema.
2. Never invent tables or columns. Formulate your query path purely based on the tool's output.
3. If the answer depends on an aggregate (e.g., counting wins, averaging stats) or an ambiguous field, validate your interpretation by running a small sample query (e.g., SELECT * LIMIT 3) FIRST to observe the raw row format.
4. Prefer the most direct table for the question.
5. Use ILIKE for partial player-name matching when relevant.
6. If no relevant rows exist, return exactly: NO_DATA_IN_DB
7. All data belongs to the LA Dodgers. You do not need to filter by team.
8. In the final answer, cite the supporting table(s), column(s), and the basis of your result in concise natural language.

Your job is to inspect the schema, reason about the data structure, validate your assumptions, and answer only from database evidence.
"""

    try:
        result = safe_sql_invoke({"input": agent_prompt})
        db_result = result["output"]
        print(f">>> SQL Query Result: {db_result[:200]}...")
    except Exception as e:
        db_result = f"ERROR: {str(e)}"

    return {"db_query_result": db_result, "data_synced": False}

def baseball_fetch_api_node(state: BaseballSubState) -> dict:
    print("--- NODE 3: Fetch PyBaseball Dodgers API ---")
    entities = state.get("entities", {})
    year = entities.get("year")
    category = entities.get("category", "batting")
    fetch_attempts = state.get("fetch_attempts", 0)

    if fetch_attempts >= 2:
        return {"final_response": "Max fetch attempts reached.", "data_synced": False, "fetch_attempts": fetch_attempts}

    if not year:
        return {"final_response": "I need a specific year to fetch Dodgers stats.", "data_synced": False, "fetch_attempts": fetch_attempts}

    try:
        sync_baseball_data_to_neon(year, category)
        return {"db_query_result": "", "data_synced": True, "fetch_attempts": fetch_attempts + 1}
    except Exception as e:
        return {"final_response": str(e), "data_synced": False, "fetch_attempts": fetch_attempts + 1}

def baseball_decision_node(state: BaseballSubState) -> dict:
    return {}

def baseball_finalize_node(state: BaseballSubState) -> dict:
    print("--- NODE 4: Finalize Response ---")
    db_result = state.get("db_query_result", "")
    final_response = state.get("final_response", "")

    if final_response: return {"final_response": final_response}
    if not db_result or "no_data_in_db" in db_result.lower():
        return {"final_response": "I couldn't find the requested Dodgers data."}

    return {"final_response": db_result}

# === GRAPH ASSEMBLY ===
baseball_internal_builder = StateGraph(BaseballSubState)

baseball_internal_builder.add_node("extract", baseball_extract_node)
baseball_internal_builder.add_node("schema_ground", baseball_schema_ground_node)
baseball_internal_builder.add_node("query", baseball_query_db_node)
baseball_internal_builder.add_node("fetch", baseball_fetch_api_node)
baseball_internal_builder.add_node("decide", baseball_decision_node)
baseball_internal_builder.add_node("finalize", baseball_finalize_node)

baseball_internal_builder.add_edge(START, "extract")
baseball_internal_builder.add_edge("extract", "schema_ground")
baseball_internal_builder.add_edge("schema_ground", "query")
baseball_internal_builder.add_edge("query", "decide")

baseball_internal_builder.add_conditional_edges(
    "decide",
    lambda state: (
        "end" if state.get("final_response") else
        "query" if state.get("data_synced") else
        "fetch" if "no_data_in_db" in state.get("db_query_result", "").lower() and state.get("fetch_attempts", 0) < 2 else
        "end"
    ),
    {"query": "query", "fetch": "fetch", "end": "finalize"}
)

baseball_internal_builder.add_edge("fetch", "decide")
baseball_internal_builder.add_edge("finalize", END)

baseball_sector_graph = baseball_internal_builder.compile()