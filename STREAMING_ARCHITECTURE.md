# Dual-Stream SSE Architecture Guide
## Real-Time LangGraph Streaming with Live Thought Trace

**Updated**: 2026-04-01  
**Architecture**: FastAPI + LangGraph + Streamlit with Server-Sent Events (SSE)

---

## 🎯 What Changed

### Before: Blocking Request/Response
```
Frontend → Backend.post(/chat) → LLM processes → Response returned (blocking)
```
- User waits for entire response
- No visibility into agent's thought process
- Poor UX for long-running queries

### After: Dual-Stream SSE
```
Frontend ─┬─→ Backend.post(/chat/stream)
          │
          ├─ STREAM 1: "updates" ─→ Node execution trace (thought process)
          │                          ├─ Router active
          │                          ├─ Query executing
          │                          └─ Analysis complete
          │
          └─ STREAM 2: "messages" → LLM tokens (incremental response)
                                     ├─ "The fastest driver..."
                                     ├─ "in 2024 was..."
                                     └─ "Lewis Hamilton"
```

---

## 🔧 Backend Changes (`backend.py`)

### Key Update: Dual-Stream Mode

**Before**:
```python
for output in langgraph_app.stream(initial_state):
    for node_name, state_update in output.items():
        yield f"data: {json.dumps(payload)}\n\n"
```
- Single stream: node-level updates only
- No token-level granularity

**After**:
```python
for stream_type, data in langgraph_app.stream(
    initial_state,
    stream_mode=["updates", "messages"]  # ← DUAL STREAMS
):
    if stream_type == "updates":
        # Node execution trace (thought process)
        yield format_sse_event("update", {...})

    elif stream_type == "messages":
        # LLM token chunks (incremental response)
        for message_chunk in data:
            if isinstance(message_chunk, AIMessageChunk):
                token = message_chunk.content
                yield format_sse_event("message", {"token": token})
```

### SSE Event Format

Each event follows strict SSE format:
```
data: <json>\n\n
```

**Update Event** (node trace):
```json
{
  "type": "update",
  "timestamp": "2026-04-01T12:34:56.789012",
  "data": {
    "node": "query_db_node",
    "status": "executing"
  }
}
```

**Message Event** (token stream):
```json
{
  "type": "message",
  "timestamp": "2026-04-01T12:34:56.890123",
  "data": {
    "token": "The fastest",
    "is_final": false
  }
}
```

**Error Event**:
```json
{
  "type": "error",
  "timestamp": "2026-04-01T12:34:56.999999",
  "data": {
    "message": "Database query failed"
  }
}
```

### New Utility Functions

```python
def format_sse_event(event_type: str, data: dict) -> str:
    """
    Format event as Server-Sent Events.
    Returns: "data: <json>\n\n"
    """
    sse_event = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }
    return f"data: {json.dumps(sse_event)}\n\n"
```

### StreamingResponse Headers

```python
return StreamingResponse(
    event_generator(),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # Disable proxy buffering (important!)
    }
)
```

**Why these headers?**
- `text/event-stream`: Tells browser this is SSE (not JSON)
- `Cache-Control: no-cache`: Ensures real-time delivery
- `X-Accel-Buffering: no`: Disables Nginx/proxy buffering that delays events

---

## 🎨 Frontend Changes (`frontend.py`)

### Key Update: Dual-Stream Consumption

**Before**:
```python
res = requests.post(f"{API_URL}/chat", json={"query": query}, stream=True)
for line in res.iter_lines():
    data = json.loads(line.decode('utf-8').replace('data: ', ''))
    status_placeholder.caption(f"🔄 {data['status']}")  # Single placeholder
```
- One placeholder for all events
- No thought trace visibility

**After**:
```python
# Separate containers for different streams
trace_expander = st.expander("Node Execution", expanded=True)
response_placeholder = st.empty()

# Process dual streams
for line in res.iter_lines():
    event = json.loads(line.decode('utf-8').replace('data: ', ''))
    event_type = event.get("type")

    if event_type == "update":
        # Node trace (thought process)
        with trace_expander:
            st.markdown(f'<div class="thought-trace">▶ {node_name}</div>')

    elif event_type == "message":
        # Incremental token rendering
        accumulated_response += token
        with response_placeholder.container():
            st.markdown(f'<div class="token-stream">{accumulated_response}</div>')
```

