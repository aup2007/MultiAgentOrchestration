"""
TWG Sports Intelligence Platform - FastAPI Backend with Dual-Stream SSE
=========================================================================

Implements real-time streaming with two parallel event streams:
1. "updates" stream: Node execution trace (thought process)
2. "messages" stream: LLM token chunks (incremental text)

Uses Server-Sent Events (SSE) format:
    data: <json>\n\n

This enables real-time UX with live node status and progressive token rendering.
"""

import os
import json
import asyncio
from typing import AsyncIterator, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessageChunk
from langgraph.graph import StateGraph, END, START
from state import AgentState
from f1_agent import f1_sector_graph
from main import supervisor_router  # Import the LLM router
import logging
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends, status


USERS_DB = {
    "mark_walter": "password123",    # TWG Owner
    "atharv_admin": "nyu2025",      # You
    "chelsea_scout": "football24"   # Scout
}

load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI(title="TWG Sports Intelligence Platform - Streaming")

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class ChatRequest(BaseModel):
    """User chat message."""
    query: str
    user_role: str = "user"


class SSEEvent(BaseModel):
    """Structured SSE event."""
    type: str  # "update" or "message"
    timestamp: str
    data: dict


# ============================================================================
# SSE UTILITIES
# ============================================================================

def format_sse_event(event_type: str, data: dict) -> str:
    """
    Format an event as Server-Sent Events (SSE).

    SSE Format:
        data: <json>\n\n

    Args:
        event_type: "update" or "message"
        data: Event payload

    Returns:
        SSE-formatted string ready for transmission
    """
    sse_event = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }
    json_str = json.dumps(sse_event)
    return f"data: {json_str}\n\n"


