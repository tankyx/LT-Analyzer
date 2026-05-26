'use client';

import { useEffect, useRef } from 'react';
import { TURNSTILE_SITE_KEY } from '../../utils/config';

interface Props {
  onVerify: (token: string) => void;
  /** Optional callback fired when the user's token expires or fails. */
  onExpire?: () => void;
}

declare global {
  interface Window {
    turnstile?: {
      render: (
        el: HTMLElement,
        opts: { sitekey: string; callback: (t: string) => void; 'expired-callback'?: () => void; 'error-callback'?: () => void },
      ) => string;
      remove: (id: string) => void;
    };
  }
}

/**
 * Lightweight wrapper around the Cloudflare Turnstile widget. The
 * Turnstile JS itself is loaded once in app/layout.tsx. If no site key
 * is configured (dev mode), we render nothing and immediately resolve a
 * placeholder token — the backend soft-passes when TURNSTILE_SECRET_KEY is
 * also empty, so this keeps the dev experience friction-free.
 */
export default function TurnstileWidget({ onVerify, onExpire }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  // Keep latest callbacks in refs so the mount effect never re-runs on parent re-renders.
  // (A new arrow function from the parent must not trigger widget reset / loop.)
  const onVerifyRef = useRef(onVerify);
  const onExpireRef = useRef(onExpire);
  onVerifyRef.current = onVerify;
  onExpireRef.current = onExpire;

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) {
      // Dev mode: short-circuit with a placeholder token.
      onVerifyRef.current('dev-no-turnstile');
      return;
    }
    let cancelled = false;

    const tryRender = () => {
      if (cancelled) return;
      if (!window.turnstile || !ref.current) {
        window.setTimeout(tryRender, 100);
        return;
      }
      widgetIdRef.current = window.turnstile.render(ref.current, {
        sitekey: TURNSTILE_SITE_KEY,
        callback: (token: string) => onVerifyRef.current(token),
        'expired-callback': () => onExpireRef.current?.(),
        'error-callback': () => onExpireRef.current?.(),
      });
    };
    tryRender();

    return () => {
      cancelled = true;
      if (widgetIdRef.current && window.turnstile) {
        try {
          window.turnstile.remove(widgetIdRef.current);
        } catch {
          // best-effort cleanup
        }
      }
    };
    // Intentionally empty deps: render once, capture latest callbacks via refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!TURNSTILE_SITE_KEY) return null;
  return <div ref={ref} className="cf-turnstile" />;
}
