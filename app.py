"""Entrada: python app.py"""
from __future__ import annotations

import uvicorn

from config import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("main:app", host=s.host, port=s.port, reload=False, log_level="info")
