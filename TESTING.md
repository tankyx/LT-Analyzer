# Testing Guide for LT-Analyzer

This document provides comprehensive information about the testing setup and procedures for both frontend and backend components of the LT-Analyzer project.

## Table of Contents
1. [Frontend Testing (Next.js/React)](#frontend-testing)
2. [Backend Testing (Python/Flask)](#backend-testing)
3. [Running Tests](#running-tests)
4. [Writing New Tests](#writing-new-tests)
5. [Test Coverage](#test-coverage)
6. [CI/CD Integration](#cicd-integration)

## Frontend Testing

### Test Framework
- **Jest**: JavaScript testing framework
- **React Testing Library**: For testing React components
- **Testing Library User Event**: For simulating user interactions

### Directory Structure
```
racing-analyzer/
├── __tests__/
│   ├── components/
│   │   └── RaceDashboard/
│   │       ├── RaceDashboard.test.tsx
│   │       └── StintPlanner.test.tsx
│   ├── services/
│   │   └── WebSocketService.test.ts
│   └── utils/
│       └── config.test.ts
├── jest.config.js
└── jest.setup.js
```

### Running Frontend Tests

```bash
cd racing-analyzer

# Run all tests
npm test

# Run tests in watch mode
npm run test:watch

# Run tests with coverage
npm run test:coverage

# Run specific test file
npm test -- StintPlanner.test.tsx
```

### Frontend Test Examples

#### Component Testing
```typescript
// Testing React components
test('renders StintPlanner component', () => {
  render(<StintPlanner {...defaultProps} />);
  expect(screen.getByText('Stint Planner')).toBeInTheDocument();
});

// Testing user interactions
test('saves data to localStorage when config changes', async () => {
  render(<StintPlanner {...defaultProps} />);
  
  const numStintsInput = screen.getByLabelText('Number of Stints:');
  await userEvent.clear(numStintsInput);
  await userEvent.type(numStintsInput, '5');

  await waitFor(() => {
    expect(mockLocalStorage.setItem).toHaveBeenCalled();
  });
});
```

#### Service Testing
```typescript
// Testing WebSocket service
test('connects to WebSocket server', () => {
  webSocketService.connect();
  
  expect(io).toHaveBeenCalledWith(expect.any(String), {
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
    transports: ['websocket', 'polling'],
  });
});
```

## Backend Testing

### Test Framework
- **pytest**: Python testing framework
- **pytest-asyncio**: For testing async code
- **pytest-cov**: For code coverage
- **pytest-mock**: For mocking

### Directory Structure
```
tests/
├── __init__.py
├── conftest.py          # Shared fixtures and configuration
├── test_api/
│   ├── __init__.py
│   ├── test_race_endpoints.py
│   └── test_websocket_events.py
└── test_websocket/
    ├── __init__.py
    └── test_apex_parser.py
```

### Running Backend Tests

```bash
# Activate virtual environment
source racing-venv/bin/activate

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_api/test_race_endpoints.py

# Run specific test class or method
pytest tests/test_api/test_race_endpoints.py::TestRaceDataEndpoint::test_get_race_data_success

# Run with coverage
pytest --cov=. --cov-report=html

# Run tests matching a pattern
pytest -k "test_update_monitoring"
```

### Backend Test Examples

#### API Endpoint Testing
```python
def test_get_race_data_success(client, mock_race_data):
    """Test successful retrieval of race data."""
    response = client.get('/api/race-data')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'teams' in data
    assert 'sessionInfo' in data
```

#### WebSocket Event Testing
```python
def test_connect_success(socket_client):
    """Test successful WebSocket connection."""
    assert socket_client.is_connected()
    received = socket_client.get_received()
    
    # Should receive initial race data on connect
    race_data_msg = next((msg for msg in received if msg['name'] == 'race_data_update'), None)
    assert race_data_msg is not None
```

#### Async Testing
```python
@pytest.mark.asyncio
async def test_handle_message_grid_update(parser):
    """Test handling grid update messages."""
    message = json.dumps({
        'cmd': 'grid_update',
        'row': 'row1',
        'col': 0,
        'value': '1'
    })
    
    await parser.handle_message(message)
    assert parser.grid_data['row1']['Position'] == '1'
```

## Writing New Tests

### Frontend Test Guidelines

1. **Component Tests**: Test component rendering, user interactions, and state changes
2. **Service Tests**: Test API calls, WebSocket connections, and data transformations
3. **Mock External Dependencies**: Use Jest mocks for API calls and WebSocket connections
4. **Test Accessibility**: Include tests for keyboard navigation and screen readers

### Backend Test Guidelines

1. **Unit Tests**: Test individual functions and methods in isolation
2. **Integration Tests**: Test API endpoints with mocked dependencies
3. **Async Tests**: Use `pytest.mark.asyncio` for async functions
4. **Fixtures**: Use pytest fixtures for reusable test data and mocks

### Best Practices

1. **Descriptive Test Names**: Use clear, descriptive names that explain what is being tested
2. **Arrange-Act-Assert**: Structure tests with clear setup, execution, and verification phases
3. **Test Edge Cases**: Include tests for error conditions and boundary values
4. **Keep Tests Independent**: Each test should be able to run in isolation
5. **Mock External Services**: Don't make real API calls or database connections in tests

## Test Coverage

### Frontend Coverage
```bash
# Generate coverage report
npm run test:coverage

# View HTML coverage report
open coverage/lcov-report/index.html
```

### Backend Coverage
```bash
# Generate coverage report
pytest --cov=. --cov-report=html

# View HTML coverage report
open htmlcov/index.html
```

### Coverage Goals
- Aim for at least 80% code coverage
- Focus on critical business logic
- Don't test implementation details
- Prioritize testing user-facing functionality

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Tests

on: [push, pull_request]

jobs:
  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-node@v2
        with:
          node-version: '18'
      - run: cd racing-analyzer && npm ci
      - run: cd racing-analyzer && npm test

  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest
```

## Troubleshooting

### Common Frontend Issues
- **Module not found**: Check import paths and tsconfig.json aliases
- **Act warnings**: Wrap state updates in `waitFor` or `act`
- **Mock not working**: Ensure mocks are set up before imports

### Common Backend Issues
- **Import errors**: Check PYTHONPATH and __init__.py files
- **Database errors**: Ensure database mocks are properly configured
- **Async test failures**: Use proper async/await syntax and fixtures

## Continuous Improvement

1. **Regular Test Reviews**: Review and update tests as features change
2. **Performance Testing**: Add performance benchmarks for critical paths
3. **Integration Testing**: Add end-to-end tests for complete user workflows
4. **Security Testing**: Include tests for authentication and authorization