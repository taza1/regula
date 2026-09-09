#!/usr/bin/env python3
"""Startup script for the research system."""

import sys
import os
import asyncio
import uvicorn
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.config import get_api_config


async def main():
    """Start the research system API server."""
    config = get_api_config()
    
    print("=" * 70)
    print("Multi-Agent Research System - Starting")
    print("=" * 70)
    print(f"API Version: {config.api_version}")
    print(f"Host: {config.host}")
    print(f"Port: {config.port}")
    print(f"Documentation: http://{config.host}:{config.port}/docs")
    print("=" * 70)
    
    # Start FastAPI server
    uvicorn.run(
        "src.main:app",
        host=config.host,
        port=config.port,
        reload=True,  # Set to False in production
        log_level="info"
    )


if __name__ == "__main__":
    asyncio.run(main())
