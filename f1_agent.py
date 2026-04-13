import os
import json
import re
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from state import AgentState
from db_utils import engine, ensure_f1_partition
from dotenv import load_dotenv
import pandas as pd
import fastf1
from fastf1 import Cache
from sqlalchemy import text
import sqlalchemy.exc
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langgraph.graph import StateGraph, START, END
from typing import Any, Literal
from typing import TypedDict
import logging
from tenacity import retry, wait_exponential, stop_after_attempt

logger = logging.getLogger(__name__)

# === STATE DEFINITION ===
class F1SubState(TypedDict):
    query: str
    entities: dict[str, Any]
    schema_grounding: dict[str, Any]
    final_response: str
    db_query_result: str  # Result from Text-to-SQL
    fetch_attempts: int  # Track number of API fetch attempts
    data_synced: bool  # Flag: has data been synced in this cycle?

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

extract_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_tokens=100, streaming=False)
sql_llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, max_tokens=1000, streaming=False)


llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.3, streaming=True)
f1_db = SQLDatabase(engine, include_tables=["f1_telemetry"])

# Use the same SQL agent for querying
f1_sql_executor = create_sql_agent(
    llm=sql_llm,
    db=f1_db,
    agent_type="openai-tools",
    verbose=False
)


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10), 
    stop=stop_after_attempt(3),
    reraise=True
)
def safe_extract_invoke(prompt_content: str):
    return extract_llm.invoke([HumanMessage(content=prompt_content)]).content

# Safe wrapper for the LangChain SQL Agent
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10), 
    stop=stop_after_attempt(3),
    reraise=True
)
def safe_sql_invoke(prompt_dict: dict):
    return f1_sql_executor.invoke(prompt_dict)


def parse_json_safely(text: str) -> dict:
    """Helper to extract and parse JSON even if the LLM adds extra text."""
    try:
        # Try to extract JSON object from text using regex
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        # Fallback: try direct parsing
        cleaned = text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception as e:
        logger.error(f"JSON Parse Error: {e} - Raw: {text}")
        return {"question_type": "unknown", "relevant_tables": [], "relevant_columns": [], "strategy": "fallback", "needs_validation": True, "reason": "Failed to parse grounding."}





# === TOOLS ===

@tool
def sync_telemetry_tool(year: int, location: str, session_type: str = "R") -> str:
    """
    Downloads F1 telemetry from FastF1 API and syncs to Neon PostgreSQL.
    Returns success/failure message.

    Args:
        year: Race year (e.g., 2024)
        location: Race location (e.g., "Monaco")
        session_type: "R" for Race, "FP1", "FP2", "FP3", "Q" for Qualifying
    """
    return sync_telemetry_to_neon(year, location, session_type)


def check_if_data_exists(year: int, location: str):
    """Checks the Cloud DB to see if we already synced this race."""
    try:
        query = text("""
            SELECT COUNT(*) FROM f1_telemetry
            WHERE year = :y AND event_name = :loc
        """)
        with engine.connect() as conn:
            count = conn.execute(query, {"y": year, "loc": location}).scalar()
        return count > 0
    except Exception as e:
        logger.warning(f"Table 'f1_telemetry' check failed: {e}")
        return False


