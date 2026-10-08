"""
Launch the NovaBank lab web app.

    python run.py            # http://127.0.0.1:8000
    HOST=0.0.0.0 PORT=8000 python run.py
"""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "web.app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
