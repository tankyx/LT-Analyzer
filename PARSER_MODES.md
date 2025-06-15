# Parser Modes in LT-Analyzer

LT-Analyzer now supports three different parser modes for collecting race data from Apex Timing websites:

## Available Modes

### 1. **Hybrid Mode** (Recommended) 🔄
- **Description**: Automatically detects and uses the best available method
- **How it works**: 
  - First tries to detect WebSocket connections on the timing page
  - If WebSocket is found and working, uses it for real-time updates
  - Falls back to Playwright browser scraping if WebSocket is not available
- **Advantages**: 
  - Best of both worlds - fast when possible, reliable always
  - No manual configuration needed
- **Use when**: You want the system to automatically choose the best method

### 2. **WebSocket Mode** ⚡
- **Description**: Forces direct WebSocket connection only
- **How it works**: 
  - Connects directly to the timing server's WebSocket
  - Receives real-time updates with minimal latency (~100ms)
  - Will fail if the timing page doesn't support WebSocket
- **Advantages**: 
  - Lowest latency updates
  - Minimal resource usage (no browser needed)
  - Most efficient for long-running sessions
- **Use when**: You know the timing page supports WebSocket and want maximum performance

### 3. **Playwright Mode** 🌐
- **Description**: Traditional browser-based scraping
- **How it works**: 
  - Uses a headless browser to load and parse the timing page
  - Extracts data from the rendered HTML
  - Updates every 5 seconds
- **Advantages**: 
  - Works with any Apex Timing page
  - Most compatible option
- **Use when**: WebSocket is not available or you need maximum compatibility

## How to Select a Parser Mode

1. When starting data collection, enter your timing URL
2. Select your preferred parser mode using the buttons:
   - **Hybrid** (Auto-detect) - Default and recommended
   - **WebSocket** (Direct) - For maximum performance
   - **Playwright** (Original) - For maximum compatibility
3. Click "Start Collection"

## Performance Comparison

| Mode | Update Latency | Resource Usage | Compatibility |
|------|---------------|----------------|---------------|
| WebSocket | ~100ms | Low | Limited to WebSocket-enabled pages |
| Hybrid | ~100ms to 5s | Medium | Universal |
| Playwright | ~5s | High | Universal |

## Troubleshooting

- **WebSocket mode fails to start**: The timing page doesn't support WebSocket. Use Hybrid or Playwright mode instead.
- **No data updates**: Check that the timing URL is correct and the race is active.
- **High resource usage**: If using Playwright mode, this is normal as it runs a full browser.