# Architecture Update: Multi-Agent Sports Intelligence Platform
## LLM-Based Routing + Agentic F1 Subgraph Refactor

**Date**: 2026-04-01  
**Version**: 2.0  
**Status**: Ready for Testing  

---

## Executive Summary

This document records the complete refactoring of the TWG multi-agent sports intelligence platform. Two critical architectural upgrades were implemented:

1. **Main Router (`main.py`)**: Migrated from fragile keyword-matching to LLM-powered intent classification with structured output parsing.
2. **F1 Subgraph (`f1_agent.py`)**: Transformed from linear procedural execution to a true agentic cyclic routing pattern with state-driven decision making.

These changes enable the system to handle conversational queries gracefully, implement autonomous data-fetching decisions, and prevent infinite loops through explicit state tracking.

---

## File 1: `main.py` - Router Refactor

### 1.1 Architectural Shift

**Problem**: The original router used basic substring matching on the query ("if 'f1' in query"), which fails to understand user intent when phrased conversationally.
- Example failure: "Tell me about Lewis Hamilton's fastest lap" → Keyword `"f1"` missing, router misclassifies.

**Solution**: Implemented LLM-based intent classification using a lightweight, fast model (Mixtral) with deterministic output parsing.
- The LLM explicitly understands domain semantics (F1 teams, soccer goals, baseball home runs).
- Structured output parsing ensures the response is always a valid sector name.
- Graceful fallback to `DEFAULT_SECTOR` prevents routing failures.

**Why Now**: As the platform grows to support more sports sectors, keyword matching becomes unmaintainable. LLM routing scales linearly with new sectors (just update the system prompt).

---

### 1.2 Technical Delta

#### **Model & Configuration**
```python
# BEFORE
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.3)

# AFTER
router_llm = ChatGroq(model="mixtral-8x7b-32768", temperature=0)
```
- **Why Mixtral**: 8x7B MoE model is faster than 120B for routing decisions, suitable for real-time classification.
- **temperature=0**: Ensures deterministic outputs (no random variations in routing).

#### **New Constants**
```python
VALID_SECTORS = ["f1_sector", "soccer_sector", "baseball_sector"]
DEFAULT_SECTOR = "f1_sector"  # Fallback for ambiguous/off-topic queries
```

#### **New Function: `parse_router_response()`**
```python
def parse_router_response(response_text: str) -> str:
    """
    Robust output parsing with fallback.
    1. Try JSON parsing: {"sector": "f1_sector"}
    2. Fall back to direct string matching
    3. Return DEFAULT_SECTOR if all else fails
    """
```
- Handles LLM hallucinations gracefully.
- Logs warnings when fallback is used.
- Ensures `supervisor_router()` always returns a valid sector.

#### **Refactored Function: `supervisor_router()`**
```python
# BEFORE: substring matching + validation
for sector in valid_sectors:
    if sector in response:
        return sector

# AFTER: structured LLM call + parsing
response = router_llm.invoke([HumanMessage(...)]).content
sector = parse_router_response(response)
return sector
```

#### **System Prompt Evolution**
```python
# BEFORE: Simple one-liner instructions
"Respond with ONLY the string of the sector name. No preamble or explanation."

# AFTER: Detailed routing definitions
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
```
- Explicit keywords for each sector help the LLM make better decisions.
- Dual output format support (JSON or plain text) increases robustness.

#### **Error Handling**
```python
# ADDED: Try-except wrapper with logging
try:
    response = router_llm.invoke([HumanMessage(...)])
    sector = parse_router_response(response)
    logger.info(f"Query: '{user_query}' → Routed to: {sector}")
    return sector
except Exception as e:
    logger.error(f"Router LLM call failed: {e}. Using default sector: {DEFAULT_SECTOR}")
    return DEFAULT_SECTOR
```

#### **Imports Added**
```python
import json           # For structured output parsing
import logging        # For error tracking
```

