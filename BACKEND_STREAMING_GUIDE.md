# Backend Streaming Architecture Guide

## Table of Contents
1. [Overview](#overview)
2. [Architecture & Flow](#architecture--flow)
3. [How It Connects to main.py](#how-it-connects-to-mainpy)
4. [How It Connects to Frontend](#how-it-connects-to-frontend)
5. [Component Breakdown](#component-breakdown)
6. [SSE Protocol & Events](#sse-protocol--events)
7. [Detailed Function Explanations](#detailed-function-explanations)
8. [Data Flow Examples](#data-flow-examples)

---

## Overview

`backend_streaming.py` is the FastAPI server that implements **dual-stream Server-Sent Events (SSE)** to send real-time updates to the React frontend. It acts as the bridge between:
- **LangGraph** (main.py's compiled graph)
- **React Frontend** (twg-ui/src/App.jsx)

### Key Features
- ✅ **Dual-stream SSE**: Two simultaneous event streams
  - "updates" stream: Node execution trace (thought process)
  - "messages" stream: LLM tokens (typewriter effect)
- ✅ **Token-level streaming**: Progressive token emission for smooth UX
- ✅ **Node status tracking**: Real-time visibility of which node is running
- ✅ **Human-in-the-loop support**: Pause/resume graph execution for approval
- ✅ **Async/await pattern**: Non-blocking, high-concurrency design

---

## Architecture & Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     React Frontend (twg-ui)                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  App.jsx → useSportsAgent hook                          │   │
│  │  - Manages message state                                │   │
│  │  - Tracks activeTrace (node updates)                    │   │
│  │  - Renders TracePanel (node activity UI)                │   │
│  │  - Displays message bubbles (tokens)                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────┬──────────────────────────────────────┘
                             │
                    HTTP POST (EventSource)
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│              FastAPI Server (backend_streaming.py)               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  POST /chat/stream                                       │   │
│  │  ├─ Receives: ChatRequest(query, user_role, thread_id)  │   │
│  │  └─ Returns: StreamingResponse (SSE)                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  async stream_chat_agentic()                            │   │
│  │  ├─ Calls: graph.astream() from main.py               │   │
│  │  ├─ Receives: (stream_type, data) tuples               │   │
│  │  │   ├─ Type "updates": Node execution events           │   │
│  │  │   └─ Type "messages": LLM tokens                     │   │
│  │  └─ Yields: SSE-formatted events                        │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────┬──────────────────────────────────────┘
                             │
                  LangGraph astream() interface
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│              LangGraph Compiled (main.py)                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Main Graph (compiled with checkpointer)                │   │
│  │  ├─ Node: input_guard                                   │   │
│  │  ├─ Node: supervisor_router                             │   │
│  │  ├─ Node: f1_sector (sub-graph)                         │   │
│  │  ├─ Node: football_sector (sub-graph)                   │   │
│  │  ├─ Node: baseball_sector (sub-graph)                   │   │
│  │  └─ Node: output_guard                                  │   │
│  │                                                          │   │
│  │  Each sector contains synthesis LLMs:                    │   │
│  │  ├─ Extract entity → SQL query → Fetch (if needed)      │   │
│  │  └─ Finalize (async with astream) → tokens              │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## How It Connects to main.py

### Import & Graph Reference
```python
# Line 30 in backend_streaming.py
from main import graph  # Import the LLM router
```

The `graph` imported from `main.py` is the **compiled LangGraph** that contains:
- Router logic (which sector to route to)
- Input/output guards (safety checks)
- Sub-graphs for each sector (f1, baseball, football)
- Checkpointer for human-in-the-loop support

### Execution Flow
```python
# Line 193-196 in stream_chat_agentic()
async for event in graph.astream(
    initial_state,
    config,
    stream_mode=["updates", "messages"]
):
```

This calls LangGraph's `astream()` method with:
1. **initial_state**: AgentState dict with query, messages, flags
2. **config**: Thread ID for checkpoint recovery
3. **stream_mode**: ["updates", "messages"] — crucial for dual-streaming

### How main.py graph.astream() Works

When `graph.astream()` is called, it:
1. **Routes the query** via supervisor_router (in main.py)
2. **Executes appropriate sector sub-graph** (f1_agent, baseball_agent, etc.)
3. **Yields two types of events**:
   - "updates": Each time a node executes (from LangGraph internals)
   - "messages": Each time an LLM emits a token (from ChatGroq with streaming=True)

### State Architecture (AgentState)

Defined in `state.py` (imported via main.py):
```python
{
    "messages": [...],           # Chat history (HumanMessage, AIMessage)
    "query": "...",              # Original user query
    "user_role": "user|scout|admin",
    "domain_detected": "",       # Which sector was routed to
    "final_response": "",        # Final synthesized answer
    "is_safe": True,             # Guardrail check
    "guardrail_reason": ""       # Why it was flagged (if is_safe=False)
}
```

---

## How It Connects to Frontend

### Request Flow
```javascript
// frontend: useSportsAgent hook
const streamChat = (query) => {
  const response = await fetch('http://localhost:8000/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: query,
      user_role: 'user',
      thread_id: sessionId
    })
  });

  // EventSource reads SSE stream
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    const text = decoder.decode(value);
    // Each line is: "data: {...}\n\n"
    const event = JSON.parse(text.replace('data: ', ''));
    
    if (event.type === 'update') {
      // Update node status in UI
      setActiveTrace(prev => [...]);
    } else if (event.type === 'message') {
      // Append token to message
      setMessages(prev => [
        ...prev.slice(0, -1),
        { content: lastMsg.content + event.data.token }
      ]);
    }
  }
};
```

### Event Reception

Frontend receives two types of events:

**1. Update Events** (Node Status)
```json
{
  "type": "update",
  "timestamp": "2026-04-07T10:30:45.123456",
  "data": {
    "node": "f1_sector",
    "status": "running",  // "running", "completed", "error"
    "timestamp": "2026-04-07T10:30:45.123456"
  }
}
```

**2. Message Events** (Token Stream)
```json
{
  "type": "message",
  "timestamp": "2026-04-07T10:30:45.456789",
  "data": {
    "token": "Lewis",
    "is_final": false
  }
}
```

### Frontend State Management

In `useSportsAgent` hook:
```javascript
const [messages, setMessages] = useState([]);      // Chat messages
const [activeTrace, setActiveTrace] = useState([]); // Node execution trace

// When "update" event received:
setActiveTrace(prev => {
  const existing = prev.find(t => t.node === event.data.node);
  if (existing) {
    return prev.map(t => 
      t.node === event.data.node 
        ? { ...t, status: event.data.status }
        : t
    );
  }
  return [...prev, { node: event.data.node, status: event.data.status }];
});

// When "message" event received:
setMessages(prev => [
  ...prev.slice(0, -1),
  { role: 'ai', content: (prev[-1]?.content || '') + event.data.token }
]);
```

---

## Component Breakdown

### 1. **Request/Response Models** (Lines 63-74)

```python
class ChatRequest(BaseModel):
    query: str                    # User question: "Who won the 2024 F1 championship?"
    user_role: str = "user"      # Determines permissions: user|scout|admin
    thread_id: str               # Session ID for checkpoint recovery

class SSEEvent(BaseModel):
    type: str                     # "update" or "message"
    timestamp: str                # ISO timestamp
    data: dict                    # Event payload
```

### 2. **SSE Formatting Utilities** (Lines 81-142)

#### `format_sse_event(event_type, data)` (Lines 81-101)
**Purpose**: Convert Python dict to SSE format

**Input**:
```python
event_type = "update"  # or "message"
data = {"node": "f1_sector", "status": "running"}
```

**Output** (SSE format):
```
data: {"type":"update","timestamp":"2026-04-07T10:30:45.123456","data":{"node":"f1_sector","status":"running"}}\n\n
```

**Why SSE format**: 
- `data: ` prefix tells browsers this is SSE
- `\n\n` tells browsers event boundary
- Browser's EventSource API automatically parses this

#### `emit_update(node_name, status)` (Lines 104-122)
**Purpose**: Create a node status update event

**Call**: `yield emit_update("f1_sector", status="running")`

**Result**:
```python
SSE string with:
- event_type: "update"
- node_name: "f1_sector"
- status: "running" (changed from "executing" after fix)
```

#### `emit_message(token, is_final)` (Lines 125-142)
**Purpose**: Create a token emission event

**Call**: `yield emit_message("Lewis ", is_final=False)`

**Result**:
```python
SSE string with:
- event_type: "message"
- token: "Lewis "
- is_final: False (True only at stream end)
```

---

## SSE Protocol & Events

### What is SSE?

Server-Sent Events (SSE) is an HTTP protocol for one-way server-to-client streaming:
- **HTTP request**: Single POST from browser to server
- **Response**: Stream of text events, never closes
- **Format**: Each event = `data: <json>\n\n`
- **Browser API**: `EventSource` or `fetch().body.getReader()`

### TWG's Dual-Stream Implementation

Unlike typical SSE (one event type), TWG sends **two concurrent streams**:

```
Time ─────────────────────────────────────────────────────────────>

UPDATES:  [start: input_guard] → [complete: input_guard]
          [start: supervisor_router] → [complete: supervisor_router]
          [start: f1_sector] ───────────────────────────→ [complete]

MESSAGES:                                 [L][i][w][i][s][ ][H][a][m][i][l][t][o][n]
                                          └──────────────────────────────────────┘
                                                  Typewriter effect
```

**Why dual-stream?**
1. **Updates**: Show user what the AI is thinking (node trace)
2. **Messages**: Show progressive token rendering (typewriter effect)

### Event Order Guarantee

Due to line 221 `await asyncio.sleep(0.01)` after update:
1. Node "running" event is sent
2. Small delay (10ms) for UI to update
3. Then tokens start flowing

---

## Detailed Function Explanations

### `stream_chat_agentic()` — The Core Streaming Engine (Lines 149-275)

This is the **heart of the system**. It's an async generator that:

#### Signature
```python
async def stream_chat_agentic(
    query: str,                    # "Who won F1 2024?"
    user_role: str = "user",       # Permissions
    thread_id: str = "session_user" # Checkpoint ID
) -> AsyncIterator[str]:
```

Returns: Async iterator that yields SSE-formatted strings

#### Initialization (Lines 171-183)

```python
logger.info(f"Starting stream for query: {query[:50]}...")
config = {"configurable": {"thread_id": thread_id}}

initial_state = {
    "messages": [HumanMessage(content=query)],
    "query": query,
    "user_role": user_role,
    "domain_detected": "",      # Will be set by supervisor_router
    "final_response": "",       # Will be set by finalize node
    "is_safe": True,            # Will be checked by guardrails
    "guardrail_reason": ""
}
```

**Key insight**: `thread_id` enables checkpoint recovery — if user pauses for approval, we can resume from exactly here.

#### State Tracking (Lines 186-190)

```python
active_node = None          # Current executing node
previous_node = None        # Previous node (for "completed" events)
final_text_sent = False     # Flag to avoid duplicate final responses
last_token_hash = None      # Hash of last token (deduplication)
```

#### The Main Loop (Lines 193-252)

```python
async for event in graph.astream(
    initial_state,
    config,
    stream_mode=["updates", "messages"]  # CRUCIAL: enables dual-stream
):
    stream_type, data = event
```

Each `event` is a tuple: `(stream_type, data)`

**Stream Type 1: "updates"** (Lines 205-226)

When LangGraph executes a node:
```python
if stream_type == "updates":
    # data = {node_name: {state_update}}
    # Example: {"f1_sector": {"final_response": "Lewis Hamilton..."}}
    
    for node_name, node_state in data.items():
        # Mark PREVIOUS node as completed
        if previous_node and previous_node != node_name:
            yield emit_update(previous_node, status="completed")
            
        # Emit NEW node as running
        active_node = node_name
        previous_node = node_name
        yield emit_update(node_name, status="running")
        
        # Wait 10ms for UI to catch up
        await asyncio.sleep(0.01)
```

**Why the delay?** Allows frontend to update UI before tokens start flowing. Without it, user might miss node name in the speed of token rendering.

**Stream Type 2: "messages"** (Lines 231-252)

When LLM emits tokens:
```python
elif stream_type == "messages":
    # data = [AIMessageChunk(...), AIMessageChunk(...), ...]
    # Each chunk is one or more tokens from the LLM
    
    for message_chunk in data:
        token = None
        
        # Handle AIMessageChunk (streaming tokens)
        if isinstance(message_chunk, AIMessageChunk):
            token = message_chunk.content
        # Handle AIMessage (full message from finalize node)
        elif isinstance(message_chunk, AIMessage):
            token = getattr(message_chunk, 'content', None)
        
        # Deduplication: only emit if different from last token
        if token:
            token_hash = hash(token)
            if token_hash != last_token_hash:
                yield emit_message(token, is_final=False)
                last_token_hash = token_hash
        
        # 1ms delay for smooth streaming animation
        await asyncio.sleep(0.001)
```

**Why deduplication?** Without it, you might see: "Lewissss Hamilton" instead of "Lewis Hamilton"

#### Completion Handling (Lines 254-268)

```python
# After all events from graph.astream() are done:
current_state = graph.get_state(config)

if current_state.next:
    # Graph paused at a breakpoint (human-in-the-loop)
    yield format_sse_event(
        event_type="interrupt",
        data={"message": "Waiting for API approval"}
    )
else:
    # Graph completed normally
    yield emit_message("", is_final=True)  # Signal end of stream
    
    if active_node:
        yield emit_update(active_node, status="completed")
```

#### Error Handling (Lines 270-275)

```python
except Exception as e:
    logger.error(f"Stream error: {str(e)}")
    yield format_sse_event(
        event_type="error",
        data={"message": str(e)}
    )
```

If anything fails during streaming, send error event to frontend.

---

### `chat_stream()` — The FastAPI Endpoint (Lines 369-399)

```python
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
```

**Purpose**: HTTP endpoint that receives chat requests

**Flow**:
1. Receive POST with ChatRequest (query, user_role, thread_id)
2. Call `stream_chat_agentic()` generator
3. Wrap in StreamingResponse with SSE media type
4. Set headers to prevent buffering

**Critical Headers** (Lines 395-398):
```python
headers={
    "Cache-Control": "no-cache",     # Prevent caching of stream
    "X-Accel-Buffering": "no",      # Tell nginx/proxies not to buffer
}
```

Without these, some proxies might buffer the entire stream before sending, defeating real-time UX.

---

### `chat_resume()` — Human-in-the-Loop Support (Lines 403-440)

```python
@app.post("/chat/resume")
async def chat_resume(request: Request) -> dict:
```

**Purpose**: Resume paused graph execution when user approves

**Workflow**:
1. User clicks "Approve" on approval card
2. Frontend POST to `/chat/resume` with `{"thread_id": "...", "action": "approved"}`
3. Backend retrieves paused state via `graph.get_state(config)`
4. Resumes with `Command(resume=action)`
5. Returns final response once complete

**Why checkpointer matters**: LangGraph's checkpointer (MemorySaver in main.py line 182) saves state at interrupt. Without it, we'd lose all progress.

---

### `chat_non_streaming()` — Fallback Endpoint (Lines 466-496)

```python
@app.post("/chat")
async def chat_non_streaming(request: ChatRequest) -> dict:
```

**Purpose**: Non-streaming fallback for testing or simple clients

**Uses**: `graph.invoke()` instead of `graph.astream()`
- Blocks until complete response
- Returns JSON dict instead of stream
- No real-time updates or tokens

---

### `health_check()` — Endpoint Monitoring (Lines 499-506)

```python
@app.get("/health")
async def health_check() -> dict:
```

**Purpose**: Simple health check for load balancers/monitoring

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2026-04-07T10:30:45.123456",
  "streaming_enabled": true
}
```

---

## Data Flow Examples

### Example 1: Simple F1 Query

```
User Input: "Who won the 2024 F1 championship?"
Thread ID: "session_user_abc123"

┌─ Backend Receives ──────────────────────────┐
│ POST /chat/stream                           │
│ {                                            │
│   "query": "Who won the 2024...",           │
│   "user_role": "user",                       │
│   "thread_id": "session_user_abc123"        │
│ }                                            │
└────────────────────────────────────────────┘
                      ↓
┌─ stream_chat_agentic() ────────────────────┐
│ 1. Initial state created                    │
│ 2. graph.astream() called                   │
│ 3. main.py graph processes:                 │
│    - input_guard: "Is safe" ✓               │
│    - supervisor_router: Route to f1_sector  │
│    - f1_sector: Extract, query DB, finalize│
│    - output_guard: Final safety check       │
│                                              │
│ 4. Emits events:                            │
└────────────────────────────────────────────┘
                      ↓
        Stream of SSE Events to Frontend
┌────────────────────────────────────────────┐
│ data: {"type":"update","data":{"node":"in  │
│ put_guard","status":"running"}}\n\n        │
│                                              │
│ data: {"type":"update","data":{"node":"in  │
│ put_guard","status":"completed"}}\n\n      │
│                                              │
│ data: {"type":"update","data":{"node":"su  │
│ pervisor_router","status":"running"}}\n\n  │
│                                              │
│ data: {"type":"message","data":{"token":"  │
│ Lewis","is_final":false}}\n\n               │
│                                              │
│ data: {"type":"message","data":{"token":" H│
│ amilton","is_final":false}}\n\n             │
│                                              │
│ ... (more tokens) ...                       │
│                                              │
│ data: {"type":"message","data":{"token":"  │
│ ","is_final":true}}\n\n                     │
│                                              │
│ data: {"type":"update","data":{"node":"f1 │
│ _sector","status":"completed"}}\n\n        │
└────────────────────────────────────────────┘
                      ↓
        Frontend Processes Events
┌────────────────────────────────────────────┐
│ activeTrace = [                             │
│   {node: "input_guard", status: "completed"}│
│   {node: "supervisor_router", status: "..."}│
│   {node: "f1_sector", status: "completed"} │
│ ]                                            │
│                                              │
│ messages = [                                │
│   {role: "user", content: "Who won..."},   │
│   {role: "ai", content: "Lewis Hamilton"}  │
│ ]                                            │
└────────────────────────────────────────────┘
```

### Example 2: With Human-in-the-Loop

```
Assume some node calls an external API that needs approval...

┌─ graph.astream() emits interrupt ─────────┐
│ data: {"type":"interrupt","data":          │
│ {"message":"Waiting for API approval"}}\n\n│
└────────────────────────────────────────────┘
                      ↓
    Frontend shows approval card to user
                      ↓
    User clicks "Approve"
                      ↓
┌─ Frontend POST /chat/resume ───────────────┐
│ {                                            │
│   "thread_id": "session_user_abc123",      │
│   "action": "approved"                      │
│ }                                            │
└────────────────────────────────────────────┘
                      ↓
    Backend resumes from checkpoint
                      ↓
    API call executes with approval
                      ↓
    Stream continues (more tokens/nodes)
                      ↓
    graph.astream() completes
                      ↓
    Backend returns final response
```

---

## Summary Table

| Component | Purpose | Key Responsibilities |
|-----------|---------|----------------------|
| `ChatRequest` | Input model | Validate query, user_role, thread_id |
| `format_sse_event()` | Event formatting | Convert dict to SSE format |
| `emit_update()` | Node status event | Create "update" type SSE |
| `emit_message()` | Token event | Create "message" type SSE |
| `stream_chat_agentic()` | Core streaming | Execute graph, track nodes, emit events |
| `stream_sector_subgraph()` | Sector debugging | Stream individual sector sub-graphs |
| `chat_stream()` | Streaming endpoint | POST /chat/stream handler |
| `chat_resume()` | HITL endpoint | POST /chat/resume handler |
| `chat_non_streaming()` | Fallback endpoint | POST /chat handler (non-streaming) |
| `health_check()` | Health endpoint | GET /health |

---

## Connection Summary

**backend_streaming.py** is the glue between:
1. **React Frontend** ← Receives SSE events showing node updates & tokens
2. **LangGraph (main.py)** ← Calls graph.astream() to execute LLM pipeline
3. **Sub-agents** (f1_agent, baseball_agent, football_agent) ← Indirectly via main.py graph

It translates LangGraph's event stream into browser-friendly SSE, enabling real-time UX with dual feedback (node status + token streaming).
