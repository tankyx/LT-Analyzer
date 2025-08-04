#!/bin/bash

# Frontend Test Runner Script
# This script runs the frontend tests with various options

set -e  # Exit on error

echo "🧪 Frontend Test Runner"
echo "====================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Change to frontend directory
cd "$(dirname "$0")/../racing-analyzer"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}📦 Installing dependencies...${NC}"
    npm install
fi

# Parse command line arguments
MODE="default"
if [ "$1" = "watch" ]; then
    MODE="watch"
elif [ "$1" = "coverage" ]; then
    MODE="coverage"
elif [ "$1" = "ci" ]; then
    MODE="ci"
elif [ "$1" = "help" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Usage: $0 [mode]"
    echo ""
    echo "Modes:"
    echo "  (default)  Run tests once"
    echo "  watch      Run tests in watch mode"
    echo "  coverage   Run tests with coverage report"
    echo "  ci         Run tests in CI mode (with coverage, no watch)"
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  $0 watch"
    echo "  $0 coverage"
    exit 0
fi

# Run tests based on mode
case $MODE in
    "watch")
        echo -e "${GREEN}🔄 Running tests in watch mode...${NC}"
        npm run test:watch
        ;;
    "coverage")
        echo -e "${GREEN}📊 Running tests with coverage...${NC}"
        npm run test:coverage
        echo ""
        echo -e "${GREEN}✅ Coverage report generated!${NC}"
        echo "View HTML report: racing-analyzer/coverage/lcov-report/index.html"
        ;;
    "ci")
        echo -e "${GREEN}🤖 Running tests in CI mode...${NC}"
        CI=true npm test -- --coverage --watchAll=false
        ;;
    *)
        echo -e "${GREEN}🧪 Running tests...${NC}"
        npm test -- --watchAll=false
        ;;
esac

# Check exit code
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
else
    echo -e "${RED}❌ Some tests failed!${NC}"
    exit 1
fi