#### **Functions Removed**
- Old hardcoded keyword-matching commented code is removed (lines 42–51 in original).

---

### 1.3 Data Flow Impact

#### **Query Path**
```
User Query: "How did Hamilton perform in the 2023 Monaco race?"
    ↓
router_llm.invoke([
    HumanMessage(system_prompt + user_prompt)
])
    ↓
Response: "f1_sector" (JSON or plain text)
    ↓
parse_router_response() → Validates & extracts sector
    ↓
supervisor_router() returns: "f1_sector"
    ↓
conditional_edges routes to f1_sector node
```

#### **State Propagation**
```python
# State at START → supervisor_router → Conditional Edges
state = {
    "messages": [],
    "query": user_query,          # ← Used by router_llm
    "user_role": "admin",
    "domain_detected": "",
    "final_response": ""
}

# After routing decision:
# → directed to f1_sector node
# → f1_sector node receives full state unchanged
```

#### **LLM Call Frequency**
- **Before**: 1 LLM call per query (extraction) + basic string matching.
- **After**: 1 LLM call per query (routing + extraction split by architecture).
- **Cost**: Minimal—Mixtral is faster than 120B model.

#### **Fallback Behavior**
- If router fails (API error, parse error): Returns `DEFAULT_SECTOR` ("f1_sector").
- Query still processes, no request dropped.

---

### 1.4 Deployment / Next Steps

#### **Dependencies**
No new pip packages required. Your existing setup includes:
```bash
langchain-groq
langchain-core
langgraph
```

#### **Environment Variables**
No changes required to `.env`. Existing `GROQ_API_KEY` is used.

#### **Running the Updated Router**
```bash
# No schema changes, no database updates required
python main.py

# Expected output:
# >>> QUERY: Which team was lewis hamilton part of in 2022?
# >>> ROUTING TO: f1_sector
# --- Node 'f1_sector' Finished ---
```

#### **Testing New Router**
```python
# Test conversational phrasing:
test_queries = [
    "Tell me about Lewis Hamilton's 2023 season",  # Should route to f1_sector
    "Who scored the most goals?",                   # Should route to soccer_sector
    "What's the weather today?",                    # Should default to f1_sector
]

for q in test_queries:
    run_sports_ai(q)
```

#### **Monitoring**
- Check logs for `logger.warning()` entries (fallback activations).
- Monitor `GROQ_API_KEY` rate limits (Mixtral is lightweight).

---

---

## File 2: `f1_agent.py` - Agentic Subgraph Refactor

### 2.1 Architectural Shift

**Problem**: The original F1 agent was a linear, procedural pipeline:
```
extract → check_db → [if missing: sync_api] → query_sql → respond
```
- All orchestration was hardcoded in the `f1_node` function.
- No true decision-making by the agent; just sequential steps.
- No loop-back capability if data was fresh-synced.

**Solution**: Implemented a **cyclic agentic subgraph** with explicit state-driven routing:
```
extract → query_db ↘
             ↓      ↘
           decide ← fetch (loop back)
           ↙  ↓  ↘
      query fetch end
         ↓   ↓    ↓
      [LOOP]  finalize → END
```

**Why Now**: This enables true autonomy—the LLM agent recognizes missing data and invokes fetch, then re-queries. Prevents hardcoded orchestration from becoming a bottleneck as the platform grows.

**Theoretical Benefit**: LLM-as-orchestrator can make better contextual decisions (e.g., "should I retry with a different session type?") without code changes.

---

### 2.2 Technical Delta

#### **State Definition: Expanded F1SubState**
```python
# BEFORE
class F1SubState(TypedDict):
    query: str
    entities: dict[str, Any]
    final_response: str

# AFTER
class F1SubState(TypedDict):
    query: str
    entities: dict[str, Any]
    final_response: str
    db_query_result: str  # ← Tracks SQL results for decision logic
    fetch_attempts: int   # ← Counter to prevent infinite loops
    data_synced: bool     # ← Flag to trigger loop-back to query
```

