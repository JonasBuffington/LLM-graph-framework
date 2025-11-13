#!/bin/bash

# Start the Uvicorn server in the foreground
# It will use the PORT environment variable provided by Render
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}