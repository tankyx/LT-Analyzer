#!/bin/bash

# Install Git Hooks Script
# This script installs pre-commit hooks for the project

echo "🔧 Installing Git Hooks"
echo "====================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the git directory
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)

if [ -z "$GIT_DIR" ]; then
    echo "Error: Not in a git repository"
    exit 1
fi

# Create hooks directory if it doesn't exist
mkdir -p "$GIT_DIR/hooks"

# Create pre-commit hook
cat > "$GIT_DIR/hooks/pre-commit" << 'EOF'
#!/bin/bash

# Pre-commit hook for LT-Analyzer
# Runs tests before allowing commit

echo "🔍 Running pre-commit checks..."

# Get the project root directory
PROJECT_ROOT=$(git rev-parse --show-toplevel)

# Function to check if files of a certain type were changed
has_changes() {
    local pattern=$1
    git diff --cached --name-only | grep -q "$pattern"
}

# Check for frontend changes
if has_changes "racing-analyzer/.*\.\(ts\|tsx\|js\|jsx\)$"; then
    echo "📦 Frontend changes detected, running frontend tests..."
    cd "$PROJECT_ROOT/racing-analyzer"
    
    # Run linter
    npm run lint
    if [ $? -ne 0 ]; then
        echo "❌ Frontend linting failed. Please fix errors before committing."
        exit 1
    fi
    
    # Run tests
    npm test -- --watchAll=false --passWithNoTests
    if [ $? -ne 0 ]; then
        echo "❌ Frontend tests failed. Please fix failing tests before committing."
        exit 1
    fi
fi

# Check for backend changes
if has_changes ".*\.py$"; then
    echo "🐍 Backend changes detected, running backend tests..."
    cd "$PROJECT_ROOT"
    
    # Activate virtual environment if it exists
    if [ -f "racing-venv/bin/activate" ]; then
        source racing-venv/bin/activate
    fi
    
    # Run specific tests for changed files
    CHANGED_PY_FILES=$(git diff --cached --name-only | grep "\.py$" | grep -v "__pycache__")
    
    if [ -n "$CHANGED_PY_FILES" ]; then
        # Run pytest on test files related to changed files
        pytest tests/ -x --tb=short
        if [ $? -ne 0 ]; then
            echo "❌ Backend tests failed. Please fix failing tests before committing."
            exit 1
        fi
    fi
fi

echo "✅ All pre-commit checks passed!"
exit 0
EOF

# Make the hook executable
chmod +x "$GIT_DIR/hooks/pre-commit"

echo -e "${GREEN}✅ Pre-commit hook installed successfully!${NC}"
echo ""
echo "The hook will:"
echo "  - Run frontend linting and tests when .ts/.tsx/.js/.jsx files are changed"
echo "  - Run backend tests when .py files are changed"
echo ""
echo -e "${YELLOW}To skip the hook temporarily, use: git commit --no-verify${NC}"