**Why Each Field**:
- `db_query_result`: Allows decision node to inspect SQL output without re-running the query.
- `fetch_attempts`: Prevents infinite loops (max 2 attempts before exit).
- `data_synced`: Boolean signal for the decision node to loop back.

#### **New Tool: `@tool sync_telemetry_tool()`**
```python
@tool
def sync_telemetry_tool(year: int, location: str, session_type: str = "R") -> str:
    """
    LangChain-compatible tool wrapper for sync_telemetry_to_neon().
    Returns: Success/failure message string.
    """
    return sync_telemetry_to_neon(year, location, session_type)
```
- Wraps existing `sync_telemetry_to_neon()` function.
- Makes it callable by LLM agents (though currently only used by node, not LLM directly).
- Future-proofs for agent-driven sync decisions.

#### **Functions: Refactored Nodes**

##### **Node 1: `f1_extract_node()` (Unchanged Core Logic, Expanded Output)**
```python
# BEFORE: Returns only {"entities": ...}
# AFTER: Returns {"entities": ..., "fetch_attempts": 0, "data_synced": False}
```
- Initializes new state fields.
- Clearer extraction prompt with JSON schema example.

##### **Node 2: `f1_query_db_node()` (Previously Part of Sync Node)**
```python
def f1_query_db_node(state: F1SubState) -> dict:
    """NEW NODE: Pure database query with no orchestration."""
    # 1. Extract entities from state
    # 2. Build SQL agent prompt with instruction:
    #    "If the table returns NO results, report 'NO_DATA_IN_DB'"
    # 3. Invoke f1_sql_executor
    # 4. Return {"db_query_result": result}
```
- **Key Change**: LLM explicitly instructed to return `"NO_DATA_IN_DB"` if empty.
- **Why Separate**: Decouples querying from fetch logic; enables re-querying after sync.

##### **Node 3: `f1_fetch_api_node()` (Entirely New)**
```python
def f1_fetch_api_node(state: F1SubState) -> dict:
    """
    NEW NODE: Fetch from FastF1 API and sync to Neon.
    Only invoked when query_db_node detects missing data.
    
    Safeguards:
    - Max 2 fetch attempts (prevents infinite retries)
    - Requires year + location (fails gracefully if missing)
    - Sets data_synced=True to trigger loop-back
    """
    # 1. Check fetch_attempts < MAX_FETCH_ATTEMPTS (2)
    # 2. Validate year and location exist
    # 3. Call sync_telemetry_tool()
    # 4. Return {
    #     "db_query_result": "",      # Clear for re-query
    #     "data_synced": True,         # Signal to loop back
    #     "fetch_attempts": +1
    # }
```

##### **Node 4: `f1_decision_node()` (Entirely New)**
```python
def f1_decision_node(state: F1SubState) -> Literal["query", "fetch", "end"]:
    """
    DECISION NODE: Routes flow based on state (not hardcoded logic).
    
    Logic:
    - If data_synced == True → "query" (loop back to re-query)
    - Else if "no_data_in_db" in db_result AND fetch_attempts < 2 → "fetch"
    - Else → "end"
    """
```
- Three return values create conditional edge paths.
- Purely state-based (no LLM call, deterministic).

##### **Node 5: `f1_finalize_node()` (Entirely New)**
```python
def f1_finalize_node(state: F1SubState) -> dict:
    """
    NEW NODE: Finalize response before returning to main graph.
    
    Logic:
    - If final_response is set (from error), use that
    - Else if db_result is empty, return "couldn't find data"
    - Else return db_result (the answer)
    """
```
- Ensures clean final response regardless of path taken.

#### **Graph Assembly: New Conditional Edges**

