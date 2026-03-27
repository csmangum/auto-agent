#!/bin/bash
# Extract route sections from claims.py by line numbers
# This uses sed to extract specific line ranges

CLAIMS_FILE="src/claim_agent/api/routes/claims.py"
ROUTES_DIR="src/claim_agent/api/routes"

# First, let me find exact line numbers for each route function
# by searching for the @router decorators and their corresponding functions

echo "Analyzing $CLAIMS_FILE for route boundaries..."

# Use grep to find all @router lines with line numbers
grep -n "^@router\." "$CLAIMS_FILE" > /tmp/router_lines.txt

echo "Found $(wc -l < /tmp/router_lines.txt) routes"
echo ""
echo "Route decorator line numbers:"
cat /tmp/router_lines.txt | head -20
