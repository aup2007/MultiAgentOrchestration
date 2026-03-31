import os
import sys
from io import StringIO
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

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)


def check_if_data_exists(year: int, location: str):
    """Checks the Cloud DB to see if we already synced this race."""
    query = text("""
        SELECT COUNT(*) FROM f1_telemetry 
        WHERE year = :y AND event_name = :loc
    """)
    with engine.connect() as conn:
        count = conn.execute(query, {"y": year, "loc": location}).scalar()
    return count > 0



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
        df_to_sync['driver'] = laps_raw['Driver']       # Map 'Driver' to 'driver'
        df_to_sync['team'] = laps_raw['Team']           # Map 'Team' to 'team'
        df_to_sync['lap_number'] = laps_raw['LapNumber']
        
        # CORRECTED: Pull from 'LapTime' (API) to 'lap_time_seconds' (DB)
        df_to_sync['lap_time_seconds'] = laps_raw['LapTime'].dt.total_seconds()
        
        # 4. EXECUTE: The "Upload" to Neon
        df_to_sync.to_sql(
            'f1_telemetry', 
            engine, 
            if_exists='append', 
            index=False,
            method='multi' # Prevents the parameter truncation error
        )
        
        return laps_raw.pick_fastest()
    finally:
        Cache.set_enabled()

def f1_node(state: AgentState):
    """
    Production F1 Node. Stateless sync to Cloud Neon.
    """
    print("--- LOG: Processing F1 Sector ---")
    
    extraction_prompt = f"""
    Extract the Year and Location from this query: "{state['query']}"
    Return ONLY in format: Year, Location. Example: 2023, Monaco
    """
    extraction = llm.invoke([HumanMessage(content=extraction_prompt)]).content

    try:
        parts = extraction.split(",")
        year = int(parts[0].strip())
        location = parts[1].strip()


        if check_if_data_exists(year, location):
            print(f">>> [CACHE HIT] {year} {location} found. Querying Neon...")
            
            # Use SQL to find the fastest lap directly from the cloud
            query = text("""
                SELECT driver, team, lap_number, lap_time_seconds 
                FROM f1_telemetry 
                WHERE year = :y AND event_name = :loc
                ORDER BY lap_time_seconds ASC
                LIMIT 1
            """)
            
            with engine.connect() as conn:
                data = conn.execute(query, {"y": year, "loc": location}).fetchone()
            
            # if result:
            #     driver, time = result
            #     # Convert seconds back to a readable format if you want, or just print
            #     return {
            #         "final_response": f"According to the Cloud Warehouse, the fastest lap in {year} {location} was set by {driver} with a {time:.3f}s.",
            #         "domain_detected": "f1"
            #     }
        else: 
        # 3. CACHE MISS: Only download if it's NOT in the DB
            print(f">>> [CACHE MISS] Fetching {year} {location} from API...")
            fastest_lap = sync_telemetry_to_neon(year, location, 'R')
            data = (fastest_lap['Driver'], fastest_lap['Team'], fastest_lap['LapNumber'], fastest_lap['LapTime'].total_seconds())


        analysis_prompt = (
        f"The user asked: {state['query']}\n"
        f"The telemetry data shows: Driver: {data[0]}, Team: {data[1]}, "
        f"Lap: {data[2]}, Time: {data[3]}s.\n"
        "As a TWG Global Analyst, provide a professional, concise response."
    )
    
        final_ai_msg = llm.invoke([SystemMessage(content="You are a professional F1 analyst."), 
                               HumanMessage(content=analysis_prompt)])
        
        
        return {
            "final_response": final_ai_msg.content,
            "messages": [HumanMessage(content=f"Processed F1 sync for {year} {location}")],
            "domain_detected": "f1"
        }

    except Exception as e:
        return {"final_response": f"F1 Cloud Sync Error: {str(e)}"}