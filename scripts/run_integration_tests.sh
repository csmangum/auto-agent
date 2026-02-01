#!/bin/bash
# Integration Test Runner Script
# 
# This script runs integration tests for the claim agent system.
# It supports different test modes and configurations.
#
# Usage:
#   ./scripts/run_integration_tests.sh [options]
#
# Options:
#   --all          Run all integration tests
#   --fast         Run fast integration tests only (skip slow/LLM tests)
#   --llm          Run tests that require LLM API access
#   --rag          Run RAG-specific tests
#   --db           Run database tests
#   --tools        Run tools tests
#   --mcp          Run MCP server tests
#   --workflow     Run workflow tests
#   --coverage     Generate coverage report
#   -v, --verbose  Verbose output
#   -h, --help     Show this help message

set -euo pipefail

# Verify bash is available (for CI environments)
if [ -z "${BASH_VERSION:-}" ]; then
    echo "Error: This script requires bash"
    exit 1
fi

# Default values
PYTEST_ARGS=()
COVERAGE=""
VERBOSE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --all)
            PYTEST_ARGS+=("tests/integration/")
            shift
            ;;
        --fast)
            PYTEST_ARGS+=("tests/integration/" "-m" "integration and not slow and not llm")
            shift
            ;;
        --llm)
            PYTEST_ARGS+=("tests/integration/" "-m" "llm")
            shift
            ;;
        --rag)
            PYTEST_ARGS+=("tests/integration/test_rag.py")
            shift
            ;;
        --db)
            PYTEST_ARGS+=("tests/integration/test_database.py")
            shift
            ;;
        --tools)
            PYTEST_ARGS+=("tests/integration/test_tools.py")
            shift
            ;;
        --mcp)
            PYTEST_ARGS+=("tests/integration/test_mcp.py")
            shift
            ;;
        --workflow)
            PYTEST_ARGS+=("tests/integration/test_workflow.py")
            shift
            ;;
        --coverage)
            COVERAGE="--cov=claim_agent --cov-report=term-missing --cov-report=html"
            shift
            ;;
        -v|--verbose)
            VERBOSE="-v"
            shift
            ;;
        -h|--help)
            head -30 "$0" | tail -25
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Default to all integration tests if no specific tests selected
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_ARGS=("tests/integration/" "-m" "integration")
fi

# Change to project root
cd "$(dirname "$0")/.."

# Check for virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -d "venv" ]; then
        echo "Activating virtual environment..."
        source venv/bin/activate
    elif [ -d ".venv" ]; then
        echo "Activating virtual environment..."
        source .venv/bin/activate
    else
        echo "Warning: No virtual environment detected. Proceeding with system Python."
    fi
fi

# Check for required dependencies
if ! python -c "import pytest" 2>/dev/null; then
    echo "Error: pytest not found. Install with: pip install pytest"
    exit 1
fi

# Display test configuration
echo "=========================================="
echo "Integration Test Runner"
echo "=========================================="
echo "Python: $(python --version)"
echo "Pytest: $(python -m pytest --version | head -1)"
echo ""
echo "Test configuration:"
echo "  OPENAI_API_KEY: ${OPENAI_API_KEY:+set}"
echo "  MOCK_DB_PATH: ${MOCK_DB_PATH:-data/mock_db.json}"
echo ""

# Run tests
echo "Running: pytest ${PYTEST_ARGS[*]} $COVERAGE $VERBOSE"
echo "=========================================="
python -m pytest "${PYTEST_ARGS[@]}" $COVERAGE $VERBOSE

echo ""
echo "=========================================="
echo "Integration tests completed!"
echo "=========================================="
