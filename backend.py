from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
import uvicorn
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
    try:
        # This is where the magic happens. 
        # We pass the Streamlit query INTO your LangGraph logic.
        initial_state = {"query": request.query}
        result = langgraph_app.invoke(initial_state)
        
        # We send the LangGraph result back to the Streamlit UI
        return {
            "reply": result["final_response"],
            "domain": result.get("domain_detected", "F1 Sector")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph Error: {str(e)}")

if __name__ == "__main__":
    # Runs the server on port 8000
    uvicorn.run(backend, host="0.0.0.0", port=8000)