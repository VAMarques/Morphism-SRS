#!/usr/bin/env sh
# ==============================================================================
# Morphism SRS - Setup & Launch Script (macOS / Linux)
# Creates a Python virtual environment, installs dependencies, & runs the app.
# ==============================================================================

set -e

# ANSI Color Codes
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "${BLUE}====================================================${NC}"
echo "${BLUE}       ⚡ Morphism SRS Setup & Launcher ⚡          ${NC}"
echo "${BLUE}====================================================${NC}"

# Detect OS
OS_NAME=$(uname -s)
echo "${YELLOW}Detected OS:${NC} ${OS_NAME}"

# Detect Python 3 executable
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "${RED}Error: Python 3 is not installed or not found in PATH.${NC}"
    echo "Please install Python 3 (https://www.python.org/downloads/) and try again."
    exit 1
fi

echo "${GREEN}Using Python:${NC} $($PYTHON_BIN --version)"

# Create virtual environment if not present
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "${YELLOW}Creating Python virtual environment in ${VENV_DIR}...${NC}"
    $PYTHON_BIN -m venv "$VENV_DIR"
    echo "${GREEN}Virtual environment created successfully!${NC}"
fi

# Activate virtual environment
echo "${YELLOW}Activating virtual environment...${NC}"
. "$VENV_DIR/bin/activate"

# Upgrade pip and install requirements
echo "${YELLOW}Installing dependencies from requirements.txt...${NC}"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo "${GREEN}Dependencies installed successfully!${NC}"
echo "${BLUE}====================================================${NC}"
echo "${GREEN}🚀 Launching Morphism SRS...${NC}"
echo "${BLUE}====================================================${NC}"

# Run main application
python main.py
