#!/bin/bash

# Test Environment Checker
# This script verifies that the test environment is properly set up

echo "🔍 Test Environment Checker"
echo "=========================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track overall status
STATUS=0

# Function to check command exists
check_command() {
    local cmd=$1
    local name=$2
    if command -v $cmd &> /dev/null; then
        echo -e "${GREEN}✓${NC} $name is installed ($(command -v $cmd))"
        return 0
    else
        echo -e "${RED}✗${NC} $name is not installed"
        return 1
    fi
}

# Function to check npm package
check_npm_package() {
    local package=$1
    local dir=$2
    if [ -d "$dir/node_modules/$package" ]; then
        echo -e "${GREEN}✓${NC} $package is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $package is not installed"
        return 1
    fi
}

# Function to check Python package
check_python_package() {
    local package=$1
    if python -c "import $package" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $package is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $package is not installed"
        return 1
    fi
}

echo ""
echo "System Requirements:"
echo "-------------------"

# Check Node.js
check_command node "Node.js" || STATUS=1
if command -v node &> /dev/null; then
    echo "  Version: $(node --version)"
fi

# Check npm
check_command npm "npm" || STATUS=1
if command -v npm &> /dev/null; then
    echo "  Version: $(npm --version)"
fi

# Check Python
check_command python3 "Python 3" || STATUS=1
if command -v python3 &> /dev/null; then
    echo "  Version: $(python3 --version)"
fi

# Check Git
check_command git "Git" || STATUS=1

echo ""
echo "Frontend Test Environment:"
echo "-------------------------"

# Check if in correct directory
cd "$(dirname "$0")/../racing-analyzer" 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Frontend directory exists"
    
    # Check package.json
    if [ -f "package.json" ]; then
        echo -e "${GREEN}✓${NC} package.json found"
    else
        echo -e "${RED}✗${NC} package.json not found"
        STATUS=1
    fi
    
    # Check node_modules
    if [ -d "node_modules" ]; then
        echo -e "${GREEN}✓${NC} node_modules directory exists"
        
        # Check specific test packages
        echo ""
        echo "Test packages:"
        check_npm_package "jest" "." || STATUS=1
        check_npm_package "@testing-library/react" "." || STATUS=1
        check_npm_package "@testing-library/jest-dom" "." || STATUS=1
        check_npm_package "@testing-library/user-event" "." || STATUS=1
    else
        echo -e "${YELLOW}⚠${NC} node_modules not found - run 'npm install'"
        STATUS=1
    fi
    
    # Check test directory
    if [ -d "__tests__" ]; then
        echo -e "${GREEN}✓${NC} __tests__ directory exists"
        TEST_COUNT=$(find __tests__ -name "*.test.*" -o -name "*.spec.*" | wc -l)
        echo "  Found $TEST_COUNT test files"
    else
        echo -e "${RED}✗${NC} __tests__ directory not found"
        STATUS=1
    fi
    
    cd ..
else
    echo -e "${RED}✗${NC} Frontend directory not found"
    STATUS=1
fi

echo ""
echo "Backend Test Environment:"
echo "------------------------"

# Check virtual environment
if [ -d "racing-venv" ]; then
    echo -e "${GREEN}✓${NC} Virtual environment exists"
    
    # Activate venv and check packages
    source racing-venv/bin/activate 2>/dev/null
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Virtual environment can be activated"
        
        echo ""
        echo "Test packages:"
        check_python_package "pytest" || STATUS=1
        check_python_package "pytest_cov" || STATUS=1
        check_python_package "pytest_asyncio" || STATUS=1
        check_python_package "pytest_mock" || STATUS=1
    else
        echo -e "${YELLOW}⚠${NC} Could not activate virtual environment"
        STATUS=1
    fi
else
    echo -e "${YELLOW}⚠${NC} Virtual environment not found - create with 'python3 -m venv racing-venv'"
    STATUS=1
fi

# Check test directory
if [ -d "tests" ]; then
    echo -e "${GREEN}✓${NC} tests directory exists"
    TEST_COUNT=$(find tests -name "test_*.py" -o -name "*_test.py" | wc -l)
    echo "  Found $TEST_COUNT test files"
else
    echo -e "${RED}✗${NC} tests directory not found"
    STATUS=1
fi

# Check test configuration files
echo ""
echo "Configuration Files:"
echo "-------------------"

files_to_check=(
    "pytest.ini"
    ".coveragerc"
    "racing-analyzer/jest.config.js"
    "racing-analyzer/jest.setup.js"
    ".github/workflows/tests.yml"
    "TESTING.md"
)

for file in "${files_to_check[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file exists"
    else
        echo -e "${YELLOW}⚠${NC} $file not found"
    fi
done

# Check test scripts
echo ""
echo "Test Scripts:"
echo "------------"

scripts_to_check=(
    "test.sh"
    "scripts/test-all.sh"
    "scripts/test-frontend.sh"
    "scripts/test-backend.sh"
)

for script in "${scripts_to_check[@]}"; do
    if [ -f "$script" ]; then
        if [ -x "$script" ]; then
            echo -e "${GREEN}✓${NC} $script exists and is executable"
        else
            echo -e "${YELLOW}⚠${NC} $script exists but is not executable"
            echo "  Run: chmod +x $script"
        fi
    else
        echo -e "${RED}✗${NC} $script not found"
        STATUS=1
    fi
done

# Summary
echo ""
echo "Summary:"
echo "--------"

if [ $STATUS -eq 0 ]; then
    echo -e "${GREEN}✅ Test environment is properly set up!${NC}"
    echo ""
    echo "You can run tests with:"
    echo "  ./test.sh                    # Run all tests"
    echo "  ./test.sh --coverage         # Run with coverage"
    echo "  make test                    # Using Makefile"
else
    echo -e "${RED}❌ Test environment has issues that need to be fixed${NC}"
    echo ""
    echo "To fix missing dependencies:"
    echo "  Frontend: cd racing-analyzer && npm install"
    echo "  Backend:  source racing-venv/bin/activate && pip install pytest pytest-cov pytest-asyncio pytest-mock"
fi

exit $STATUS