def sync_telemetry_to_neon(year: int, location: str, session_type: str) -> str:
    """
    Downloads F1 data to RAM and executes the SQL push to Neon Cloud.
    Returns a status message.
    """
    print(f">>> [F1-SYNC] Streaming {year} {location} telemetry to Neon Cloud...")

    Cache.set_disabled()

    try:
        # 1. Load data into RAM
        session = fastf1.get_session(year, location, session_type)
        session.load(laps=True, telemetry=False, weather=False)

        # 2. Infrastructure Check
        ensure_f1_partition(year, engine)

        # 3. Create DataFrame matching Postgres schema
        laps_raw = session.laps.copy()
        df_to_sync = pd.DataFrame()

        df_to_sync['year'] = [year] * len(laps_raw)
        df_to_sync['event_name'] = [location] * len(laps_raw)
        df_to_sync['time_seconds'] = laps_raw['Time'].dt.total_seconds()
        df_to_sync['lap_time_seconds'] = laps_raw['LapTime'].dt.total_seconds()
        df_to_sync['pit_out_time_seconds'] = laps_raw['PitOutTime'].dt.total_seconds()
        df_to_sync['pit_in_time_seconds'] = laps_raw['PitInTime'].dt.total_seconds()
        df_to_sync['sector1_time_seconds'] = laps_raw['Sector1Time'].dt.total_seconds()
        df_to_sync['sector2_time_seconds'] = laps_raw['Sector2Time'].dt.total_seconds()
        df_to_sync['sector3_time_seconds'] = laps_raw['Sector3Time'].dt.total_seconds()
        df_to_sync['sector1_session_time_seconds'] = laps_raw['Sector1SessionTime'].dt.total_seconds()
        df_to_sync['sector2_session_time_seconds'] = laps_raw['Sector2SessionTime'].dt.total_seconds()
        df_to_sync['sector3_session_time_seconds'] = laps_raw['Sector3SessionTime'].dt.total_seconds()
        df_to_sync['lap_start_time_seconds'] = laps_raw['LapStartTime'].dt.total_seconds()

        df_to_sync['lap_start_date'] = laps_raw['LapStartDate']
        df_to_sync['driver'] = laps_raw['Driver']
        df_to_sync['driver_number'] = laps_raw['DriverNumber']
        df_to_sync['lap_number'] = laps_raw['LapNumber']
        df_to_sync['stint'] = laps_raw['Stint']
        df_to_sync['speed_i1'] = laps_raw['SpeedI1']
        df_to_sync['speed_i2'] = laps_raw['SpeedI2']
        df_to_sync['speed_fl'] = laps_raw['SpeedFL']
        df_to_sync['speed_st'] = laps_raw['SpeedST']
        df_to_sync['is_personal_best'] = laps_raw['IsPersonalBest']
        df_to_sync['compound'] = laps_raw['Compound']
        df_to_sync['tyre_life'] = laps_raw['TyreLife']
        df_to_sync['fresh_tyre'] = laps_raw['FreshTyre']
        df_to_sync['team'] = laps_raw['Team']
        df_to_sync['track_status'] = laps_raw['TrackStatus']
        df_to_sync['position'] = laps_raw['Position']
        df_to_sync['deleted'] = laps_raw['Deleted']
        df_to_sync['deleted_reason'] = laps_raw['DeletedReason']
        df_to_sync['fastf1_generated'] = laps_raw['FastF1Generated']
        df_to_sync['is_accurate'] = laps_raw['IsAccurate']

        # 4. Execute upload to Neon
        try:
            df_to_sync.to_sql(
                'f1_telemetry',
                engine,
                if_exists='append',
                index=False,
                chunksize=500
            )
            # Flush connection pool to ensure fresh connections see committed data
            refresh_sql_database_connection()
            msg = f"✅ Successfully synced {year} {location} ({len(df_to_sync)} laps) to Neon."
            print(f">>> {msg}")
            return msg
        except sqlalchemy.exc.SQLAlchemyError as db_err:
            original_error = getattr(db_err, 'orig', db_err)
            error_msg = f"❌ DB Insert Failed: {original_error}"
            logger.error(error_msg)
            raise Exception(error_msg)
    except Exception as e:
        error_msg = f"❌ Sync failed: {str(e)}"
        logger.error(error_msg)
        return error_msg
    finally:
        Cache.set_enabled()


# === NODES ===

def f1_extract_node(state: F1SubState) -> dict:
    """
    NODE 1: Extracts entities (year, location, driver) from user query.
    No routing logic here—just extraction.
    """
    print("--- NODE 1: Entity Extraction ---")

    extraction_prompt = f"""
    Analyze this F1 query: "{state['query']}"
    Extract all relevant F1 entities:
    - year (as integer, e.g., 2024)
    - event_name (race location, e.g., "Monaco")
    - driver (driver name or code)
    - team (team name)
    - lap_number (if mentioned)

    Respond with ONLY a JSON object. If a field is not found, use null.
    Example: {{"year": 2024, "event_name": "Monaco", "driver": "Hamilton", "team": null, "lap_number": null}}
    """

    # response = llm.invoke([HumanMessage(content=extraction_prompt)]).content
    response = safe_extract_invoke(extraction_prompt)

    try:
        entities = parse_json_safely(response)
    except Exception as e:
        logger.warning(f"Failed to parse extraction response: {response}")
        entities = {"year": None, "event_name": None, "driver": None, "team": None, "lap_number": None}

    return {"entities": entities, "fetch_attempts": 0, "data_synced": False}


