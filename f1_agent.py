import os
import json
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
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
from typing import Any
from typing import TypedDict

# This is the ONLY state these 3 nodes will care about
class F1SubState(TypedDict):
    query: str
    entities: dict[str, Any]
    final_response: str

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.3)
f1_db = SQLDatabase(engine)
f1_sql_executor = create_sql_agent(
    llm=llm, 
    db=f1_db, 
    agent_type="openai-tools", 
    verbose=True
)





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
        print(">>> [DB NOTICE] Table 'f1_telemetry' missing. Treating as a cache miss.")
        return False



def sync_telemetry_to_neon(year: int, location: str, session_type: str):
    """
    Downloads F1 data to RAM and executes the SQL push to Neon Cloud.
    """
    print(f">>> [F1-SYNC] Streaming {year} {location} telemetry to Neon Cloud (Stateless)...")
    
    Cache.set_disabled()
    
    try:
        # 1. Load data into RAM
        session = fastf1.get_session(year, location, session_type)
        session.load(laps=True, telemetry=False, weather=False)
        
        # 2. Infrastructure Check (Using your existing function)
        ensure_f1_partition(year, engine)
        
        # 3. FIX: Create a CLEAN DataFrame that matches your Postgres schema EXACTLY
        laps_raw = session.laps.copy()
        df_to_sync = pd.DataFrame()
        
        df_to_sync['year'] = [year] * len(laps_raw)
        df_to_sync['event_name'] = [location] * len(laps_raw)
        # df_to_sync['driver'] = laps_raw['Driver']       # Map 'Driver' to 'driver'
        # df_to_sync['team'] = laps_raw['Team']           # Map 'Team' to 'team'
        # df_to_sync['lap_number'] = laps_raw['LapNumber']
        
        # # CORRECTED: Pull from 'LapTime' (API) to 'lap_time_seconds' (DB)
        # df_to_sync['lap_time_seconds'] = laps_raw['LapTime'].dt.total_seconds()

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
        
        # Datetime column
        df_to_sync['lap_start_date'] = laps_raw['LapStartDate']
        
        # Standard Data Mapping (Strings, Booleans, Numerics)
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
        
        # 4. EXECUTE: The "Upload" to Neon
        try: 
            df_to_sync.to_sql(
                'f1_telemetry', 
                engine, 
                if_exists='append', 
                index=False,
                chunksize=500
            )
            print(">> Data inserted <<")
        except sqlalchemy.exc.SQLAlchemyError as db_err:
            original_error = getattr(db_err, 'orig', db_err)
            print("\n" + "="*50)
            print(" CLEAN DATABASE ERROR REPORT ")
            print("="*50)
            print(f"ERROR DETAILS:\n{original_error}")
            print("="*50 + "\n")
            
            # Raise a clean, short error so the LangGraph agent doesn't print the data payload either
            raise Exception(f"DB Insert Failed: {original_error}")
        return laps_raw.pick_fastest()
    finally:
        Cache.set_enabled()


def f1_extract_node(state: F1SubState):
    """Node 1: Extracts the year and location, checks for missing context."""
    print("--- NODE 1: Extraction ---")
    
    extraction_prompt = f"""
    Analyze: "{state['query']}"
    Extract all relevant F1 entities (year, driver, event_name, team, lap_number).
    Respond with ONLY a JSON object.
    """
    
    response = llm.invoke([HumanMessage(content=extraction_prompt)]).content
    
    try:
        entities = json.loads(response)
    except json.JSONDecodeError:
        entities = {"year": None, "location": None}

    return {"entities": entities}
        
    # year = data.get("year")
    # location = data.get("location")
    
    # # EARLY EXIT CHECK: Catch missing data immediately
    # if not year or not location:
    #     return {
    #         "year": year, 
    #         "location": location,
    #         "final_response": "Could you please specify the year and the race location? (For example: '2024 Monaco')",
    #         "domain_detected": "f1"
    #     }
    
    # return {
    #     "year": year, 
    #     "location": location
    # }


def f1_sync_node(state: F1SubState):
    """Node 2: Checks the DB and downloads FastF1 data if missing."""
    print("--- NODE 2: Database Sync ---")
    
    entities = state.get("entities", {})
    year = entities.get("year")
    location = entities.get("event_name") or entities.get("location")
    # EARLY EXIT: If Node 1 already asked for clarification, skip this node entirely
    if state.get("final_response"):
        print(">>> [SKIP] Missing context. Bypassing sync.")
        return {}
        
    if year and location:
        if not check_if_data_exists(year, location):
            print(f">>> [CACHE MISS] Fetching {year} {location} from API...")
            try:
                sync_telemetry_to_neon(year, location, 'R')
            except Exception as e:
                print(f">>> [SYNC ERROR] {e}")
        else:
            print(f">>> [CACHE HIT] {year} {location} data is ready.")
    else:
        # Don't return a final_response here, just let it pass to SQL
        print(">>> [INFO] No race context for sync. Proceeding to SQL Agent.")
            
    return {}


