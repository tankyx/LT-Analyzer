#!/bin/bash

# Combined Test Runner Script
# This script runs both frontend and backend tests

set -e  # Exit on error

echo "🧪 LT-Analyzer Complete Test Suite"
echo "================================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Track overall status
FRONTEND_STATUS=0
BACKEND_STATUS=0

# Get script directory
SCRIPT_DIR="$(dirname "$0")"

# Parse command line arguments
COVERAGE=false
VERBOSE=false
CI_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage|-c)
            COVERAGE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --ci)
            CI_MODE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --coverage, -c   Run tests with coverage reports"
            echo "  --verbose, -v    Run tests with verbose output"
            echo "  --ci            Run in CI mode (no interactive output)"
            echo "  --help, -h      Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0"
            echo "  $0 --coverage"
            echo "  $0 --verbose --coverage"
            echo "  $0 --ci"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

# Function to run frontend tests
run_frontend_tests() {
    echo ""
    echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}🎨 Running Frontend Tests${NC}"
    echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    if [ "$CI_MODE" = true ]; then
        "$SCRIPT_DIR/test-frontend.sh" ci
    elif [ "$COVERAGE" = true ]; then
        "$SCRIPT_DIR/test-frontend.sh" coverage
    else
        "$SCRIPT_DIR/test-frontend.sh"
    fi
    
    FRONTEND_STATUS=$?
    return $FRONTEND_STATUS
}

# Function to run backend tests
run_backend_tests() {
    echo ""
    echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}🔧 Running Backend Tests${NC}"
    echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    BACKEND_ARGS=""
    if [ "$COVERAGE" = true ]; then
        BACKEND_ARGS="coverage"
    fi
    if [ "$VERBOSE" = true ]; then
        BACKEND_ARGS="$BACKEND_ARGS verbose"
    fi
    
    "$SCRIPT_DIR/test-backend.sh" $BACKEND_ARGS
    
    BACKEND_STATUS=$?
    return $BACKEND_STATUS
}

# Start time
START_TIME=$(date +%s)

# Run tests
echo -e "${YELLOW}🚀 Starting test suite...${NC}"

# Run frontend tests
run_frontend_tests || true

# Run backend tests
run_backend_tests || true

# Calculate elapsed time
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

# Summary
echo ""
echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📊 Test Summary${NC}"
echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $FRONTEND_STATUS -eq 0 ]; then
    echo -e "Frontend: ${GREEN}✅ PASSED${NC}"
else
    echo -e "Frontend: ${RED}❌ FAILED${NC}"
fi

if [ $BACKEND_STATUS -eq 0 ]; then
    echo -e "Backend:  ${GREEN}✅ PASSED${NC}"
else
    echo -e "Backend:  ${RED}❌ FAILED${NC}"
fi

echo -e "Time:     ${YELLOW}${MINUTES}m ${SECONDS}s${NC}"

# Coverage reports
if [ "$COVERAGE" = true ]; then
    echo ""
    echo -e "${BLUE}📈 Coverage Reports:${NC}"
    echo "  Frontend: racing-analyzer/coverage/lcov-report/index.html"
    echo "  Backend:  htmlcov/index.html"
fi

# Overall exit code
if [ $FRONTEND_STATUS -eq 0 ] && [ $BACKEND_STATUS -eq 0 ]; then
    echo ""
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}💥 Some tests failed!${NC}"
    exit 1
fi