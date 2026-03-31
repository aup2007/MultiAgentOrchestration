# System Architecture & Design Document
## TWG Global — Multi-Sector Sports Intelligence Platform

---

## 1. High-Level Project Overview

### Purpose
The TWG platform is a **LLM-powered sports intelligence router** built for TWG Global. It solves the problem of querying heterogeneous sports datasets — Formula 1 telemetry, soccer transfer data, and baseball statistics — through a single conversational interface. A user asks a natural-language question; the system determines the relevant sports domain, fetches/caches the appropriate data, and returns a professionally-worded analytical response.

### Primary Tech Stack

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | Streamlit | Chat UI with session-based auth |
| **API Gateway** | FastAPI + Uvicorn | REST endpoint, routes requests to graph |
| **Orchestration** | LangGraph + LangChain | Multi-agent state machine |
| **LLM Inference** | Groq (`gpt-oss-120b`) | Query parsing + response generation |
| **F1 Data Source** | FastF1 library | Official F1 telemetry API |
| **Persistence** | PostgreSQL on Neon Cloud (AWS us-east-1) | Partitioned telemetry storage |
| **Stub DBs** | SQLite (`transfermarkt.db`, `lahman.db`) | Planned soccer/baseball storage (not yet present) |

---

## 2. Detailed Technical Architecture

### System Flow: "Day in the Life" of a Query

Tracing `"What was Verstappen's fastest lap at the 2024 Monaco GP?"`:

```
+------------------------------------------------------------------+
|  1. USER -> Streamlit (frontend.py)                              |
|     st.chat_input() captures query                               |
|     session_state["token"] gates access (login wall)            |
+------------------------------+-----------------------------------+
                               | POST /chat  {query: "..."}
+------------------------------v-----------------------------------+
|  2. FastAPI (backend.py)                                         |
|     ChatRequest Pydantic model validates shape                   |
|     Builds partial initial_state = {"query": query}             |
|     Calls langgraph_app.invoke(initial_state)                    |
+------------------------------+-----------------------------------+
                               | invoke()
+------------------------------v-----------------------------------+
|  3. LangGraph Router (main.py) -> supervisor_router()            |
|     Keyword scan on lowercased query                             |
|     "prix" keyword matches -> f1_sector                          |
+------------------------------+-----------------------------------+
                               | node execution
+------------------------------v-----------------------------------+
|  4. f1_node() (f1_agent.py)                                      |
|                                                                  |
|     LLM Call 1: Parse query -> extract {Year: 2024, Loc: Monaco} |
|     check_if_data_exists(2024, "Monaco") -> PostgreSQL COUNT(*)  |
|                                                                  |
|     [CACHE HIT]  -> SELECT * FROM f1_telemetry WHERE ...        |
|                     ORDER BY lap_time_seconds ASC LIMIT 1        |
|                                                                  |
|     [CACHE MISS] -> fastf1.get_session(2024, "Monaco", "R")     |
|                  -> session.load() -> laps DataFrame             |
|                  -> ensure_f1_partition(2024) [db_utils.py]      |
|                  -> df.to_sql('f1_telemetry', engine, multi=True)|
|                  -> retrieve fastest lap object                  |
|                                                                  |
|     LLM Call 2: "You are F1 analyst. Data: {lap}. Answer: {q}"  |
+------------------------------+-----------------------------------+
                               | state["final_response"] = result
+------------------------------v-----------------------------------+
|  5. LangGraph -> END node                                        |
|     Returns full AgentState to backend.py                        |
|     FastAPI returns {"reply": ..., "domain": "F1 Sector"}        |
|     Streamlit renders st.chat_message("assistant").write(reply)  |
+------------------------------------------------------------------+
```

**Total Latency:**
- Cache hit: ~2.1s (dominated by 2 LLM calls at ~1s each)
- Cache miss: ~6.1s (adds ~3s FastF1 API + ~1s bulk insert)

---

### Component Breakdown

**`state.py`** — The Shared Contract

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    query: str
    user_role: str
    domain_detected: str
    final_response: str