### Real-Time UI Components

#### 1. **Live Thought Trace** (st.expander + st.markdown)
```python
with trace_expander:
    # Append nodes dynamically
    st.markdown(f'<div class="thought-trace">
                    <span class="node-executing">▶ query_db_node</span>
                </div>', unsafe_allow_html=True)
```

**Output**:
```
🧠 Live Thought Trace
━━━━━━━━━━━━━━━━━━━━
▶ router_node
▶ query_db_node
✓ decision_node
▶ analyze_node
```

#### 2. **Incremental Token Rendering** (st.empty)
```python
response_placeholder = st.empty()

for token in token_stream:
    accumulated_response += token
    with response_placeholder.container():
        st.markdown(f'<div class="token-stream">{accumulated_response}</div>')
```

**Output** (updates in place as tokens arrive):
```
The fastest driver
The fastest driver in 2024
The fastest driver in 2024 was Lewis Hamilton
```

#### 3. **Node Status Styling**
```css
.node-executing { color: #FFA500; } /* Orange - active */
.node-completed { color: #28A745; } /* Green - done */
.node-error { color: #DC3545; }     /* Red - failed */
```

---

## 🚀 Running the System

### Terminal 1: Start Backend
```bash
cd /Users/Atharv/Documents/TWG
python backend.py

# Expected output:
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Terminal 2: Start Frontend
```bash
cd /Users/Atharv/Documents/TWG
streamlit run frontend.py

# Expected output:
# You can now view your Streamlit app in your browser.
# URL: http://localhost:8501
```

### Test in Browser
1. Open http://localhost:8501
2. Login: `atharv_admin` / `nyu2025`
3. Enter query: "Who won the 2024 World Series?"
4. Watch live thought trace appear
5. Watch tokens arrive incrementally

---

## 📊 Data Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  FRONTEND (Streamlit)                    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │ User Query: "Who won the 2024 World Series?"    │   │
│  └────────────────────┬────────────────────────────┘   │
│                       │                                  │
│                       │ requests.post(stream=True)      │
│                       ▼                                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │         Live Thought Trace (st.expander)        │   │
│  │ ▶ router_node                                   │   │
│  │ ▶ baseball_subgraph::extract                    │   │
│  │ ▶ baseball_subgraph::query                      │   │
│  │ ✓ baseball_subgraph::analyze                    │   │
│  └─────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │      Incremental Response (st.empty)            │   │
│  │ "The 2024 World..."                             │   │
│  │ "The 2024 World Series was won by the..."       │   │
│  │ "The 2024 World Series was won by the Yankees"  │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
          ▲                                    │
          │ SSE: event: update\n               │
          │ SSE: event: message\n              │
          │ SSE: event: message\n              │
          │ SSE: event: message\n              │
          │                                    │
┌─────────────────────────────────────────────────────────┐
│                 BACKEND (FastAPI)                        │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ POST /chat                                       │  │
│  │                                                  │  │
│  │ def event_generator():                           │  │
│  │   for stream_type, data in graph.astream(        │  │
│  │     state,                                       │  │
│  │     stream_mode=["updates", "messages"]          │  │
│  │   ):                                             │  │
│  │     if stream_type == "updates":                 │  │
│  │       yield format_sse_event("update", {...})    │  │
│  │     elif stream_type == "messages":              │  │
│  │       yield format_sse_event("message", {...})   │  │
│  └──────────────────────────────────────────────────┘  │
│                    │                                    │
│                    ▼                                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │          LangGraph with Dual Streams             │  │
│  │                                                  │  │
│  │  STREAM 1: updates                               │  │
│  │  ├─ router_node → "executing"                    │  │
│  │  ├─ baseball_subgraph::extract → "executing"     │  │
│  │  ├─ baseball_subgraph::validate → "executing"    │  │
│  │  ├─ baseball_subgraph::query → "executing"       │  │
│  │  └─ baseball_subgraph::analyze → "completed"     │  │
│  │                                                  │  │
│  │  STREAM 2: messages                              │  │
│  │  ├─ AIMessageChunk("The")                        │  │
│  │  ├─ AIMessageChunk("2024")                       │  │
│  │  ├─ AIMessageChunk("World")                      │  │
│  │  └─ AIMessageChunk("Series...")                  │  │
│  └──────────────────────────────────────────────────┘  │
│                    │                                    │
│                    ▼                                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │          Neon Database / LLM APIs                │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 🔍 Debugging

### Check Backend is Streaming

```bash
# Terminal 3: Use curl to test SSE stream
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Who won the 2024 World Series?"}'