def f1_sql_node(state: F1SubState):
    """Node 3: Executes the dynamic SQL Query."""
    print("--- NODE 3: Text-to-SQL ---")
    entities = state.get("entities", {})
    # EARLY EXIT: If Node 1 already asked for clarification, do not run the SQL Agent
    if state.get("final_response"):
        print(">>> [SKIP] Missing context. Bypassing Text-to-SQL.")
        return {}
        
    year = entities.get("year")
    location = entities.get("location")

    print(">>> Executing dynamic Text-to-SQL...")
    context = json.dumps(entities)
    agent_prompt = (
        f"Query: {state['query']}\n"
        f"Context Entities: {context}\n"
        f"Instructions:\n"
        f"1. Use the 'f1_telemetry' table for lap-by-lap data.\n"
        f"2. Use the provided Context Entities to filter your SQL queries (e.g., year, event_name).\n"
        f"3. If the telemetry table doesn't have the answer, use your general knowledge."
    )
    
    result = f1_sql_executor.invoke({"input": agent_prompt})
    return {"final_response": result["output"]}
    
    # agent_prompt = (
    #     f"You are a TWG Global F1 Analyst. Query: '{state['query']}'\n\n"
    #     f"DATA INTEGRITY RULES:\n"
    #     f"1. Table: 'f1_telemetry' | Filters: WHERE year = {year} AND event_name = '{location}'\n"
    #     f"2. DO NOT GUESS NAMES.\n"
    #     f"3. Cross-reference the 'driver' code with the 'team' column before naming a driver.\n"
    #     f"4. If you are unsure of a name, just use the Driver Code (e.g., 'Driver NOR') or the Driver Number."
    # )
    
    # result = f1_sql_executor.invoke({"input": agent_prompt})
    
    # return {"final_response": result["output"]}




f1_internal_builder = StateGraph(F1SubState)
f1_internal_builder.add_node("extract", f1_extract_node)
f1_internal_builder.add_node("sync", f1_sync_node)
f1_internal_builder.add_node("sql", f1_sql_node)

f1_internal_builder.add_edge(START, "extract")
f1_internal_builder.add_edge("extract", "sync")
f1_internal_builder.add_edge("sync", "sql")
f1_internal_builder.add_edge("sql", END)


f1_sector_graph = f1_internal_builder.compile()

if __name__ == "__main__":
    with open("f1_internal_architecture.png", "wb") as f:
        f.write(f1_sector_graph.get_graph().draw_mermaid_png())
    print("✅ Generated f1_internal_architecture.png")
# def f1_node(state: AgentState):
#     """
#     Production F1 Node. Stateless sync to Cloud Neon.
#     """
#     print("--- LOG: Processing F1 Sector ---")
    
#     extraction_prompt = f"""
#     Analyze this query: "{state['query']}"
#     Extract the 'year' (as an integer) and the 'location' (as a string).
#     If either is missing, return null for that field.
    
#     You MUST respond with ONLY a valid JSON object. No markdown, no explanations.
#     Example 1: {{"year": 2024, "location": "Monaco"}}
#     Example 2: {{"year": null, "location": "Silverstone"}}
#     Example 3: {{"year": null, "location": null}}
#     """
#     extraction = llm.invoke([HumanMessage(content=extraction_prompt)]).content

#     try:
#         extracted_data = json.loads(extraction)
#         year = extracted_data.get("year")
#         location = extracted_data.get("location")

#         if not year or not location:
#             print(">>> [MISSING DATA] Prompting user for clarification...")
#             missing_items = []
#             if not year: missing_items.append("the year")
#             if not location: missing_items.append("the specific race/location")
            
#             clarification_msg = f"Could you please specify {' and '.join(missing_items)}? (For example: '2024 Monaco')"
            
#             return {
#                 "final_response": clarification_msg,
#                 "domain_detected": "f1"
#             }


#         # 1. CACHE CHECK & SYNC (Data Orchestration)
#         if not check_if_data_exists(year, location):
#             print(f">>> [CACHE MISS] Fetching {year} {location} from API...")
#             # We no longer need to save the return value of sync_telemetry_to_neon
#             # because the SQL agent will fetch the data directly from the DB.
#             sync_telemetry_to_neon(year, location, 'R')
#         else:
#             print(f">>> [CACHE HIT] {year} {location} found in Neon DB.")

#         # 2. DYNAMIC TEXT-TO-SQL (Query Orchestration)
#         print(">>> Executing dynamic Text-to-SQL via LangChain Agent...")
        
#         # We wrap the user's query with strict instructions so the agent 
#         # filters the database efficiently and responds as an analyst.
#         agent_prompt = (
#             f"You are a TWG Global F1 Analyst. Answer the user's query: '{state['query']}'\n\n"
#             f"CRITICAL DB INSTRUCTIONS:\n"
#             f"1. The data for this specific race is in the 'f1_telemetry' table.\n"
#             f"2. You MUST include WHERE year = {year} AND event_name = '{location}' in every SQL query you write.\n"
#             f"3. Do not query other years or locations.\n"
#             f"4. Once you have the SQL result, provide a professional, concise summary."
#         )
        
#         # Invoke the LangChain SQL Agent
#         result = f1_sql_executor.invoke({"input": agent_prompt})
        
#         return {
#             "final_response": result["output"],
#             "messages": [HumanMessage(content=f"Processed dynamic Text-to-SQL for {year} {location}")],
#             "domain_detected": "f1"
#         }

#     except Exception as e:
#         return {"final_response": f"F1 Cloud Sync Error: {str(e)}"}