```

Every node in the graph reads from and writes to this TypedDict. The `Annotated[..., operator.add]` on `messages` is a LangGraph reducer: when multiple nodes emit message updates, LangGraph merges them by concatenation rather than overwriting. This is the only field with a custom reducer — all others follow last-write-wins semantics.

**`main.py`** — The Orchestration Brain

Builds the LangGraph `StateGraph`. Key insight: `add_conditional_edges` from `START` means the router runs *before* any node executes. The edge mapping `{"soccer_sector": "f1_sector", "baseball_sector": "f1_sector"}` is the current stub wiring — all three return values of the routing function point to the same node.

**`db_utils.py`** — The Partitioning Engine

Creates and manages the `f1_telemetry` parent table and yearly child partition tables. The logic exists inside `ensure_f1_partition()`, which checks `pg_tables` before issuing DDL — this is idempotent by design, safe to call on every cache-miss path.

**`f1_agent.py`** — The Only Live Agent

The only fully implemented domain agent. It does triple duty: (1) LLM-based structured extraction, (2) cache-or-fetch data retrieval, (3) LLM-based response synthesis.

**`backend.py`** — The Thin Gateway

FastAPI server with two routes. Notable: it builds only `{"query": request.query}` as the initial state, leaving `messages`, `user_role`, and `domain_detected` unset. LangGraph tolerates this only because the F1 node doesn't read those fields during normal execution.

**`frontend.py`** — The Session-Gated UI

Streamlit uses `st.session_state` as its in-memory store. The login gate is implemented as a conditional on `st.session_state["token"] is None`, with `st.rerun()` forcing a page reload post-authentication. The token is sent as a Bearer header but never validated by the backend.

---

## 3. Design Choices & Patterns

### Data Strategy: PostgreSQL Partitioning

The most architecturally deliberate decision in the codebase is in `db_utils.py:ensure_f1_partition()`:

```sql
CREATE TABLE IF NOT EXISTS f1_telemetry (
    id SERIAL,
    year INT NOT NULL,
    ...
    PRIMARY KEY (id, year)
) PARTITION BY RANGE (year);

CREATE TABLE f1_laps_2024 PARTITION OF f1_telemetry
    FOR VALUES FROM (2024) TO (2025);
```

**Why this choice:** F1 telemetry is naturally time-series data. By partitioning on `year`, PostgreSQL's query planner performs **partition pruning** — a query for 2024 data never touches `f1_laps_2025`. This also means bulk inserts for a new season go into an isolated partition, avoiding lock contention on historical data. The `PRIMARY KEY (id, year)` includes `year` because PostgreSQL requires partition keys to be part of the primary key in declarative partitioning.

**The two-tier cache:** FastF1 has its own file-based local cache, which the code explicitly disables (`Cache.set_disabled()`) before syncing and re-enables after. This forces fresh data from the F1 API during sync operations, while the PostgreSQL layer serves as the durable, shared cache across all users and requests.

**No indexing defined:** The current schema has no secondary indexes on `driver`, `event_name`, or `lap_time_seconds`. The fastest-lap query uses `ORDER BY lap_time_seconds ASC LIMIT 1`, which will perform a full partition scan. At F1 scale (~1,000 laps per race, ~23 races/year), this is acceptable; at large scale it would warrant a B-tree index on `(year, event_name, lap_time_seconds)`.

### State & Logic: LangGraph TypedDict

The choice of LangGraph over a simpler chain is motivated by the multi-agent routing requirement. LangGraph represents the pipeline as a directed graph where nodes are Python functions and edges are either deterministic (`add_edge`) or conditional (`add_conditional_edges`). The state machine guarantees that:

1. Each node receives a full copy of `AgentState`
2. Node return dicts are **merged** (not replaced) into state
3. The `operator.add` reducer on `messages` means conversation history accumulates automatically without manual list management

This design allows future nodes to share context (e.g., a soccer node could read `domain_detected` set by a pre-processing node) without explicit parameter passing.

### Scalability: Patterns Used

| Pattern | Where | Rationale |
|---|---|---|
| **Supervisor Router** | `main.py:supervisor_router()` | Single decision point that fans out to specialized agents — scales by adding new keyword sets and new nodes |
| **Strategy Pattern** | `supervisor_router()` | The routing function is a pluggable strategy; swapping keyword matching for an LLM classifier requires only changing this one function |
| **Factory Pattern** | `f1_agent.py` | `ChatGroq(model=..., temperature=0)` creates the LLM client at module load time (effectively a module-level singleton) |
| **Repository Pattern** | `db_utils.py` | `engine = create_engine(...)` is the single database abstraction point; all agents import this rather than creating their own connections |
| **Cache-Aside Pattern** | `f1_node()` | Check cache first, populate on miss — the canonical read-through cache pattern |
| **Iterator/Streaming** | `main.py:run_sports_ai()` | `graph.stream()` emits state updates node-by-node, enabling real-time output before the full graph completes |

**Current scalability ceiling:** The system is single-process Uvicorn with no worker configuration. SQLAlchemy's default connection pool is 5 connections. Horizontal scaling would require externalizing LangGraph state (currently in-process memory per request) to Redis or a shared store.

---

## 4. Multi-Agent / Service Orchestration

### Current Architecture

```
START
  |
  v