def emit_update(node_name: str, status: str = "executing") -> str:
    """
    Emit a node update event (thought trace).

    Args:
        node_name: Name of the executing node
        status: "executing", "completed", or "error"

    Returns:
        SSE-formatted update event
    """
    return format_sse_event(
        event_type="update",
        data={
            "node": node_name,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


def emit_message(token: str, is_final: bool = False) -> str:
    """
    Emit a message token event (incremental rendering).

    Args:
        token: Single token or partial message chunk
        is_final: Whether this is the final token/message

    Returns:
        SSE-formatted message event
    """
    return format_sse_event(
        event_type="message",
        data={
            "token": token,
            "is_final": is_final
        }
    )


# ============================================================================
# STREAMING GENERATORS
# ============================================================================

async def stream_chat_agentic(
    query: str,
    user_role: str = "user"
) -> AsyncIterator[str]:
    """
    Stream response from agentic graph with dual-stream output.

    Uses LangGraph's astream() with stream_mode=["updates", "messages"]
    to capture:
    1. Node execution trace (updates stream)
    2. LLM token chunks (messages stream)

    Emits SSE events in real-time.

    Args:
        query: User's natural language query
        user_role: Role of user ("user", "scout", "admin")

    Yields:
        SSE-formatted event strings
    """
    logger.info(f"Starting stream for query: {query[:50]}...")

    # Initialize graph state
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "query": query,
        "user_role": user_role,
        "domain_detected": "",
        "final_response": ""
    }

    try:
        # Track active node for status display
        active_node = None
        final_text_sent = False

        # Main graph with router → sector subgraph
        main_graph = build_main_graph()

        # Stream with dual modes: updates (node trace) + messages (tokens)
        async for event in main_graph.astream(
            initial_state,
            stream_mode=["updates", "messages"]
        ):

            # Event format: (stream_type, data)
            stream_type, data = event

            # ================================================================
            # STREAM 1: UPDATES (Thought Trace)
            # ================================================================
            if stream_type == "updates":
                # data = {node_name: {state_update}}
                for node_name, node_state in data.items():
                    active_node = node_name
                    logger.info(f"Node: {node_name}")

                    # Emit node start event
                    yield emit_update(node_name, status="executing")

                    # Small delay to let frontend update UI
                    await asyncio.sleep(0.01)
                    if isinstance(node_state, dict):
                        final_response = node_state.get("final_response", "")
                        if final_response and not final_text_sent:
                            yield emit_message(final_response, is_final=False)
                            final_text_sent = True

            # ================================================================
            # STREAM 2: MESSAGES (Token Stream)
            # ================================================================
            elif stream_type == "messages":
                # data = [AIMessageChunk(...), AIMessageChunk(...), ...]
                for message_chunk in data:
                    if isinstance(message_chunk, AIMessageChunk):
                        token = message_chunk.content

                        # Emit token event
                        if token:
                            yield emit_message(token, is_final=False)

                        # Small delay for smooth streaming
                        await asyncio.sleep(0.001)

        # Signal completion
        logger.info("Stream completed successfully")
        yield emit_message("", is_final=True)

        # Final node completion status
        if active_node:
            yield emit_update(active_node, status="completed")

    except Exception as e:
        logger.error(f"Stream error: {str(e)}")
        yield format_sse_event(
            event_type="error",
            data={"message": str(e)}
        )


async def stream_sector_subgraph(
    sector: str,
    query: str,
    user_role: str = "user"
) -> AsyncIterator[str]:
    """
    Stream response from a specific sector subgraph.

    Useful for debugging or sector-specific analysis.

    Args:
        sector: "f1_sector", "baseball_sector", "football_sector"
        query: User query
        user_role: User role

    Yields:
        SSE-formatted events
    """
    logger.info(f"Streaming {sector} with query: {query[:50]}...")

    initial_state = {
        "query": query,
        "entities": {},
        "final_response": "",
        "db_query_result": "",
        "fetch_attempts": 0,
        "data_synced": False
    }

    try:
        # Map sector to subgraph
        sector_graphs = {
            "f1_sector": f1_sector_graph,
            # "baseball_sector": baseball_sector_graph,
            # "football_sector": football_sector_graph,
        }

        if sector not in sector_graphs:
            raise ValueError(f"Unknown sector: {sector}")

        sector_graph = sector_graphs[sector]

        # Stream the sector subgraph
        async for event in sector_graph.astream(
            initial_state,
            stream_mode=["updates", "messages"]
        ):
            stream_type, data = event

            if stream_type == "updates":
                for node_name, _ in data.items():
                    yield emit_update(f"{sector}::{node_name}", status="executing")
                    await asyncio.sleep(0.01)

            elif stream_type == "messages":
                for message_chunk in data:
                    if isinstance(message_chunk, AIMessageChunk):
                        token = message_chunk.content
                        if token:
                            yield emit_message(token, is_final=False)
                        await asyncio.sleep(0.001)

        yield emit_message("", is_final=True)

    except Exception as e:
        logger.error(f"Sector stream error: {str(e)}")
        yield format_sse_event(
            event_type="error",
            data={"message": str(e)}
        )


# ============================================================================
# FASTAPI ENDPOINTS
# ============================================================================

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user_password = USERS_DB.get(form_data.username)
    
    if not user_password or form_data.password != user_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {"access_token": f"session_for_{form_data.username}", "token_type": "bearer"}



@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    Stream chat response with dual-stream SSE (updates + messages).

    Returns a StreamingResponse that emits two types of events:
    1. "update" events: Node execution trace
    2. "message" events: LLM token chunks

    Example Usage (frontend):
        response = requests.post(
            "http://localhost:8000/chat/stream",
            json={"query": "Who is the fastest driver?"},
            stream=True
        )
        for line in response.iter_lines():
            if line:
                event = json.loads(line.decode('utf-8').replace('data: ', ''))
                if event['type'] == 'update':
                    print(f"→ {event['data']['node']}")
                elif event['type'] == 'message':
                    print(event['data']['token'], end='', flush=True)
    """
    return StreamingResponse(
        stream_chat_agentic(request.query, request.user_role),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
        }
    )


@app.post("/chat/stream/sector/{sector}")
async def chat_stream_sector(
    sector: str,
    request: ChatRequest
) -> StreamingResponse:
    """
    Stream chat response for a specific sector subgraph.

    Args:
        sector: "f1_sector", "baseball_sector", "football_sector"
        request: Chat request with query
    """
    return StreamingResponse(
        stream_sector_subgraph(sector, request.query, request.user_role),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/chat")
async def chat_non_streaming(request: ChatRequest) -> dict:
    """
    Fallback non-streaming endpoint (for testing/simple clients).

    Collects full response, returns as JSON.
    Less real-time UX, but simpler for basic consumption.
    """
    logger.info(f"Non-streaming chat: {request.query[:50]}...")

    initial_state = {
        "messages": [HumanMessage(content=request.query)],
        "query": request.query,
        "user_role": request.user_role,
        "domain_detected": "",
        "final_response": ""
    }

    try:
        main_graph = build_main_graph()
        final_state = main_graph.invoke(initial_state)

        return {
            "status": "success",
            "response": final_state.get("final_response", ""),
            "query": request.query,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Non-streaming error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "streaming_enabled": True
    }


# ============================================================================
# GRAPH BUILDER
# ============================================================================

def build_main_graph() -> StateGraph:
    """
    Build the main LangGraph with supervisor router.

    Reconstructed here to avoid circular imports.

    Returns:
        Compiled LangGraph
    """
    from main import (
        supervisor_router,
        DEFAULT_SECTOR,
        VALID_SECTORS
    )

    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("f1_sector", f1_sector_graph)
    # builder.add_node("baseball_sector", baseball_sector_graph)
    # builder.add_node("football_sector", football_sector_graph)

    # Routing from START
    builder.add_conditional_edges(
        START,
        supervisor_router,
        {
            "f1_sector": "f1_sector",
            # "baseball_sector": "baseball_sector",
            # "football_sector": "football_sector",
            END: END
        }
    )

    # Edges from sectors to END
    builder.add_edge("f1_sector", END)
    # builder.add_edge("baseball_sector", END)
    # builder.add_edge("football_sector", END)

    return builder.compile()


# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Startup event: log initialization."""
    logger.info("🚀 TWG Sports Intelligence Platform (Streaming) Started")
    logger.info("📡 Dual-stream SSE enabled (updates + messages)")
    logger.info("🔗 Endpoint: POST /chat/stream")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event: cleanup."""
    logger.info("🛑 TWG Sports Intelligence Platform Shutting Down")


# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)


# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disable for production
        log_level="info"
    )