def f1_schema_ground_node(state: F1SubState) -> dict:
    # print("--- NODE 1.5: Schema Grounding & Strategy Planning ---")
    print("NODE 1.5", "Schema Grounding & Strategy Planning", "magenta")
    query_text = state.get("query", "")
    
    # Read the DDL explicitly for grounding
    try:
        with open("db_utils.py", "r") as f:
            schema_text = f.read()
    except Exception as e:
        schema_text = "Schema unavailable."

    grounding_prompt = f"""
You are a TWG Global F1 Data Architect.
Your job is to analyze the user query against the physical database schema and formulate a pure data strategy. 
Do NOT answer the question. Only map the question to the schema.

User Query: "{query_text}"

Available Database Schema:
{schema_text}

Analyze the schema and output a query strategy in this EXACT JSON format:
{{
  "domain": "f1",
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





def f1_query_db_node(state: F1SubState) -> dict:
    """
    NODE 2: Query the database using Text-to-SQL.
    The LLM agent will recognize if the result is empty and decide whether to fetch.
    This is where the agentic loop starts.
    """
    print("--- NODE 2: Query Database (Text-to-SQL) ---")

    entities = state.get("entities", {})
    query_text = state.get("query", "")
    schema_grounding = state.get("schema_grounding", {})
    year = entities.get("year")
    event_name = entities.get("event_name")
    driver = entities.get("driver")

    if year and event_name and driver:
        try:
            exists_query = text("""
                SELECT COUNT(*)
                FROM f1_telemetry
                WHERE year = :year
                AND event_name ILIKE :event_name
                AND driver = :driver
            """)
            with engine.connect() as conn:
                count = conn.execute(
                    exists_query,
                    {
                        "year": year,
                        "event_name": f"%{event_name}%",
                        "driver": driver[:3].upper()
                    }
                ).scalar()

            if not count:
                return {
                    "db_query_result": "NO_DATA_IN_DB",
                    "data_synced": False
                }
        except Exception as e:
            logger.error(f"Existence check failed: {e}")

    # Build context for the SQL agent
    needs_val_rule = "You MUST validate your interpretation by running a small sample query (e.g., SELECT * LIMIT 3) FIRST to observe the raw row format." if schema_grounding.get("needs_validation") else "Validation query is optional for this direct lookup."
    context = json.dumps(entities)
    agent_prompt = f"""
        You are a TWG Global F1 Analyst. Answer this query: '{query_text}'

        Context Entities: {json.dumps(entities)}

        Query Strategy Plan (Follow this strictly):
        {json.dumps(schema_grounding, indent=2)}

        INSTRUCTIONS:
        1. Focus exclusively on the `relevant_tables` and `relevant_columns` outlined in your strategy plan.
        2. {needs_val_rule}
        3. Never invent tables or columns.
        4. If the table returns NO results or is empty, report exactly 'NO_DATA_IN_DB'.
        5. In the final answer, cite the supporting table(s), column(s), and the basis of your result.
        """

    try:
        # result = f1_sql_executor.invoke({"input": agent_prompt})
        result = safe_sql_invoke({"input": agent_prompt})
        db_result = result["output"]
        print(f">>> SQL Query Result: {db_result[:200]}...")  # First 200 chars
    except Exception as e:
        logger.error(f"SQL execution failed: {e}")
        db_result = f"ERROR: {str(e)}"

    return {"db_query_result": db_result,
            "data_synced": False
            }


def f1_fetch_api_node(state: F1SubState) -> dict:
    """
    NODE 3: Fetch data from FastF1 API and sync to Neon.
    This node is only reached if the agent decides data is missing.
    Includes safeguards against infinite loops.
    """
    print("--- NODE 3: Fetch API & Sync to Database ---")

    entities = state.get("entities", {})
    year = entities.get("year")
    location = entities.get("event_name")
    fetch_attempts = state.get("fetch_attempts", 0)

    MAX_FETCH_ATTEMPTS = 2  # Prevent infinite loops

    if fetch_attempts >= MAX_FETCH_ATTEMPTS:
        msg = f"⚠️ Max fetch attempts ({MAX_FETCH_ATTEMPTS}) reached. Cannot retrieve data."
        logger.warning(msg)
        return {
            "final_response": msg,
            "data_synced": False,
            "fetch_attempts": fetch_attempts
        }

    if not year or not location:
        msg = "Cannot fetch: year and location are required. Please specify the race (e.g., '2024 Monaco')."
        return {
            "final_response": msg,
            "data_synced": False,
            "fetch_attempts": fetch_attempts
        }

    try:
        sync_result = sync_telemetry_to_neon(year, location, "R")
        logger.info(f"Sync result: {sync_result}")

        return {
            "db_query_result": "",  # Clear for next cycle
            "data_synced": True,
            "fetch_attempts": fetch_attempts + 1
        }
    except Exception as e:
        error_msg = f"Failed to fetch from API: {str(e)}"
        logger.error(error_msg)
        return {
            "final_response": error_msg,
            "data_synced": False,
            "fetch_attempts": fetch_attempts + 1
        }


def f1_decision_node(state: F1SubState) -> dict:
    """
    DECISION NODE: Routes the flow based on the database query result.

    Returns:
    - "query": Loop back to query_db_node (data was just synced)
    - "fetch": Go to fetch_api_node (data is missing from DB)
    - "end": Done, go to END
    """
    print("--- DECISION NODE: Route Based on Query Result ---")

    db_result = state.get("db_query_result", "").lower()
    data_synced = state.get("data_synced", False)
    fetch_attempts = state.get("fetch_attempts", 0)

    # If we just synced data, loop back to query
    if data_synced:
        print(">>> 🔄 Data synced! Looping back to query database.")
        return {}

    # If DB returned empty, decide whether to fetch
    if "no_data_in_db" in db_result or "no results" in db_result or len(db_result.strip()) == 0:
        if fetch_attempts < 2:
            print(">>> 🔗 No data in DB. Fetching from API...")
            return {}
        else:
            print(">>> ⚠️ Max attempts reached. Exiting with empty result.")
            return {}

    # DB has data - we're done
    print(">>> ✅ Found data in database. Finalizing response.")
    return {}


async def f1_finalize_node(state: F1SubState) -> dict:
    """
    NODE 4: Finalize the response. Synthesizes the SQL Agent's output into Natural Language.
    Uses async streaming to accumulate tokens from the LLM.
    """
    print("--- NODE 4: Finalize Response ---")

    db_result = state.get("db_query_result", "")
    final_response = state.get("final_response", "")
    user_query = state.get("query", "")

    # If we hit an error during fetch, use that
    if final_response:
        return {"final_response": final_response}

    # If the database returned empty
    if not db_result or "no_data_in_db" in db_result.lower():
        return {
            "final_response": "I couldn't find the requested F1 data in the database. Please check the year and race location."
        }

    # SYNTHESIS STEP: Convert the raw SQL agent output into a conversational answer
    synthesis_prompt = f"""
    You are an expert F1 commentator.

    User Question: {user_query}
    Raw Database Output: {db_result}

    Synthesize the 'Raw Database Output' into a concise, conversational answer for the fan.

    CRITICAL RULES:
    1. Answer the question directly using ONLY the provided data.
    2. NEVER mention databases, tables, SQL queries, columns, or rows.
    3. NEVER say "The query returned", "Based on the data", or "The strategy is as follows:".
    """

    try:
        # Use astream to collect tokens for true streaming support
        response_chunks = []
        async for chunk in llm.astream([HumanMessage(content=synthesis_prompt)]):
            if hasattr(chunk, 'content') and chunk.content:
                response_chunks.append(chunk.content)
        clean_response = "".join(response_chunks)
        return {"final_response": clean_response}
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        # Fallback to the raw result if the LLM call fails
        return {"final_response": db_result}


# === GRAPH ASSEMBLY ===

f1_internal_builder = StateGraph(F1SubState)

# Add nodes
f1_internal_builder.add_node("extract", f1_extract_node)
f1_internal_builder.add_node("schema_ground", f1_schema_ground_node)
f1_internal_builder.add_node("query", f1_query_db_node)
f1_internal_builder.add_node("fetch", f1_fetch_api_node)
f1_internal_builder.add_node("decide", f1_decision_node)
f1_internal_builder.add_node("finalize", f1_finalize_node)

# Start with extraction
f1_internal_builder.add_edge(START, "extract")
f1_internal_builder.add_edge("extract", "schema_ground")

# Extract → Query (first database attempt)
f1_internal_builder.add_edge("schema_ground", "query")

# Query → Decision (decide what to do next)
f1_internal_builder.add_edge("query", "decide")

# Decision logic: conditional edges that create the cycle
f1_internal_builder.add_conditional_edges(
    "decide",
    lambda state: (
        "end" if state.get("final_response") else
        "query" if state.get("data_synced") else
        "fetch" if "no_data_in_db" in state.get("db_query_result", "").lower() and state.get("fetch_attempts", 0) < 2 else
        "end"
    ),
    {
        "query": "query",   # Loop back to query
        "fetch": "fetch",   # Go to fetch/sync
        "end": "finalize"   # Done, finalize response
    }
)

# Fetch → Decision (after syncing, decide again)
f1_internal_builder.add_edge("fetch", "decide")

# Finalize → END
f1_internal_builder.add_edge("finalize", END)

# Compile the subgraph
f1_sector_graph = f1_internal_builder.compile()

if __name__ == "__main__":
    with open("f1_internal_architecture.png", "wb") as f:
        f.write(f1_sector_graph.get_graph().draw_mermaid_png())
    print("✅ Generated f1_internal_architecture.png")
