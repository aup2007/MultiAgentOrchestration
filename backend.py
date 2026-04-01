from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
import uvicorn
import json
from fastapi.responses import StreamingResponse
from main import graph as langgraph_app # This is your Compiled Graph

# This is the actual server
backend = FastAPI()

USERS_DB = {
    "mark_walter": "password123",    # TWG Owner
    "atharv_admin": "nyu2025",      # You
    "chelsea_scout": "football24"   # Scout
}

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

# Matches your Frontend's 'requests.post' chat call
class ChatRequest(BaseModel):
    query: str

@backend.post("/chat")
async def chat(request: ChatRequest):
    def event_generator():
        yield f"data: {json.dumps({'status': 'Connected to TWG Server. Initializing...'})}\n\n"
        initial_state = {"query": request.query}
        
        try:
            # .stream() yields updates as each node finishes
            for output in langgraph_app.stream(initial_state):
                for node_name, state_update in output.items():
                    # Format the payload for Server-Sent Events
                    payload = {
                        "node": node_name,
                        "status": f"Finished processing in {node_name}...",
                        "reply": state_update.get("final_response", ""),
                        "domain": state_update.get("domain_detected", "")
                    }
                    # SSE format requires "da ta: <json_string>\n\n"
                    yield f"data: {json.dumps(payload)}\n\n"
                    
        except Exception as e:
            error_payload = {"error": str(e)}
            yield f"data: {json.dumps(error_payload)}\n\n"

    # Return the stream with the correct SSE media type
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    # Runs the server on port 8000
    uvicorn.run(backend, host="0.0.0.0", port=8000)