# Expected output (raw SSE):
# data: {"type":"status","timestamp":"...","data":{"message":"🚀 Connected..."}}
# data: {"type":"update","timestamp":"...","data":{"node":"router_node","status":"executing"}}
# data: {"type":"message","timestamp":"...","data":{"token":"The","is_final":false}}
# data: {"type":"message","timestamp":"...","data":{"token":" 2024","is_final":false}}
# ...
```

### Enable Logging

**Backend**:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.info(f"🧠 Node: {node_name}")
```

**Frontend**:
```python
import logging
logger = logging.getLogger(__name__)
logger.debug(f"Token: {token}")
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Backend returns `502 Bad Gateway` | Check `X-Accel-Buffering: no` header |
| Tokens arrive all at once | Verify `stream_mode=["updates", "messages"]` in `astream()` |
| Frontend shows blank response | Check `st.empty()` container is within chat message |
| Thought trace not updating | Verify `st.expander` is used (not static markdown) |
| High latency between updates | Reduce `asyncio.sleep()` delays in backend |

---

## 📈 Performance Tips

### Optimize for Low Latency

1. **Backend**: Minimize delays
```python
# Good: Small delays only
await asyncio.sleep(0.001)  # 1ms

# Bad: Large delays block streaming
await asyncio.sleep(0.5)    # 500ms
```

2. **Frontend**: Avoid re-renders
```python
# Good: Update container in place
with response_placeholder.container():
    st.markdown(accumulated_response)

# Bad: Full page re-render
st.write(accumulated_response)
```

3. **Network**: Verify headers
```bash
curl -v http://localhost:8000/chat | grep -i cache-control
# Should output: Cache-Control: no-cache
```

---

## 🎓 Understanding SSE Events

### Event 1: Connection Status
```json
{
  "type": "status",
  "data": {"message": "🚀 Connected to TWG Server..."}
}
```

### Event 2: Node Trace (Thought Process)
```json
{
  "type": "update",
  "data": {
    "node": "router_node",
    "status": "executing"
  }
}
```

### Event 3: Token Stream (Response)
```json
{
  "type": "message",
  "data": {
    "token": "The",
    "is_final": false
  }
}
```

### Event 4: Completion Signal
```json
{
  "type": "message",
  "data": {
    "token": "",
    "is_final": true
  }
}
```

### Event 5: Error (if any)
```json
{
  "type": "error",
  "data": {"message": "Database query failed"}
}
```

---

## 🧪 Test Script

To test the dual-stream architecture programmatically:

```python
# test_streaming.py
import requests
import json

response = requests.post(
    "http://localhost:8000/chat",
    json={"query": "Who won the 2024 World Series?"},
    stream=True
)

print("🔄 Starting stream...\n")

for line in response.iter_lines():
    if not line:
        continue

    decoded = line.decode("utf-8")
    if decoded.startswith("data: "):
        event = json.loads(decoded.replace("data: ", "", 1))

        event_type = event.get("type")
        data = event.get("data", {})

        if event_type == "status":
            print(f"✓ {data['message']}")

        elif event_type == "update":
            print(f"🧠 {data['node']} → {data['status']}")

        elif event_type == "message":
            token = data.get("token", "")
            if token:
                print(token, end="", flush=True)

        elif event_type == "error":
            print(f"\n❌ Error: {data['message']}")
```

Run:
```bash
python test_streaming.py
```

---

## 📝 Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Streaming** | Single stream (nodes only) | Dual stream (nodes + tokens) |
| **Thought Trace** | None | Live node execution trace |
| **Token Rendering** | Blocking wait | Incremental token-by-token |
| **Latency** | High (wait for full response) | Low (tokens arrive immediately) |
| **UX** | Static response box | Dynamic thought trace + progressive response |
| **LLM Visibility** | Black box | Clear thought process visible |

---

**Next Steps**: Run the system and watch the dual-stream SSE events in real-time! 🚀