```python
# BEFORE: Linear edges
add_edge(START, "extract")
add_edge("extract", "sync")
add_edge("sync", "sql")
add_edge("sql", END)

# AFTER: Conditional routing with cycle
add_edge(START, "extract")
add_edge("extract", "query")
add_edge("query", "decide")

add_conditional_edges(
    "decide",
    lambda state: (
        "query" if state.get("data_synced") else
        "fetch" if "no_data_in_db" in state.get("db_query_result", "").lower() 
                   and state.get("fetch_attempts", 0) < 2 else
        "end"
    ),
    {
        "query": "query",      # Loop back to query
        "fetch": "fetch",      # Go to fetch
        "end": "finalize"      # Finalize and exit
    }
)

add_edge("fetch", "decide")     # Fetch always returns to decision
add_edge("finalize", END)       # Finalize always exits
```

#### **Imports Added**
```python
from typing import Literal              # For type hints on decision node returns
import logging                          # For structured logging
from langchain_core.messages import AIMessage  # Future use (agent tools)
```

#### **Functions Removed/Deprecated**
- `f1_sync_node()`: Removed (logic split into separate fetch node).
- `f1_sql_node()`: Removed (logic moved to query_db_node).
- The old 3-node architecture is completely replaced.

---

### 2.3 Data Flow Impact

#### **State Evolution Through Graph**

```
Step 1: START
State: {query: "...", entities: {}, final_response: "", db_query_result: "", 
        fetch_attempts: 0, data_synced: False}

Step 2: extract_node
State: {entities: {year: 2024, event_name: "Monaco", ...}, fetch_attempts: 0, data_synced: False}

Step 3: query_db_node
State: {db_query_result: "Fetched 78 laps from Monaco 2024...", ...}

Step 4: decision_node
Check: db_result has data? YES → return "end"

Step 5: finalize_node
State: {final_response: "Fetched 78 laps from Monaco 2024..."}

Output: final_response
```

#### **Cache Miss Scenario (Loop)**

```
Step 1-2: [Same as above]

Step 3: query_db_node
State: {db_query_result: "NO_DATA_IN_DB", ...}

Step 4: decision_node
Check: "NO_DATA_IN_DB" in result? YES
Check: fetch_attempts (0) < MAX (2)? YES
→ return "fetch"

Step 5: fetch_api_node
Action: sync_telemetry_tool(2024, "Monaco", "R")
State: {db_query_result: "", data_synced: True, fetch_attempts: 1}

Step 6: decision_node (LOOP BACK)
Check: data_synced == True? YES
→ return "query"

Step 7: query_db_node (RE-QUERY)
State: {db_query_result: "Fetched 78 laps from Monaco 2024...", data_synced: False}

Step 8: decision_node
Check: db_result has data? YES → return "end"

Step 9: finalize_node
Output: final_response
```

#### **SQL Agent Prompting Evolution**

**Before**:
```python
agent_prompt = (
    f"You are a TWG Global F1 Analyst. Query: '{state['query']}'\n\n"
    f"Use the 'f1_telemetry' table..."
)
```

**After**:
```python
agent_prompt = (
    f"You are a TWG Global F1 Analyst. Answer this query: '{query_text}'\n\n"
    f"Context Entities: {context}\n\n"
    f"INSTRUCTIONS:\n"
    f"1. Query the 'f1_telemetry' table for lap-by-lap data.\n"
    f"2. Use provided entities to filter (WHERE year = {year} AND event_name = '{location}').\n"
    f"3. If the table returns NO results, report 'NO_DATA_IN_DB'.\n"  # ← KEY
    f"4. If the table HAS data, provide a professional summary.\n"
    f"5. If you can't find the answer in the database, say so clearly."
)
```
- **Critical Addition**: Explicit instruction to report `"NO_DATA_IN_DB"` when empty.
- This signal is parsed by `f1_decision_node()` to route to fetch.

#### **Loop Prevention Mechanism**

```python
fetch_attempts: int = 0

# In fetch_api_node:
if fetch_attempts >= MAX_FETCH_ATTEMPTS (2):
    return {"final_response": "Max attempts reached"}

# After fetch:
fetch_attempts += 1

# In decision_node:
if fetch_attempts < 2 and no_data_detected:
    return "fetch"
else:
    return "end"  # Exit even if data still missing
```

