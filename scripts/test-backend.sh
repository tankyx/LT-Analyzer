#!/bin/bash

# Backend Test Runner Script
# This script runs the backend tests with various options

set -e  # Exit on error

echo "🧪 Backend Test Runner"
echo "===================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Change to project root directory
cd "$(dirname "$0")/.."

# Check if virtual environment exists
if [ ! -d "racing-venv" ]; then
    echo -e "${YELLOW}🐍 Creating virtual environment...${NC}"
    python3 -m venv racing-venv
fi

# Activate virtual environment
echo -e "${BLUE}🔧 Activating virtual environment...${NC}"
source racing-venv/bin/activate

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${YELLOW}📦 Installing test dependencies...${NC}"
    pip install pytest pytest-cov pytest-asyncio pytest-mock
fi

# Parse command line arguments
MODE="default"
ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        coverage)
            MODE="coverage"
            shift
            ;;
        verbose|v)
            ARGS="$ARGS -v"
            shift
            ;;
        vv)
            ARGS="$ARGS -vv"
            shift
            ;;
        specific)
            MODE="specific"
            shift
            if [ -z "$1" ]; then
                echo -e "${RED}Error: Please specify a test file or pattern${NC}"
                exit 1
            fi
            TEST_TARGET="$1"
            shift
            ;;
        markers|m)
            MODE="markers"
            shift
            if [ -z "$1" ]; then
                echo -e "${RED}Error: Please specify a marker${NC}"
                exit 1
            fi
            MARKER="$1"
            shift
            ;;
        failed|f)
            ARGS="$ARGS --lf"
            shift
            ;;
        help|-h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  (default)         Run all tests"
            echo "  coverage          Run tests with coverage report"
            echo "  verbose|v         Run with verbose output (-v)"
            echo "  vv                Run with very verbose output (-vv)"
            echo "  specific <path>   Run specific test file or pattern"
            echo "  markers|m <mark>  Run tests with specific marker"
            echo "  failed|f          Run only failed tests from last run"
            echo ""
            echo "Examples:"
            echo "  $0"
            echo "  $0 coverage"
            echo "  $0 verbose"
            echo "  $0 specific tests/test_api/test_race_endpoints.py"
            echo "  $0 specific tests/test_api/test_race_endpoints.py::TestRaceDataEndpoint"
            echo "  $0 markers unit"
            echo "  $0 failed"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
done

# Run tests based on mode
case $MODE in
    "coverage")
        echo -e "${GREEN}📊 Running tests with coverage...${NC}"
        pytest $ARGS --cov=. --cov-report=term-missing --cov-report=html
        echo ""
        echo -e "${GREEN}✅ Coverage report generated!${NC}"
        echo "View HTML report: htmlcov/index.html"
        ;;
    "specific")
        echo -e "${GREEN}🎯 Running specific tests: $TEST_TARGET${NC}"
        pytest $ARGS "$TEST_TARGET"
        ;;
    "markers")
        echo -e "${GREEN}🏷️  Running tests with marker: $MARKER${NC}"
        pytest $ARGS -m "$MARKER"
        ;;
    *)
        echo -e "${GREEN}🧪 Running all tests...${NC}"
        pytest $ARGS
        ;;
esac

# Check exit code
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
else
    echo -e "${RED}❌ Some tests failed!${NC}"
    exit $EXIT_CODE
fi