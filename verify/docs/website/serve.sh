#!/bin/bash
# Tron Documentation Website - Quick Start Server

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Tron Documentation Website Server              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if port 8080 is available
if lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠ Port 8080 is already in use${NC}"
    echo -e "${YELLOW}Trying port 8081...${NC}"
    PORT=8081
else
    PORT=8080
fi

# Navigate to the website directory
cd "$SCRIPT_DIR"

echo -e "${GREEN}✓ Starting HTTP server on port ${PORT}${NC}"
echo ""
echo -e "${GREEN}Documentation available at:${NC}"
echo -e "  ${BLUE}http://localhost:${PORT}${NC}"
echo ""
echo -e "Press ${YELLOW}Ctrl+C${NC} to stop the server"
echo ""

# Start Python HTTP server
python3 -m http.server $PORT --bind 127.0.0.1

# Trap Ctrl+C for clean exit
trap 'echo -e "\n${GREEN}✓ Server stopped${NC}"; exit 0' INT