**Why This Works**:
- Counter is incremented only in fetch_api_node.
- Query node doesn't increment, so repeated queries don't count.
- After 2 API attempts, graph exits gracefully.

#### **Database Interactions**

```
query_db_node:
  ├─ Reads f1_telemetry table (SELECT)
  └─ Returns rows or "NO_DATA_IN_DB"

fetch_api_node:
  ├─ Calls FastF1 API (external, not Neon)
  └─ Calls to_sql(...) to INSERT rows into f1_telemetry

[Loop back]

query_db_node (2nd time):
  ├─ Reads f1_telemetry table (now populated)
  └─ Returns rows
```

No schema changes to Neon DB. Existing `f1_telemetry` table is used as-is.

---

### 2.4 Deployment / Next Steps

#### **Dependencies**
No new pip packages. Existing setup supports:
```bash
langchain-groq
langchain-core
langgraph
fastf1
pandas
sqlalchemy
```

#### **Environment Variables**
No changes required. Existing:
```
GROQ_API_KEY=...
DATABASE_URL=...  # Neon connection string
```

#### **Database Schema**
No schema changes. Existing `f1_telemetry` table is used.

#### **Running Updated F1 Subgraph**
```bash
python f1_agent.py

# Expected output:
# ✅ Generated f1_internal_architecture.png
```

#### **Testing the Cyclic Flow**

```python
# Test 1: Query with cached data
from f1_agent import f1_sector_graph

state = {
    "query": "What was Lewis Hamilton's fastest lap at Monaco 2024?",
    "entities": {},
    "final_response": "",
    "db_query_result": "",
    "fetch_attempts": 0,
    "data_synced": False
}

# Expected flow: extract → query → decide → finalize (no fetch needed)
output = f1_sector_graph.invoke(state)
print(output["final_response"])
```

```python
# Test 2: Query with missing data (forces fetch)
state = {
    "query": "Top 3 fastest drivers at Monaco 2025?",  # Future year, likely not in DB
    "entities": {},
    "final_response": "",
    "db_query_result": "",
    "fetch_attempts": 0,
    "data_synced": False
}

# Expected flow: extract → query → decide → fetch → decide → query → decide → finalize
output = f1_sector_graph.invoke(state)
print(output["final_response"])
```

#### **Monitoring & Debugging**

Enable logging:
```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Now logs will show:
# INFO: Query: 'What was...' → Routed to: f1_sector
# WARNING: Failed to parse extraction response: ...
# ERROR: SQL execution failed: ...
```

#### **Performance Expectations**

| Scenario | Time | LLM Calls | DB Calls |
|----------|------|-----------|----------|
| Cached data (hit) | ~2-3s | 2 (extract + SQL) | 1 (query) |
| Missing data (fetch + re-query) | ~15-20s | 2 (extract + SQL + SQL again) | 1 (query) + 1 (insert) + 1 (query) |

#### **Known Limitations**

1. **Single Retry**: If API fails (network error), graph exits instead of retrying.
   - **Mitigation**: Wrap `sync_telemetry_tool()` in retry logic if needed.

2. **Session Type Hardcoded**: Always uses `session_type="R"` (Race).
   - **Future**: Could extract from query (e.g., "qualifying" → "Q").

3. **No Agent Tool Binding**: `sync_telemetry_tool` is defined but LLM doesn't call it directly.
   - **Current**: Node explicitly invokes it.
   - **Future**: Could bind to LLM for full autonomy.

#### **Next Steps for Production**

1. **Test cyclic flow** with cache hits and misses.
2. **Monitor logs** for `fetch_attempts` patterns (high retries = API issues).
3. **Implement retry logic** in `sync_telemetry_tool()` for transient failures.
4. **Add metrics**: Track "fetch_triggered", "loop_cycles", "total_time" per query.
5. **Extend to soccer/baseball**: Replicate F1 subgraph pattern for other sectors.