supervisor_router()          <- Conditional edge decision function
  |
  +--- "f1_sector"     -----> f1_node() ----> END
  +--- "soccer_sector" -----> f1_node() ----> END  (stub: wired to F1)
  +--- "baseball_sector" ---> f1_node() ----> END  (stub: wired to F1)
```

The graph is currently **linear and single-path** — no parallel fan-out, no aggregation node. The stub agents (`football_agent.py`, `baseball_agent.py`) each define a `create_sql_agent()` from LangChain, which internally implements a **ReAct loop**: the LLM reasons about what SQL to run, executes it via the `QuerySQLDataBaseTool`, observes the result, and iterates. This is a multi-step agentic pattern hidden inside a single graph node.

### Guardrails & Error Handling

**What exists:**
```python
# f1_agent.py
try:
    ...
except Exception as e:
    return {"final_response": f"F1 Cloud Sync Error: {str(e)}"}

# backend.py
except Exception as e:
    raise HTTPException(status_code=500, detail=f"Graph Error: {str(e)}")
```

**What's missing:**
- No retry logic (a transient Groq API 429 will immediately surface as an error)
- No exponential backoff on FastF1 calls
- No circuit breaker pattern
- No timeout guards (FastF1 `session.load()` can block indefinitely on slow connections)
- Generic `except Exception` catches everything, including programming errors that should propagate

### Inter-Service Communication

| From | To | Protocol | Auth |
|---|---|---|---|
| Streamlit | FastAPI | HTTP REST (requests lib) | Bearer token (not validated) |
| FastAPI | LangGraph | In-process function call | None |
| f1_node | Groq API | HTTPS (LangChain SDK) | API key in env |
| f1_node | FastF1 | HTTPS | None (public API) |
| f1_node / db_utils | Neon PostgreSQL | TCP + SSL | Connection string in env |

---

## 5. Critical Observations

### 1. The Backend Sends Incomplete State to LangGraph

`backend.py` builds `initial_state = {"query": request.query}` — omitting `messages`, `user_role`, and `domain_detected`. LangGraph doesn't raise an error because `f1_node()` only reads `state["query"]`. However, if any node were added that reads `state["messages"]` (e.g., for conversation history), it would receive `None` and crash. The correct initialization is in `test_f1.py`, which includes all fields.

### 2. The Router Has a Silent Default Bias

```python
def supervisor_router(state):
    query = state["query"].lower()
    if any(word in query for word in ["f1", "verstappen", "lap", "prix", "race"]):
        return "f1_sector"
    elif any(word in query for word in ["soccer", "goal", "transfer", "market"]):
        return "soccer_sector"
    return "baseball_sector"   # <- catches everything else, including soccer/baseball
