# TWG Sports Intelligence Platform
## Technical Architecture Specification: Baseball & Football Subgraphs

**Version**: 1.0  
**Date**: 2026-04-01  
**Status**: Design Review & Implementation Roadmap  
**Audience**: Engineering Team, Scouts, Data Ops

---

## Executive Summary

This document specifies the technical architecture, state management, node logic, and data ingestion strategy for the **Baseball** and **Football (Soccer)** sectors of the TWG Sports Intelligence Platform.

Both subgraphs follow the **agentic cyclic routing pattern** established in the F1 sector, with sector-specific enhancements:
- **Baseball**: Lahman historical database + live MLB APIs
- **Football**: Soccer GitHub datasets + live match APIs

The system is designed for **scout-ready intelligence**—delivering professional-grade analysis with decision paths driven by LLM reasoning rather than hardcoded logic.

---

## Table of Contents

1. [Subgraph State Definitions](#subgraph-state-definitions)
2. [Node Architecture & Edge Logic](#node-architecture--edge-logic)
3. [Data Ingestion Roadmap](#data-ingestion-roadmap)
4. [System Architecture Diagram](#system-architecture-diagram)
5. [Cross-Sector Query Execution](#cross-sector-query-execution)
6. [Deployment Checklist](#deployment-checklist)

---

---

## 1. Subgraph State Definitions

### 1.1 Baseball Subgraph State (`BaseballSubState`)

```python
from typing import TypedDict, Any, Optional
from datetime import datetime

class BaseballSubState(TypedDict):
    """
    State for the Baseball sector subgraph.
    Tracks player/team queries, DB lookups, and analysis generation.
    """
    # === QUERY INTENT & ENTITIES ===
    query: str                          # User's natural language question
    intent: str                         # Extracted intent (e.g., "player_stats", "team_comparison")
    
    # === EXTRACTED ENTITIES ===
    entities: dict[str, Any]           # Parsed context from query
    # Expected keys (if present):
    # {
    #   "player_name": str,            # e.g., "Mike Trout"
    #   "player_id": str,              # Lahman playerID (e.g., "troutmi01")
    #   "team": str,                   # e.g., "LAA" (3-letter team code)
    #   "season": int,                 # Year (e.g., 2023)
    #   "league": str,                 # "MLB", "AAA", "AA", "A"
    #   "stat_category": str,          # e.g., "batting", "pitching", "fielding"
    #   "comparison_player": str,      # For comparative queries
    #   "time_period": str,            # "career", "season", "month", "week"
    # }
    
    # === VALIDATION & DATA RETRIEVAL ===
    validation_status: str             # "PENDING", "VALID", "INVALID"
    validation_error: str              # If INVALID, reason (e.g., "player_not_found")
    
    # === SQL GENERATION & EXECUTION ===
    sql_query: str                     # Generated Postgres query
    sql_error: str                     # If query failed, error message
    sql_execution_status: str          # "PENDING", "EXECUTED", "FAILED"
    
    # === RAW DATA BUFFER ===
    raw_data: list[dict[str, Any]]    # Query results from Neon DB
    raw_data_count: int                # Row count
    
    # === ANALYSIS & RESPONSE ===
    analysis: str                      # LLM-synthesized report
    final_response: str                # Scout-ready intelligence summary
    
    # === CONTROL FLOW ===
    attempt_count: int                 # Track retries (max 2)
    data_fetched: bool                 # Did we successfully fetch data?
    should_loop: bool                  # Should we re-attempt?
```

### 1.2 Football (Soccer) Subgraph State (`FootballSubState`)

```python
class FootballSubState(TypedDict):
    """
    State for the Football (Soccer) sector subgraph.
    Tracks player/team queries, match analysis, and tactical intelligence.
    """
    # === QUERY INTENT & ENTITIES ===
    query: str                          # User's natural language question
    intent: str                         # Extracted intent (e.g., "player_performance", "team_tactics", "match_analysis")
    
    # === EXTRACTED ENTITIES ===
    entities: dict[str, Any]           # Parsed context from query
    # Expected keys (if present):
    # {
    #   "player_name": str,            # e.g., "Erling Haaland"
    #   "player_id": str,              # Transfermarkt/Wikidata ID
    #   "team": str,                   # e.g., "Manchester City"
    #   "season": int,                 # e.g., 2023
    #   "league": str,                 # "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"
    #   "position": str,               # "FW", "MF", "DEF", "GK"
    #   "stat_category": str,          # "goals", "assists", "passes", "tackles", "positioning"
    #   "comparison_player": str,      # For comparative queries
    #   "match_date": str,             # ISO date (e.g., "2024-01-15")
    #   "match_id": str,               # Unique match identifier
    #   "tactical_focus": str,         # e.g., "pressing", "buildup", "transition"
    # }
    
    # === VALIDATION & DATA RETRIEVAL ===
    validation_status: str             # "PENDING", "VALID", "INVALID"
    validation_error: str              # If INVALID, reason
    
    # === SQL GENERATION & EXECUTION ===
    sql_query: str                     # Generated Postgres query
    sql_error: str                     # If query failed, error message
    sql_execution_status: str          # "PENDING", "EXECUTED", "FAILED"
    
    # === RAW DATA BUFFER ===
    raw_data: list[dict[str, Any]]    # Query results from Neon DB
    raw_data_count: int                # Row count
    match_event_data: list[dict]       # Event-level data (for tactical analysis)
    
    # === ANALYSIS & RESPONSE ===
    tactical_analysis: str             # LLM-synthesized tactical breakdown
    final_response: str                # Scout-ready scout report
    
    # === CONTROL FLOW ===
    attempt_count: int                 # Track retries (max 2)
    data_fetched: bool                 # Did we successfully fetch data?
    should_loop: bool                  # Should we re-attempt?
```

### 1.3 State Field Rationale

| Field | Purpose | Example |
|-------|---------|---------|
| `intent` | LLM classifies the query type for branch routing | "player_stats", "team_comparison", "match_breakdown" |
| `entities` | Extracted parameters guide DB queries | `{"player_name": "Trout", "season": 2023}` |
| `validation_status` | Prevents invalid queries from hitting DB | "INVALID" → short-circuit to error response |
| `sql_query` | Audit trail for performance & debugging | Logged for reproducibility |
| `raw_data_buffer` | Decouples SQL execution from analysis | Allows re-analysis if needed |
| `attempt_count` | Prevents infinite loops | Exit after 2 failed attempts |
| `should_loop` | Explicit control signal from decision node | Routes back to validation/query or exits |

---

---

## 2. Node Architecture & Edge Logic

### 2.1 Universal Node Architecture (Both Sectors)

Both Baseball and Football subgraphs share the same 4-node pattern:

```
START
  ↓
[1] Entity Extraction & Intent Classification
  ↓
[2] Validation Node (Check if player/team exists in Neon)
  ↓
[3] Text-to-SQL Node (Generate & execute query)
  ↓
[4] Decision & Routing Node (Loop or analyze or exit)
  ↓
[5] Analysis Node (Synthesize to scout report)
  ↓
END
```

---

### 2.2 Node 1: Entity Extraction & Intent Classification

**Purpose**: Parse user query into structured entities and classify intent.

**Baseball Implementation**:
```python
def baseball_extract_intent_node(state: BaseballSubState) -> dict:
    """
    Extract entities and classify intent from raw query.
    Uses LLM to parse player names, seasons, stats, comparisons.
    """
    extraction_prompt = f"""
    Analyze this baseball query: "{state['query']}"
    
    Extract these entities (use null if not found):
    - player_name: Full player name (e.g., "Mike Trout")
    - player_id: Lahman playerID format (e.g., "troutmi01") - guess if needed
    - team: MLB 3-letter code (e.g., "LAA", "NYY")
    - season: Year as integer (e.g., 2023)
    - league: "MLB", "AAA", "AA", "A", or null
    - stat_category: "batting", "pitching", "fielding", or null
    - comparison_player: If comparative query, the second player name
    - time_period: "career", "season", "month", "week", or null
    
    Classify the intent:
    - "player_career_stats"
    - "player_season_stats"
    - "player_comparison"
    - "team_roster"
    - "team_season_performance"
    - "historical_analysis"
    - "award_eligibility"
    - "injury_status"
    - "other"
    
    Respond with JSON:
    {{
        "entities": {{ ... }},
        "intent": "player_season_stats",
        "confidence": 0.95
    }}
    """
    
    response = llm.invoke([HumanMessage(content=extraction_prompt)]).content
    
    try:
        parsed = json.loads(response)
    except:
        parsed = {"entities": {}, "intent": "other", "confidence": 0}
    
    return {
        "entities": parsed.get("entities", {}),
        "intent": parsed.get("intent", "other")
    }
```

**Football Implementation**:
```python
def football_extract_intent_node(state: FootballSubState) -> dict:
    """
    Extract entities and classify intent from raw query.
    Parses player names, teams, leagues, tactical concepts.
    """
    extraction_prompt = f"""
    Analyze this football query: "{state['query']}"
    
    Extract these entities (use null if not found):
    - player_name: Full player name (e.g., "Erling Haaland")
    - player_id: Transfermarkt/Wikidata ID
    - team: Team name (e.g., "Manchester City")
    - season: Year or season (e.g., 2023, "2023-24")
    - league: "Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1"
    - position: "FW", "MF", "DEF", "GK"
    - stat_category: "goals", "assists", "passes", "tackles", "positioning"
    - comparison_player: If comparative
    - match_date: ISO date if specific match
    - tactical_focus: e.g., "pressing", "buildup", "transition", "set-pieces"
    
    Classify the intent:
    - "player_season_stats"
    - "player_comparison"
    - "team_performance"
    - "tactical_analysis"
    - "match_preview"
    - "match_review"
    - "position_analysis"
    - "injury_status"
    - "transfer_analysis"
    - "other"
    
    Respond with JSON:
    {{
        "entities": {{ ... }},
        "intent": "player_season_stats",
        "confidence": 0.92
    }}
    """
    
    response = llm.invoke([HumanMessage(content=extraction_prompt)]).content
    
    try:
        parsed = json.loads(response)
    except:
        parsed = {"entities": {}, "intent": "other"}
    
    return {
        "entities": parsed.get("entities", {}),
        "intent": parsed.get("intent", "other")
    }
```

---

### 2.3 Node 2: Validation Node

**Purpose**: Check if the requested player/team/season exists in Neon DB before querying.

**Baseball Validation Logic**:
```python
def baseball_validation_node(state: BaseballSubState) -> dict:
    """
    Validate that player/team exists in Neon.
    Short-circuits invalid queries before SQL execution.
    """
    entities = state.get("entities", {})
    player_name = entities.get("player_name")
    team = entities.get("team")
    season = entities.get("season")
    
    # If no extractable entities, mark as invalid
    if not any([player_name, team]):
        return {
            "validation_status": "INVALID",
            "validation_error": "No player or team specified. Example: 'Mike Trout 2023' or 'Yankees roster'"
        }
    
    validation_query = ""
    
    if player_name and not player_name.startswith("http"):
        # Check if player exists in People table
        validation_query = text(f"""
            SELECT player_id, name_first, name_last 
            FROM baseball_people 
            WHERE LOWER(name_first || ' ' || name_last) LIKE LOWER('%{player_name}%')
            LIMIT 5
        """)
    elif team:
        # Check if team exists
        validation_query = text(f"""
            SELECT team_id, team_name 
            FROM baseball_teams 
            WHERE UPPER(team_id) = UPPER('{team}')
            LIMIT 1
        """)
    
    if not validation_query:
        return {
            "validation_status": "INVALID",
            "validation_error": "Could not parse a valid player or team from the query"
        }
    
    try:
        with engine.connect() as conn:
            result = conn.execute(validation_query).fetchall()
        
        if result:
            return {
                "validation_status": "VALID",
                "validation_error": ""
            }
        else:
            return {
                "validation_status": "INVALID",
                "validation_error": f"Player '{player_name}' or team '{team}' not found in database"
            }
    except Exception as e:
        return {
            "validation_status": "INVALID",
            "validation_error": f"Validation check failed: {str(e)}"
        }
```

**Football Validation Logic**:
```python
def football_validation_node(state: FootballSubState) -> dict:
    """
    Validate that player/team/season exists in Neon.
    """
    entities = state.get("entities", {})
    player_name = entities.get("player_name")
    team = entities.get("team")
    season = entities.get("season")
    league = entities.get("league")
    
    if not any([player_name, team]):
        return {
            "validation_status": "INVALID",
            "validation_error": "No player or team specified. Example: 'Erling Haaland' or 'Manchester City 2024'"
        }
    
    validation_query = ""
    
    if player_name:
        # Check if player exists in Players table
        validation_query = text(f"""
            SELECT player_id, player_name, current_team 
            FROM football_players 
            WHERE LOWER(player_name) LIKE LOWER('%{player_name}%')
            LIMIT 5
        """)
    elif team:
        # Check if team exists
        validation_query = text(f"""
            SELECT team_id, team_name, league 
            FROM football_teams 
            WHERE LOWER(team_name) LIKE LOWER('%{team}%')
            AND (league = '{league}' OR '{league}' IS NULL)
            LIMIT 5
        """)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(validation_query).fetchall()
        
        if result:
            return {
                "validation_status": "VALID",
                "validation_error": ""
            }
        else:
            return {
                "validation_status": "INVALID",
                "validation_error": f"Player '{player_name}' or team '{team}' not found"
            }
    except Exception as e:
        return {
            "validation_status": "INVALID",
            "validation_error": f"Validation check failed: {str(e)}"
        }
```

---

### 2.4 Node 3: Text-to-SQL Node

**Purpose**: Generate and execute a Postgres query based on intent and entities.

**Baseball SQL Generation**:
```python
def baseball_text_to_sql_node(state: BaseballSubState) -> dict:
    """
    Generate Postgres query from intent + entities.
    Uses LLM to construct SQL, then executes and returns results.
    """
    entities = state.get("entities", {})
    intent = state.get("intent")
    
    # Check if validation passed
    if state.get("validation_status") == "INVALID":
        return {
            "sql_execution_status": "FAILED",
            "sql_error": state.get("validation_error", "Validation failed"),
            "raw_data": [],
            "raw_data_count": 0
        }
    
    sql_generation_prompt = f"""
    Generate a Postgres query for this baseball inquiry.
    
    Intent: {intent}
    Entities: {json.dumps(entities)}
    
    Available tables:
    - baseball_people (player_id, name_first, name_last, birth_date, ...)
    - baseball_batting (player_id, season, team_id, games, at_bats, hits, doubles, triples, home_runs, rbi, ...)
    - baseball_pitching (player_id, season, team_id, games, innings_pitched, wins, losses, era, strikeouts, ...)
    - baseball_fielding (player_id, season, team_id, position, games, assists, putouts, errors, ...)
    - baseball_teams (team_id, year, team_name, league, division, ...)
    
    CRITICAL RULES:
    1. Use exact column names from the schema above
    2. Filter by season = {entities.get('season', 'NULL')} if season is provided
    3. Filter by team_id = '{entities.get('team', '')}' if team is provided
    4. Return at most 100 rows (add LIMIT 100)
    5. ORDER BY most relevant metrics DESC
    6. Return ONLY the SQL query, no explanation
    
    Example query:
    SELECT player_id, season, team_id, games, hits, home_runs, rbi
    FROM baseball_batting
    WHERE season = 2023 AND team_id = 'LAA'
    ORDER BY home_runs DESC
    LIMIT 100;
    """
    
    try:
        response = llm.invoke([HumanMessage(content=sql_generation_prompt)]).content
        sql_query = response.strip()
        
        # Safety: check for dangerous operations
        if any(word in sql_query.upper() for word in ["DROP", "DELETE", "INSERT", "UPDATE"]):
            raise ValueError("Dangerous SQL operation detected")
        
        # Execute the query
        with engine.connect() as conn:
            result = conn.execute(text(sql_query)).fetchall()
        
        # Convert to list of dicts
        raw_data = [dict(row._mapping) for row in result]
        
        return {
            "sql_query": sql_query,
            "sql_execution_status": "EXECUTED",
            "raw_data": raw_data,
            "raw_data_count": len(raw_data)
        }
    
    except Exception as e:
        return {
            "sql_query": sql_query if 'sql_query' in locals() else "",
            "sql_error": str(e),
            "sql_execution_status": "FAILED",
            "raw_data": [],
            "raw_data_count": 0
        }
```

**Football SQL Generation**:
```python
def football_text_to_sql_node(state: FootballSubState) -> dict:
    """
    Generate Postgres query from intent + entities.
    """
    entities = state.get("entities", {})
    intent = state.get("intent")
    
    if state.get("validation_status") == "INVALID":
        return {
            "sql_execution_status": "FAILED",
            "sql_error": state.get("validation_error"),
            "raw_data": [],
            "raw_data_count": 0
        }
    
    sql_generation_prompt = f"""
    Generate a Postgres query for this football inquiry.
    
    Intent: {intent}
    Entities: {json.dumps(entities)}
    
    Available tables:
    - football_players (player_id, player_name, position, current_team, birth_date, nationality, ...)
    - football_player_stats (player_id, season, team_id, league, apps, goals, assists, passes, tackles, ...)
    - football_teams (team_id, team_name, league, country, manager, ...)
    - football_matches (match_id, date, home_team_id, away_team_id, home_score, away_score, ...)
    - football_events (event_id, match_id, player_id, event_type, timestamp, x_pos, y_pos, ...)
    
    CRITICAL RULES:
    1. Use exact column names from schema
    2. Filter by season = '{entities.get('season', '')}' if season provided
    3. Filter by league = '{entities.get('league', '')}' if league provided
    4. Filter by position = '{entities.get('position', '')}' if position provided
    5. Join tables as needed (e.g., football_players → football_player_stats)
    6. LIMIT 100 rows
    7. Return ONLY the SQL query, no explanation
    """
    
    try:
        response = llm.invoke([HumanMessage(content=sql_generation_prompt)]).content
        sql_query = response.strip()
        
        # Safety check
        if any(word in sql_query.upper() for word in ["DROP", "DELETE", "INSERT", "UPDATE"]):
            raise ValueError("Dangerous SQL operation detected")
        
        # Execute
        with engine.connect() as conn:
            result = conn.execute(text(sql_query)).fetchall()
        
        raw_data = [dict(row._mapping) for row in result]
        
        return {
            "sql_query": sql_query,
            "sql_execution_status": "EXECUTED",
            "raw_data": raw_data,
            "raw_data_count": len(raw_data)
        }
    
    except Exception as e:
        return {
            "sql_query": sql_query if 'sql_query' in locals() else "",
            "sql_error": str(e),
            "sql_execution_status": "FAILED",
            "raw_data": [],
            "raw_data_count": 0
        }
```

---

### 2.5 Node 4: Decision & Routing Node

**Purpose**: Decide whether to loop back (retry validation/query), proceed to analysis, or exit with error.

**Logic (Both Sectors)**:
```python
def decision_node(state: BaseballSubState) -> Literal["analyze", "loop", "error"]:
    """
    Routing logic:
    - If validation failed → "error"
    - If SQL execution failed AND attempt_count < 2 → "loop" (retry)
    - If SQL execution succeeded → "analyze"
    - If attempt_count >= 2 → "error"
    """
    validation_status = state.get("validation_status")
    sql_status = state.get("sql_execution_status")
    attempt_count = state.get("attempt_count", 0)
    
    # Validation failed → immediate error
    if validation_status == "INVALID":
        return "error"
    
    # SQL failed → check attempt count
    if sql_status == "FAILED":
        if attempt_count < 2:
            return "loop"  # Retry
        else:
            return "error"  # Max attempts reached
    
    # SQL succeeded → analyze
    if sql_status == "EXECUTED" and state.get("raw_data_count", 0) > 0:
        return "analyze"
    
    # No data returned → error
    return "error"
```

---

### 2.6 Node 5: Analysis Node

**Purpose**: Synthesize raw data into a scout-ready intelligence report.

**Baseball Analysis**:
```python
def baseball_analysis_node(state: BaseballSubState) -> dict:
    """
    Transform raw SQL results into scout-level analysis.
    """
    raw_data = state.get("raw_data", [])
    intent = state.get("intent")
    query = state.get("query")
    
    if not raw_data:
        return {
            "analysis": "No data retrieved",
            "final_response": "Unable to retrieve statistics for the requested player or team."
        }
    
    analysis_prompt = f"""
    You are a professional baseball scout and statistician.
    
    User Query: {query}
    Intent: {intent}
    Raw Data: {json.dumps(raw_data[:10])}  # First 10 rows
    
    Using the data above, provide a scout-ready analysis that:
    1. Summarizes the key statistics
    2. Identifies trends or anomalies
    3. Compares to league averages (if applicable)
    4. Provides professional assessment of the player/team
    5. Uses baseball-specific terminology
    
    Format: Professional scout report (2-3 paragraphs)
    """
    
    response = llm.invoke([HumanMessage(content=analysis_prompt)]).content
    
    return {
        "analysis": response,
        "final_response": response
    }
```

**Football Analysis**:
```python
def football_analysis_node(state: FootballSubState) -> dict:
    """
    Transform raw SQL results into tactical/performance analysis.
    """
    raw_data = state.get("raw_data", [])
    intent = state.get("intent")
    query = state.get("query")
    
    if not raw_data:
        return {
            "tactical_analysis": "No data retrieved",
            "final_response": "Unable to retrieve data for the requested analysis."
        }
    
    analysis_prompt = f"""
    You are a professional football (soccer) scout and tactical analyst.
    
    User Query: {query}
    Intent: {intent}
    Raw Data: {json.dumps(raw_data[:10])}
    
    Provide a scout-ready analysis that:
    1. Summarizes key performance metrics
    2. Identifies tactical patterns or strengths/weaknesses
    3. Compares to league or positional standards
    4. Assesses player/team potential or form
    5. Uses football-specific terminology (positioning, pressing, buildup, transitions, etc.)
    
    Format: Professional scout report (2-3 paragraphs)
    """
    
    response = llm.invoke([HumanMessage(content=analysis_prompt)]).content
    
    return {
        "tactical_analysis": response,
        "final_response": response
    }
```

---

### 2.7 Graph Conditional Edges

**Baseball & Football Graph Assembly**:
```python
builder = StateGraph(BaseballSubState)  # or FootballSubState

# Add nodes
builder.add_node("extract", baseball_extract_intent_node)
builder.add_node("validate", baseball_validation_node)
builder.add_node("query", baseball_text_to_sql_node)
builder.add_node("decide", decision_node)
builder.add_node("analyze", baseball_analysis_node)

# Linear edges
builder.add_edge(START, "extract")
builder.add_edge("extract", "validate")
builder.add_edge("validate", "query")
builder.add_edge("query", "decide")
builder.add_edge("analyze", END)

# Conditional edges (agentic routing)
builder.add_conditional_edges(
    "decide",
    lambda state: "error" if state.get("validation_status") == "INVALID" else
                  "loop" if state.get("sql_execution_status") == "FAILED" and state.get("attempt_count", 0) < 2 else
                  "analyze" if state.get("raw_data_count", 0) > 0 else
                  "error",
    {
        "analyze": "analyze",
        "loop": "query",      # Retry query node
        "error": END          # Exit with error handling
    }
)

# Loop increment
def increment_attempt(state):
    return {"attempt_count": state.get("attempt_count", 0) + 1}

# Before looping back, increment attempt counter
builder.add_node("increment", increment_attempt)
builder.add_edge("decide", "increment")
builder.add_conditional_edges(
    "increment",
    lambda state: "query" if state.get("should_loop") else "error",
    {"query": "query", "error": END}
)

graph = builder.compile()
```

---

---

## 3. Data Ingestion Roadmap

### 3.1 Baseball Data: Lahman Historical Database

**Source**: Lahman Baseball Database (GitHub: `chadwickbureau/baseballdatabank`)

**ETL Pipeline**:

```
Step 1: EXTRACT
  └─ Clone Lahman repo
  └─ Read CSV files (People, Batting, Pitching, Fielding, Teams, etc.)
  └─ Load into pandas DataFrames

Step 2: TRANSFORM
  └─ Standardize column names (snake_case)
  └─ Handle missing values (NaN → NULL)
  └─ Validate data types (season as int, etc.)
  └─ Enrich with calculated metrics (batting average, ERA, etc.)
  └─ Merge related tables (People + Batting + Teams)

Step 3: LOAD
  └─ Create Neon Cloud schemas
  └─ Load DataFrames to Neon using SQLAlchemy
  └─ Create indexes on frequently queried columns
  └─ Validate row counts
```

**Neon Schema for Baseball**:

```sql
-- Core Tables
CREATE TABLE baseball_people (
    player_id VARCHAR(9) PRIMARY KEY,
    name_first VARCHAR(255),
    name_last VARCHAR(255),
    birth_date DATE,
    death_date DATE,
    birth_city VARCHAR(255),
    birth_country VARCHAR(100),
    weight INTEGER,
    height INTEGER,
    bats CHAR(1),
    throws CHAR(1)
);

CREATE TABLE baseball_teams (
    team_id VARCHAR(3),
    year INTEGER,
    team_name VARCHAR(255),
    league VARCHAR(2),
    division VARCHAR(3),
    rank INTEGER,
    games_played INTEGER,
    wins INTEGER,
    losses INTEGER,
    PRIMARY KEY (team_id, year)
);

CREATE TABLE baseball_batting (
    player_id VARCHAR(9),
    season INTEGER,
    team_id VARCHAR(3),
    league VARCHAR(2),
    games INTEGER,
    at_bats INTEGER,
    runs INTEGER,
    hits INTEGER,
    doubles INTEGER,
    triples INTEGER,
    home_runs INTEGER,
    rbi INTEGER,
    stolen_bases INTEGER,
    caught_stealing INTEGER,
    walks INTEGER,
    strikeouts INTEGER,
    avg DECIMAL(5,3),
    obp DECIMAL(5,3),
    slg DECIMAL(5,3),
    ops DECIMAL(6,3),
    PRIMARY KEY (player_id, season, team_id),
    FOREIGN KEY (player_id) REFERENCES baseball_people(player_id),
    FOREIGN KEY (team_id) REFERENCES baseball_teams(team_id)
);

CREATE TABLE baseball_pitching (
    player_id VARCHAR(9),
    season INTEGER,
    team_id VARCHAR(3),
    league VARCHAR(2),
    games INTEGER,
    innings_pitched DECIMAL(6,1),
    wins INTEGER,
    losses INTEGER,
    games_started INTEGER,
    saves INTEGER,
    earned_runs INTEGER,
    era DECIMAL(5,2),
    strikeouts INTEGER,
    walks INTEGER,
    home_runs_allowed INTEGER,
    PRIMARY KEY (player_id, season, team_id),
    FOREIGN KEY (player_id) REFERENCES baseball_people(player_id)
);

CREATE TABLE baseball_fielding (
    player_id VARCHAR(9),
    season INTEGER,
    team_id VARCHAR(3),
    position VARCHAR(2),
    games INTEGER,
    games_started INTEGER,
    innings_played DECIMAL(6,1),
    putouts INTEGER,
    assists INTEGER,
    errors INTEGER,
    double_plays INTEGER,
    PRIMARY KEY (player_id, season, team_id, position),
    FOREIGN KEY (player_id) REFERENCES baseball_people(player_id)
);

-- Create indexes for query performance
CREATE INDEX idx_baseball_people_name ON baseball_people(name_last, name_first);
CREATE INDEX idx_baseball_batting_player_season ON baseball_batting(player_id, season);
CREATE INDEX idx_baseball_batting_team_year ON baseball_batting(team_id, season);
CREATE INDEX idx_baseball_pitching_player_season ON baseball_pitching(player_id, season);
```

**Python ETL Script**:

```python
import pandas as pd
from sqlalchemy import create_engine, text
import os

# 1. Clone Lahman repo (one-time)
os.system("git clone https://github.com/chadwickbureau/baseballdatabank.git lahman_db")

# 2. Load CSVs
people_df = pd.read_csv("lahman_db/core/People.csv")
batting_df = pd.read_csv("lahman_db/core/Batting.csv")
pitching_df = pd.read_csv("lahman_db/core/Pitching.csv")
fielding_df = pd.read_csv("lahman_db/core/Fielding.csv")
teams_df = pd.read_csv("lahman_db/core/Teams.csv")

# 3. Transform
# Rename columns to snake_case
people_df.columns = people_df.columns.str.lower()
batting_df.columns = batting_df.columns.str.lower()
# ... etc

# 4. Load to Neon
engine = create_engine(os.getenv("DATABASE_URL"))

people_df.to_sql("baseball_people", engine, if_exists="append", index=False)
batting_df.to_sql("baseball_batting", engine, if_exists="append", index=False)
pitching_df.to_sql("baseball_pitching", engine, if_exists="append", index=False)
# ... etc

print("✅ Lahman Baseball Database loaded to Neon")
```

---

### 3.2 Football Data: Soccer GitHub Datasets

**Sources**:
- `statsbomb/statsbomb-data` (match events, lineups)
- `davidcaribou/match-data` (historical match results)
- `JaseZiv/Understat-Data` (xG, xA, shot maps)

**ETL Pipeline**:

```
Step 1: EXTRACT
  └─ Fetch JSON files from GitHub or APIs
  └─ Parse nested structures (match events, player positions)
  └─ Load into pandas

Step 2: TRANSFORM
  └─ Flatten nested JSON (events → individual rows)
  └─ Standardize player names (fuzzy matching)
  └─ Map team names to IDs
  └─ Calculate derived metrics (pass completion %, xG per 90, etc.)
  └─ Handle multi-league data (PL, La Liga, Serie A, etc.)

Step 3: LOAD
  └─ Create Neon Cloud schemas
  └─ Load tables with appropriate relationships
  └─ Index frequently filtered columns
```

**Neon Schema for Football**:

```sql
CREATE TABLE football_players (
    player_id VARCHAR(50) PRIMARY KEY,
    player_name VARCHAR(255),
    birth_date DATE,
    nationality VARCHAR(100),
    height_cm DECIMAL(5,1),
    weight_kg DECIMAL(5,1)
);

CREATE TABLE football_teams (
    team_id VARCHAR(50) PRIMARY KEY,
    team_name VARCHAR(255),
    country VARCHAR(100),
    league VARCHAR(100),
    manager_name VARCHAR(255)
);

CREATE TABLE football_player_stats (
    id SERIAL PRIMARY KEY,
    player_id VARCHAR(50),
    season INTEGER,
    team_id VARCHAR(50),
    league VARCHAR(100),
    position VARCHAR(3),
    apps INTEGER,
    apps_starts INTEGER,
    minutes_played INTEGER,
    goals INTEGER,
    assists INTEGER,
    pass_completion DECIMAL(5,2),
    tackles_per_90 DECIMAL(5,2),
    interceptions_per_90 DECIMAL(5,2),
    xg DECIMAL(5,2),
    xa DECIMAL(5,2),
    FOREIGN KEY (player_id) REFERENCES football_players(player_id),
    FOREIGN KEY (team_id) REFERENCES football_teams(team_id)
);

CREATE TABLE football_matches (
    match_id VARCHAR(50) PRIMARY KEY,
    match_date DATE,
    season INTEGER,
    league VARCHAR(100),
    home_team_id VARCHAR(50),
    away_team_id VARCHAR(50),
    home_score INTEGER,
    away_score INTEGER,
    status VARCHAR(50),
    FOREIGN KEY (home_team_id) REFERENCES football_teams(team_id),
    FOREIGN KEY (away_team_id) REFERENCES football_teams(team_id)
);

CREATE TABLE football_events (
    event_id BIGSERIAL PRIMARY KEY,
    match_id VARCHAR(50),
    player_id VARCHAR(50),
    event_type VARCHAR(50),
    timestamp_ms INTEGER,
    x_pos DECIMAL(5,2),
    y_pos DECIMAL(5,2),
    outcome VARCHAR(50),
    success BOOLEAN,
    FOREIGN KEY (match_id) REFERENCES football_matches(match_id),
    FOREIGN KEY (player_id) REFERENCES football_players(player_id)
);

-- Indexes
CREATE INDEX idx_football_player_stats_season ON football_player_stats(player_id, season);
CREATE INDEX idx_football_player_stats_league ON football_player_stats(league, season);
CREATE INDEX idx_football_events_match ON football_events(match_id);
```

**Python ETL Script**:

```python
import requests
import json
import pandas as pd
from sqlalchemy import create_engine

# Fetch StatsBomb data
url = "https://raw.githubusercontent.com/statsbomb/statsbomb-data/master/data/"

# Load matches and events
matches = requests.get(url + "matches.json").json()
events = requests.get(url + "events.json").json()

# Flatten events structure
events_flat = []
for event_list in events:
    for event in event_list:
        events_flat.append({
            "match_id": event.get("match_id"),
            "player_id": event.get("player", {}).get("id"),
            "player_name": event.get("player", {}).get("name"),
            "event_type": event.get("type", {}).get("name"),
            "timestamp": event.get("timestamp"),
            "x": event.get("location", [None])[0],
            "y": event.get("location", [None])[1],
            "success": event.get("pass", {}).get("outcome") is None if "pass" in event else None
        })

events_df = pd.DataFrame(events_flat)

# Load to Neon
engine = create_engine(os.getenv("DATABASE_URL"))
events_df.to_sql("football_events", engine, if_exists="append", index=False)

print("✅ StatsBomb data loaded to Neon")
```

---

### 3.3 Data Sync Strategy

**Frequency**:
- **Baseball**: Monthly (historical data updates quarterly, live standings daily)
- **Football**: Weekly (match events, player stats after fixtures)

**Incremental vs. Full**:
- Baseball: Full reload annually (Lahman updates once/year post-season)
- Football: Incremental (append new matches/seasons, update current season stats)

**Scheduling**:
```python
# In backend.py or celery_tasks.py

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

# Baseball: Monthly full reload
scheduler.add_job(
    func=etl_baseball_lahman,
    trigger="cron",
    day=1,  # 1st of month
    hour=2,
    minute=0,
    id="baseball_sync"
)

# Football: Weekly update (every Monday)
scheduler.add_job(
    func=etl_football_weekly,
    trigger="cron",
    day_of_week="mon",
    hour=3,
    minute=0,
    id="football_sync"
)

scheduler.start()
```

---

---

## 4. System Architecture Diagram

### 4.1 Full System Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                       │
│                          TWG SPORTS INTELLIGENCE PLATFORM                            │
│                                                                                       │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                       │
│  ┌──────────────────────┐                                                           │
│  │   FRONTEND LAYER     │                                                           │
│  │                      │                                                           │
│  │  • Streamlit UI      │  ← User queries (natural language)                        │
│  │  • Chat interface    │                                                           │
│  │  • Report viewer     │                                                           │
│  └──────────┬───────────┘                                                           │
│             │                                                                        │
│             │ HTTP POST /chat                                                       │
│             │ {"query": "Who won the 2024 World Series?"}                          │
│             ▼                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐              │
│  │               FASTAPI BACKEND (main.py)                          │              │
│  │                                                                  │              │
│  │  ┌───────────────────────────────────────────────────────────┐  │              │
│  │  │      Supervisor Router (LLM-Based Intent Router)          │  │              │
│  │  │                                                           │  │              │
│  │  │  Query: "Who won the 2024 World Series?"                 │  │              │
│  │  │    ↓                                                      │  │              │
│  │  │  router_llm: "This is about baseball"                    │  │              │
│  │  │    ↓                                                      │  │              │
│  │  │  Route decision: "baseball_sector"                       │  │              │
│  │  │    ↓                                                      │  │              │
│  │  │  Conditional edge: Send to baseball_subgraph             │  │              │
│  │  └───────────────────────────────────────────────────────────┘  │              │
│  │                    │         │         │                         │              │
│  │     ┌──────────────┘         │         └────────────┐            │              │
│  │     ▼                        ▼                      ▼            │              │
│  │ ┌─────────┐         ┌──────────────┐       ┌──────────────┐     │              │
│  │ │   F1    │         │  BASEBALL    │       │  FOOTBALL    │     │              │
│  │ │Subgraph │         │  Subgraph    │       │  Subgraph    │     │              │
│  │ │(Legacy) │         │ (New)        │       │  (New)       │     │              │
│  │ └────┬────┘         └──────┬───────┘       └──────┬───────┘     │              │
│  │      │                     │                      │             │              │
│  └──────┼─────────────────────┼──────────────────────┼─────────────┘              │
│         │                     │                      │                             │
│         └─────────────────────┼──────────────────────┘                             │
│                               │                                                    │
│                               │ Subgraph execution (LangGraph)                    │
│                               ▼                                                    │
│         ┌───────────────────────────────────────────────────────────┐             │
│         │        LANGGRAPH SUBGRAPH EXECUTION                       │             │
│         │                                                           │             │
│         │  START                                                   │             │
│         │    ↓                                                     │             │
│         │  [1] Extract Intent & Entities                          │             │
│         │    ↓                                                     │             │
│         │  [2] Validation Node (check if player exists)           │             │
│         │    ↓                                                     │             │
│         │  [3] Text-to-SQL Node (generate & execute query)        │             │
│         │    ↓                                                     │             │
│         │  [4] Decision Node (loop, analyze, or exit)             │             │
│         │    ↓                                                     │             │
│         │  [5] Analysis Node (synthesize to scout report)         │             │
│         │    ↓                                                     │             │
│         │  END                                                    │             │
│         └───────────────────────────────────────────────────────────┘             │
│                               │                                                    │
│                               │ SQL queries                                       │
│                               ▼                                                    │
│         ┌───────────────────────────────────────────────────────────┐             │
│         │          NEON CLOUD POSTGRESQL DATABASE                  │             │
│         │                                                           │             │
│         │  Baseball Schema:                                        │             │
│         │  ├─ baseball_people (players)                            │             │
│         │  ├─ baseball_batting (stats)                             │             │
│         │  ├─ baseball_pitching (pitcher stats)                    │             │
│         │  ├─ baseball_fielding (fielding stats)                   │             │
│         │  └─ baseball_teams (team info)                           │             │
│         │                                                           │             │
│         │  Football Schema:                                        │             │
│         │  ├─ football_players (players)                           │             │
│         │  ├─ football_teams (team info)                           │             │
│         │  ├─ football_player_stats (season stats)                 │             │
│         │  ├─ football_matches (match records)                     │             │
│         │  └─ football_events (event-level data)                   │             │
│         │                                                           │             │
│         │  F1 Schema: (existing)                                   │             │
│         │  └─ f1_telemetry (lap data)                              │             │
│         └───────────────────────────────────────────────────────────┘             │
│                               ▲                                                    │
│                               │                                                    │
│                    ┌──────────┴──────────┐                                        │
│                    │                     │                                        │
│             ETL Pipelines         Data Sync Scheduler                             │
│             (GitHub, APIs)        (APScheduler)                                   │
│                                                                                    │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Subgraph Internal Architecture (Repeating Pattern)

```
Baseball/Football Subgraph:
═════════════════════════════════════════════════════════════

    START
      │
      ▼
    [1] extract_intent_node
      │  Input: query (natural language)
      │  Output: entities (dict), intent (str)
      │
      ▼
    [2] validation_node
      │  Input: entities
      │  Output: validation_status ("VALID" | "INVALID")
      │          ↓
      │      ┌───┴────────────────────────────────┐
      │      │ If INVALID → Direct to error exit  │
      │      └───────────────────────────────────┘
      │
      ▼
    [3] text_to_sql_node
      │  Input: intent, entities
      │  Output: sql_query, raw_data (from Neon DB)
      │
      ▼
    [4] decision_node (AGENTIC ROUTING)
      │
      │  Routing Logic:
      │  ├─ If validation_status == "INVALID" → END
      │  ├─ If sql_execution_status == "FAILED" AND attempt_count < 2 → LOOP back to [3]
      │  ├─ If raw_data_count > 0 → Continue to [5] (analyze)
      │  └─ Else → END with error
      │
      ├─────────────────┬──────────────────┬──────────┐
      │                 │                  │          │
      │ (loop)          │                  │ (error)  │
      │                 │                  │          │
      ▼                 ▼                  ▼          │
    [3b] Increment  [5] analysis_node   ERROR        │
      │  attempt_  │  Input: raw_data   NODE        │
      │  counter   │  Output: final_   └─────────┐   │
      │  & retry   │  response           │       │   │
      │            │                      │       │   │
      └────────────┘                      │       │   │
                                          ▼       ▼   ▼
                                         END

Decision Node: "brain" of the subgraph
  - Inspects state
  - Makes routing decision (no hardcoded logic)
  - Enables autonomous data fetching or graceful degradation
```

---

---

## 5. Cross-Sector Query Execution

### 5.1 Multi-Sector Queries

**Definition**: User asks a question that requires data from multiple sports sectors.

**Example Queries**:
- "Compare the mental toughness of F1 drivers vs. baseball pitchers under pressure"
- "Which football (soccer) player has stats comparable to Mike Trout's dominance?"
- "How do pit stop times in F1 compare to baseball manager decision-making speed?"

### 5.2 Cross-Sector Execution Flow

```
User Query: "Compare the reaction times of F1 drivers to baseball hitters"
        │
        ▼
   supervisor_router
        │
        ├─ Detects multi-sector intent
        │
        ▼
   create_parallel_subgraphs()
        │
        ├─ Spawn baseball_subgraph (extract reaction time stats)
        ├─ Spawn f1_subgraph (extract reaction time telemetry)
        │
        ▼
   parallel_execution (concurrent)
        │
        ├─ Baseball: "Batter reaction times in hitting zone"
        ├─ F1: "Driver brake reaction times in emergency braking"
        │
        ▼
   synthesis_node (aggregate results)
        │
        ├─ Combine both sector analyses
        ├─ Cross-reference metrics
        ├─ Synthesize comparative report
        │
        ▼
   final_response (unified scout report)
```

### 5.3 Implementation

**Router Modification** (in `main.py`):

```python
def supervisor_router(state: AgentState) -> str:
    """
    Enhanced router that detects multi-sector queries.
    """
    router_prompt = f"""
    Analyze this sports query: "{state['query']}"
    
    Determine if this is:
    1. Single-sector: "f1_sector", "baseball_sector", "football_sector"
    2. Multi-sector: "multi_sector"
    
    If multi-sector, which sectors?
    
    Respond with JSON:
    {{
        "primary_sector": "f1_sector",
        "secondary_sectors": ["baseball_sector"],
        "is_multi": true
    }}
    """
    
    response = llm.invoke([HumanMessage(content=router_prompt)]).content
    parsed = json.loads(response)
    
    if parsed["is_multi"]:
        return "multi_sector"  # Routes to multi-sector handler
    else:
        return parsed["primary_sector"]
```

**Multi-Sector Node** (in `main.py`):

```python
def multi_sector_handler(state: AgentState):
    """
    Routes query to multiple subgraphs concurrently.
    """
    sectors_to_query = state.get("sectors", ["f1_sector", "baseball_sector"])
    
    # Create subgraph instances for each sector
    subgraphs = {
        "f1_sector": f1_sector_graph,
        "baseball_sector": baseball_sector_graph,
        "football_sector": football_sector_graph
    }
    
    # Run in parallel using asyncio or concurrent.futures
    results = {}
    for sector in sectors_to_query:
        subgraph = subgraphs[sector]
        initial_state = {
            "query": state["query"],
            "entities": {},
            "final_response": ""
        }
        results[sector] = subgraph.invoke(initial_state)
    
    # Aggregate results
    aggregated_response = synthesis_node({
        "f1_result": results.get("f1_sector", {}).get("final_response"),
        "baseball_result": results.get("baseball_sector", {}).get("final_response"),
        "football_result": results.get("football_sector", {}).get("final_response")
    })
    
    return {
        "final_response": aggregated_response,
        "multi_sector_results": results
    }

def synthesis_node(results: dict) -> str:
    """
    Synthesize multiple sector analyses into unified report.
    """
    synthesis_prompt = f"""
    You are a cross-sport analysis expert.
    
    Sector Results:
    - F1: {results.get("f1_result")}
    - Baseball: {results.get("baseball_result")}
    - Football: {results.get("football_result")}
    
    Synthesize these into a unified comparative analysis.
    Highlight similarities, differences, and insights.
    """
    
    response = llm.invoke([HumanMessage(content=synthesis_prompt)]).content
    return response
```

**Graph Update** (in `main.py`):

```python
# Add multi-sector handling
builder.add_node("multi_sector", multi_sector_handler)

builder.add_conditional_edges(
    START,
    supervisor_router,
    {
        "f1_sector": "f1_sector",
        "baseball_sector": "baseball_sector",
        "football_sector": "football_sector",
        "multi_sector": "multi_sector"
    }
)

# Multi-sector routes to END directly
builder.add_edge("multi_sector", END)
```

---

---

## 6. Deployment Checklist

### 6.1 Pre-Deployment

- [ ] **Database**: Neon PostgreSQL cluster provisioned
  - [ ] Baseball schema created
  - [ ] Football schema created
  - [ ] Lahman data loaded
  - [ ] Soccer GitHub data loaded
  - [ ] Indexes created for performance

- [ ] **LangGraph**: Subgraph implementations complete
  - [ ] Baseball subgraph tested locally
  - [ ] Football subgraph tested locally
  - [ ] Cross-sector routing tested

- [ ] **FastAPI**: Backend updated
  - [ ] Multi-sector router implemented
  - [ ] Error handling for each sector
  - [ ] Rate limiting configured

- [ ] **Frontend**: Streamlit app ready
  - [ ] Chat interface tested
  - [ ] Multi-sector query UI

### 6.2 Deployment

```bash
# 1. Set environment variables
export DATABASE_URL="postgresql://user:pass@neon.tech/twg_db"
export GROQ_API_KEY="your_api_key"

# 2. Start FastAPI backend
uvicorn backend:app --host 0.0.0.0 --port 8000 &

# 3. Start ETL scheduler (for data sync)
python etl_scheduler.py &

# 4. Start Streamlit frontend
streamlit run frontend.py --server.port 8501

# 5. Run test suite
python test_baseball_agent.py
python test_football_agent.py
python test_cross_sector_queries.py
```

### 6.3 Monitoring

- [ ] Set up logging (AWS CloudWatch or similar)
- [ ] Monitor Neon DB query performance (slow query logs)
- [ ] Track LLM token usage (Groq API)
- [ ] Monitor ETL job completion
- [ ] Set up alerts for failed queries

---

---

## Appendix: Scout-Ready Language Guide

### Baseball Scout Terminology

| Term | Definition | Example |
|------|-----------|---------|
| **Whiff** | Strikeout | "Low chase rate, only 10 whiffs in 400 ABs" |
| **Exit Velo** | Ball exit velocity off bat | "Elite 92+ mph exit velo" |
| **Barrel** | Sweet spot contact (high exit velo + launch angle) | "45% barrels, elite contact quality" |
| **Approach** | Batting discipline / plate discipline | "Selective approach, waits for fastballs" |
| **Stuff** | Pitcher's pitch quality | "Plus fastball, average slider" |
| **Command** | Pitcher's ability to place pitches | "Good command in the zone" |
| **Filthy** | Excellent pitch movement | "Filthy curveball" |
| **RPM** | Revolutions per minute (spin rate) | "2400 RPM fastball" |
| **IVB** | Induced vertical break (movement on pitch) | "Plus 18 IVB on fastball" |

### Football Scout Terminology

| Term | Definition | Example |
|------|-----------|---------|
| **Positioning** | Off-the-ball awareness and spatial awareness | "Elite positioning prevents turnovers" |
| **Pressing** | Aggressive ball recovery / closing down | "Intense 5-second pressing trigger" |
| **Distribution** | Ball-playing ability (passing out from back) | "Excellent distribution, 92% pass completion" |
| **Ball Progression** | Advancing the ball upfield | "Drives forward with 3+ progressive passes/90" |
| **Defensive Stability** | Tackle + interception rate | "2.1 tackles + interceptions per 90" |
| **xG** | Expected Goals (quality of shot opportunities) | "0.35 xG per 90" |
| **xA** | Expected Assists (quality of key passes) | "0.18 xA per 90" |
| **Pressing Intensity** | How aggressive the press / distance to ball carrier | "Presses within 5m, 70% success rate" |
| **Transition** | Speed of attacking/defending transition | "Fast transitions, 0.5s to shot" |
| **Physicality** | Strength, speed, agility | "Physical 6'1", mobile for position" |

---

**End of Document**

---

## Next Steps

1. **Review & Approve**: Engineering team reviews this specification
2. **Database Setup**: Provision Neon schemas, run ETL pipelines
3. **Implement Baseball**: Build `baseball_agent.py` following node templates
4. **Implement Football**: Build `football_agent.py` following node templates
5. **Integration Testing**: Test baseball + football subgraphs against main router
6. **Cross-Sector Testing**: Validate multi-sector query execution
7. **Deployment**: Roll out to staging, then production

---

**Questions or Clarifications?**
Contact: TWG Engineering Team
