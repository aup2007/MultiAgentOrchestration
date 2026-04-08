# Add this code to your backend.py for Railway health checks

# At the top level of backend.py, add these imports (should already exist):
# from fastapi import FastAPI, ...

# Then add these endpoints to your FastAPI app:

@backend.get("/health")
async def health_check():
    """Health check endpoint for Railway deployment."""
    return {
        "status": "healthy", 
        "service": "TWG Backend",
        "version": "2.0"
    }

@backend.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "TWG Sports Intelligence Platform Backend",
        "docs": "/docs",
        "version": "2.0"
    }

# These should be added to your existing backend.py file