```

The `else` clause defaults to `"baseball_sector"`, which is then mapped to `"f1_sector"` in `add_conditional_edges`. Any query that doesn't contain the exact F1 or soccer keywords silently routes to the F1 agent, including a baseball query about Shohei Ohtani. There's no "unknown domain" path.

### 3. Module-Level LLM Instantiation Creates Silent Import-Time Side Effects

In `f1_agent.py`, `football_agent.py`, and `baseball_agent.py`, the LLM clients and database connections are created at **module import time**, not inside the node functions. This means importing `f1_agent` immediately attempts to read `GROQ_API_KEY` from the environment and establish a SQLAlchemy engine connection. If the env var is missing at import time, the entire application fails to start with a cryptic error, not a clear configuration error.

### 4. FastF1's Cache Toggle Pattern is a Race Condition in Concurrent Contexts

```python
Cache.set_disabled()
# ... do sync ...
Cache.set_enabled()
```

`fastf1.Cache` is a **global module-level state**. In a concurrent server with multiple workers, one request's `set_disabled()` could affect another simultaneous request's cache behavior. The current single-threaded Uvicorn deployment makes this safe in practice, but it's a latent bug that would manifest under load.

### 5. The Partition Function is Called on Every Cache Miss, But DDL is Idempotent

`ensure_f1_partition(year, engine)` runs `CREATE TABLE IF NOT EXISTS` DDL on every sync operation. This is safe (the `IF NOT EXISTS` guard prevents errors) but issues DDL on the hot path. In production, partitions should be pre-created via a migration or a scheduled job, not during request handling.

### 6. LangGraph's `graph.stream()` vs. `graph.invoke()` — Two Different Interfaces

`main.py:run_sports_ai()` uses `graph.stream()` (an iterator that yields intermediate states), while `backend.py` uses `langgraph_app.invoke()` (returns the final state dict). These are not interchangeable. The `run_sports_ai()` function is a debugging/CLI utility; the actual production path through `invoke()` in `backend.py` is what users hit. A developer reading only `main.py` would see streaming and assume that's the execution model.

### 7. The Soccer/Baseball Agents Would Fail Even If Wired Correctly

`football_agent.py` and `baseball_agent.py` instantiate SQLite databases (`transfermarkt.db`, `lahman.db`) that don't exist on disk. Importing these modules at startup silently succeeds because SQLite creates the file on first connection. But executing the SQL agent would return empty results or errors because the schemas and data aren't populated. The stub routing that sends everything to the F1 agent is actually *protecting* users from hitting these broken agents.

---

## Architecture Summary Diagram

```
+---------------------------------------------------------------+
|                    Streamlit Frontend                         |
|   st.session_state["token"] ---> login gate ---> chat UI     |
+----------------------------+----------------------------------+
                             | POST /chat (HTTP)
+----------------------------v----------------------------------+
|                   FastAPI Backend                             |
|   /token (form auth) | /chat (ChatRequest -> invoke graph)   |
+----------------------------+----------------------------------+
                             | in-process invoke()
+----------------------------v----------------------------------+
|               LangGraph StateGraph                            |
|                                                               |
|   AgentState ---> supervisor_router() ---> f1_node() --> END  |
|   (TypedDict)      (keyword match)         (active)           |
|                        |                                      |
|               soccer/baseball also wired --> f1_node (stubs) |
+----------+---------------------------+------------------------+
           |                           |
+----------v----------+   +-----------v----------------------------+
|   Groq LLM API      |   |      Neon PostgreSQL                   |
|   gpt-oss-120b      |   |  f1_telemetry (PARTITION BY year)      |
|   Call 1: parse     |   |  +-- f1_laps_2024                      |
|   Call 2: respond   |   |  +-- f1_laps_2025                      |
+---------------------+   |  +-- f1_laps_NNNN (on-demand DDL)     |
                          +----------------------------------------+
                                        ^
                         +--------------+
                         | cache miss only
                   +-----v------------------+
                   |   FastF1 API           |
                   |   (official F1 data)   |
                   |   ~3s per session load |
                   +------------------------+
```

---

## File Manifest

| File | Lines | Purpose |
|---|---|---|
| `main.py` | 61 | LangGraph router & orchestration |
| `state.py` | 12 | Shared AgentState definition |
| `backend.py` | 54 | FastAPI REST server |
| `frontend.py` | 39 | Streamlit UI |
| `f1_agent.py` | 140 | F1 domain agent (primary, fully implemented) |
| `football_agent.py` | 20 | Soccer agent (stub — DB not present) |
| `baseball_agent.py` | 15 | Baseball agent (stub — DB not present) |
| `db_utils.py` | 46 | Database partitioning utilities |
| `test_f1.py` | 25 | F1 agent unit test |
