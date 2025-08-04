# Test Scripts Documentation

This directory contains various scripts to help run and manage tests for the LT-Analyzer project.

## Quick Start

From the project root directory:

```bash
# Run all tests
./test.sh

# Run with coverage
./test.sh --coverage

# Using make
make test
```

## Available Scripts

### test.sh (Project Root)
Simple wrapper that calls the main test runner.

```bash
./test.sh              # Run all tests
./test.sh --coverage   # Run with coverage
./test.sh --help       # Show help
```

### scripts/test-all.sh
Main test orchestrator that runs both frontend and backend tests.

```bash
./scripts/test-all.sh              # Run all tests
./scripts/test-all.sh --coverage   # Run with coverage reports
./scripts/test-all.sh --verbose    # Run with verbose output
./scripts/test-all.sh --ci         # Run in CI mode
```

### scripts/test-frontend.sh
Frontend-specific test runner.

```bash
./scripts/test-frontend.sh          # Run tests once
./scripts/test-frontend.sh watch    # Run in watch mode
./scripts/test-frontend.sh coverage # Run with coverage
./scripts/test-frontend.sh ci       # Run in CI mode
```

### scripts/test-backend.sh
Backend-specific test runner with advanced options.

```bash
./scripts/test-backend.sh                    # Run all tests
./scripts/test-backend.sh coverage           # Run with coverage
./scripts/test-backend.sh verbose            # Run with -v flag
./scripts/test-backend.sh vv                 # Run with -vv flag
./scripts/test-backend.sh specific <path>    # Run specific test
./scripts/test-backend.sh markers unit       # Run tests by marker
./scripts/test-backend.sh failed             # Run only failed tests
```

Examples:
```bash
# Run specific test file
./scripts/test-backend.sh specific tests/test_api/test_race_endpoints.py

# Run specific test class
./scripts/test-backend.sh specific tests/test_api/test_race_endpoints.py::TestRaceDataEndpoint

# Run specific test method
./scripts/test-backend.sh specific tests/test_api/test_race_endpoints.py::TestRaceDataEndpoint::test_get_race_data_success
```

### scripts/check-test-env.sh
Verifies that the test environment is properly configured.

```bash
./scripts/check-test-env.sh
```

This will check:
- System requirements (Node.js, Python, etc.)
- Frontend test packages
- Backend test packages
- Configuration files
- Test directories

### scripts/install-hooks.sh
Installs git pre-commit hooks that run tests before commits.

```bash
./scripts/install-hooks.sh
```

After installation, tests will automatically run when you commit changes.
To skip temporarily: `git commit --no-verify`

## Using Make

The Makefile provides convenient shortcuts:

```bash
make test              # Run all tests
make test-frontend     # Run frontend tests only
make test-backend      # Run backend tests only
make test-coverage     # Run all tests with coverage
make test-watch        # Run frontend tests in watch mode
```

## CI/CD Integration

The project includes GitHub Actions workflow (`.github/workflows/tests.yml`) that:
- Runs on push to main/develop branches
- Runs on pull requests
- Tests multiple Node.js versions (18.x, 20.x)
- Tests multiple Python versions (3.10, 3.11, 3.12)
- Generates coverage reports
- Runs integration tests
- Verifies build output

## Tips

1. **Quick Test During Development**
   ```bash
   # Frontend watch mode
   make test-watch
   
   # Backend specific file
   ./scripts/test-backend.sh specific tests/test_api/test_race_endpoints.py
   ```

2. **Before Committing**
   ```bash
   ./test.sh --coverage
   ```

3. **Fix Test Environment Issues**
   ```bash
   ./scripts/check-test-env.sh
   make install  # Install all dependencies
   ```

4. **View Coverage Reports**
   - Frontend: `open racing-analyzer/coverage/lcov-report/index.html`
   - Backend: `open htmlcov/index.html`

## Troubleshooting

If tests fail to run:

1. Check environment setup:
   ```bash
   ./scripts/check-test-env.sh
   ```

2. Install missing dependencies:
   ```bash
   # Frontend
   cd racing-analyzer && npm install
   
   # Backend
   source racing-venv/bin/activate
   pip install -r requirements.txt
   pip install pytest pytest-cov pytest-asyncio pytest-mock
   ```

3. Make scripts executable:
   ```bash
   chmod +x scripts/*.sh test.sh
   ```