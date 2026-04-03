from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
import uvicorn
import json
from fastapi.responses import StreamingResponse
from main import graph as langgraph_app # This is your Compiled Graph
from langchain_core.messages import AIMessageChunk
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# This is the actual server
backend = FastAPI()

USERS_DB = {
    "mark_walter": "password123",    # TWG Owner
    "atharv_admin": "nyu2025",      # You
    "chelsea_scout": "football24"   # Scout
}

# ============================================================================
# SSE UTILITIES
# ============================================================================

def format_sse_event(event_type: str, data: dict) -> str:
    """
    Format event as Server-Sent Events (SSE).

    Format: data: <json>\n\n
    """
    sse_event = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }
    return f"data: {json.dumps(sse_event)}\n\n"


# ============================================================================
# AUTHENTICATION
# ============================================================================

# Matches your Frontend's login attempt
@backend.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user_password = USERS_DB.get(form_data.username)

    if not user_password or form_data.password != user_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In a real app, we'd generate a real JWT token here.
    # For your demo, we just return a success string.
    return {"access_token": f"session_for_{form_data.username}", "token_type": "bearer"}


# ============================================================================
# CHAT REQUEST MODEL
# ============================================================================

class ChatRequest(BaseModel):
    query: str


# ============================================================================
# DUAL-STREAM SSE ENDPOINT
# ============================================================================

@backend.post("/chat")
async def chat(request: ChatRequest):
    """
    Dual-stream SSE endpoint with updates (node trace) + messages (tokens).

    Uses astream() with stream_mode=["updates", "messages"] to emit:
    1. "update" events: Node execution trace (thought process)
    2. "message" events: LLM token chunks (incremental response)
    """
    def event_generator():
        # Initial connection message
        yield format_sse_event("status", {"message": "🚀 Connected to TWG Server. Initializing..."})

        initial_state = {
            "messages": [],
            "query": request.query,
            "user_role": "user",
            "domain_detected": "",
            "final_response": ""
        }

        try:
            # Async streaming with dual modes: updates (node trace) + messages (tokens)
            for stream_type, data in langgraph_app.stream(
                initial_state,
                stream_mode=["updates", "messages"]
            ):

                # ================================================================
                # STREAM 1: UPDATES (Node Execution Trace)
                # ================================================================
                if stream_type == "updates":
                    # data = {node_name: {state_update}}
                    for node_name, node_state in data.items():
                        logger.info(f"🧠 Node: {node_name}")

                        # Emit node update event (thought trace)
                        yield format_sse_event(
                            "update",
                            {
                                "node": node_name,
                                "status": "executing",
                                "timestamp": datetime.utcnow().isoformat()
                            }
                        )

                # ================================================================
                # STREAM 2: MESSAGES (Token Stream)
                # ================================================================
                elif stream_type == "messages":
                    # data = [AIMessageChunk(...), AIMessageChunk(...), ...]
                    for message_chunk in data:
                        if isinstance(message_chunk, AIMessageChunk):
                            token = message_chunk.content

                            # Emit token event for incremental rendering
                            if token:
                                yield format_sse_event(
                                    "message",
                                    {
                                        "token": token,
                                        "is_final": False
                                    }
                                )

            # Signal completion
            yield format_sse_event("message", {"token": "", "is_final": True})
            logger.info("✅ Stream completed")

        except Exception as e:
            logger.error(f"❌ Stream error: {str(e)}")
            yield format_sse_event("error", {"message": str(e)})

    # Return the stream with the correct SSE media type
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
        }
    )

if __name__ == "__main__":
    # Runs the server on port 8000
    uvicorn.run(backend, host="0.0.0.0", port=8000)