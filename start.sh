#!/bin/bash

# DTP-Transport Start Script
# Starts both backend and frontend for local development

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${SCRIPT_DIR}/../.venv"

echo "🚀 DTP - Deadline-aware Transport Protocol"
echo "==========================================="
echo ""

# Check for virtual environment
if [ ! -d "$VENV_PATH" ]; then
    echo "⚠️  Virtual environment not found at $VENV_PATH"
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_PATH"
fi

# Activate virtual environment
source "$VENV_PATH/bin/activate"

# Install backend dependencies
echo "📦 Installing backend dependencies..."
pip install -q -r "$SCRIPT_DIR/backend/requirements.txt"

# Check if frontend dependencies are installed
if [ ! -d "$SCRIPT_DIR/frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd "$SCRIPT_DIR/frontend"
    npm install
    cd "$SCRIPT_DIR"
fi

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping services..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend
echo ""
echo "🖥️  Starting backend API on http://localhost:8000"
cd "$SCRIPT_DIR/backend"
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd "$SCRIPT_DIR"

# Wait for backend to start
sleep 2

# Start frontend
echo "🌐 Starting frontend on http://localhost:5173"
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

echo ""
echo "✅ DTP Dashboard ready!"
echo ""
echo "   📊 Dashboard: http://localhost:5173"
echo "   🔌 API:       http://localhost:8000"
echo "   📚 API Docs:  http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID
