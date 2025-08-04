import { API_BASE_URL, WS_BASE_URL } from '@/utils/config';

describe('Config utilities', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...originalEnv };
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  test('uses default API_BASE_URL when env variable is not set', () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    jest.isolateModules(() => {
      const { API_BASE_URL } = require('@/utils/config');
      expect(API_BASE_URL).toBe('http://localhost:5000');
    });
  });

  test('uses environment variable for API_BASE_URL when set', () => {
    process.env.NEXT_PUBLIC_API_URL = 'https://api.example.com';
    jest.isolateModules(() => {
      const { API_BASE_URL } = require('@/utils/config');
      expect(API_BASE_URL).toBe('https://api.example.com');
    });
  });

  test('uses default WS_BASE_URL when env variable is not set', () => {
    delete process.env.NEXT_PUBLIC_WS_URL;
    jest.isolateModules(() => {
      const { WS_BASE_URL } = require('@/utils/config');
      expect(WS_BASE_URL).toBe('ws://localhost:5000');
    });
  });

  test('uses environment variable for WS_BASE_URL when set', () => {
    process.env.NEXT_PUBLIC_WS_URL = 'wss://ws.example.com';
    jest.isolateModules(() => {
      const { WS_BASE_URL } = require('@/utils/config');
      expect(WS_BASE_URL).toBe('wss://ws.example.com');
    });
  });
});