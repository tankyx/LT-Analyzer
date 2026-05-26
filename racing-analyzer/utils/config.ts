// API configuration
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

// WebSocket configuration
export const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:5000';

// Cloudflare Turnstile site key — empty in dev means the backend soft-passes too.
export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || '';

// When true, /register requires an invite code (closed beta).
export const INVITE_REQUIRED =
  (process.env.NEXT_PUBLIC_INVITE_REQUIRED ?? 'true').toLowerCase() !== 'false';