---

---

## Integration: Main Graph → F1 Subgraph

### Flow Diagram

```
main.py:START
  ↓
supervisor_router (LLM intent classification)
  ↓
conditional_edges
  ├─ "f1_sector" → f1_sector_graph (F1SubState)
  ├─ "soccer_sector" → [placeholder] (F1SubState for now)
  └─ "baseball_sector" → [placeholder] (F1SubState for now)
  ↓
f1_agent.py: f1_sector_graph
  ├─ extract
  ├─ query ↘
  │         decide ← fetch (cycle)
  │        ↙  ↓  ↘
  │    query fetch end
  │       ↓   ↓    ↓
  │    [LOOP] finalize
  └─ END
  ↓
main.py:END
```

### State Mapping

```python
# main.py AgentState
{
    "messages": [],
    "query": "Which team was lewis hamilton part of in 2022?",
    "user_role": "admin",
    "domain_detected": "f1",
    "final_response": ""
}

# ↓ router directs to f1_sector_graph ↓

# f1_agent.py F1SubState (subset of AgentState)
{
    "query": "Which team was lewis hamilton part of in 2022?",
    "entities": {"year": 2022, "driver": "Hamilton", ...},
    "final_response": "Hamilton was part of Mercedes in 2022.",
    "db_query_result": "...",
    "fetch_attempts": 0,
    "data_synced": False
}

# ↓ returns final_response ↓

# Back to main.py
{
    "final_response": "Hamilton was part of Mercedes in 2022."
}
```

---

## Summary of Changes

### Files Modified

| File | Lines Changed | Type | Status |
|------|---------------|------|--------|
| `main.py` | ~50 | Refactor + Extend | Complete ✅ |
| `f1_agent.py` | ~150 | Complete Rewrite | Complete ✅ |

### Key Metrics

- **Lines added**: ~200 (new nodes, decision logic, logging)
- **Lines removed**: ~100 (old linear nodes, keyword matching)
- **Net change**: +100 LOC
- **Complexity**: Sequential → Cyclic (graph now has a loop)
- **LLM calls per query**: 2-4 (extraction, query, possible re-query)
- **API calls per query**: 0-1 (only on cache miss)

### Backward Compatibility

✅ **Fully backward compatible** with existing `AgentState`.
- No breaking changes to state schema.
- Existing `main.py` behavior preserved (routes to f1_sector).
- F1SubState is internal to f1_agent.py; main.py doesn't need changes to its state handling.

---

## Testing Checklist

- [ ] Route "Tell me about Lewis Hamilton's 2023 season" → f1_sector ✅
- [ ] Route "Who scored the most goals?" → soccer_sector ✅
- [ ] Query Monaco 2024 with cached data (no fetch)
- [ ] Query future race (2025) to trigger fetch + loop-back
- [ ] Handle API failure gracefully (max 2 attempts)
- [ ] Verify `db_query_result` and `fetch_attempts` state tracking
- [ ] Check logs for decision paths taken
- [ ] Monitor LLM call counts (should be 2-4 per query)

---

## Appendix: Quick Reference

### Router Decision Logic
```python
query → router_llm → parse_router_response() → VALID_SECTORS → sector_name
```

### F1 Subgraph Decision Logic
```
extract → query → decide:
  ├─ If data_synced=True → query (loop)
  ├─ Else if "NO_DATA_IN_DB" AND attempts<2 → fetch
  └─ Else → finalize
```

### Loop Prevention
```
fetch_attempts counter incremented only in fetch_api_node
Max 2 attempts before decision_node returns "end" instead of "fetch"
```

### State Propagation
```
Extract Node: Initialize fetch_attempts=0, data_synced=False
Query Node: Populate db_query_result
Fetch Node: Set data_synced=True, increment fetch_attempts
Decision Node: Read all three fields, route accordingly
Finalize Node: Use final_response if set, else db_query_result
```

---

**End of Document**
