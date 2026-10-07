'use client';

import React, { useEffect, useRef, useState } from 'react';
import { BarChart3, ChevronDown, Cpu, Flag, HelpCircle, LogOut, Moon, Sun } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';
import HelpDrawer from './HelpDrawer';

export interface AppBarUser {
  username: string;
  role?: string;
}

interface AppBarProps {
  trackName: string;
  sessionLabel?: string;
  sessionActive: boolean;
  /** Apex `light` field (flag state) when present. */
  flag?: string;
  /** Apex `dyn1` / `dyn2` free-text timers (remaining time, elapsed…). */
  timers?: string[];
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
  lastUpdate?: string;
  user: AppBarUser | null;
  onLogout: () => void;
  onOpenTracks: () => void;
  onOpenStats: () => void;
  /** Opens the device-token page (datalogger boards). */
  onOpenDevices?: () => void;
}

/** Colour role for a flag string coming from the timing feed. */
export function flagTone(flag: string | undefined): 'live' | 'alarm' | 'accent' | 'muted' {
  const f = (flag || '').toLowerCase();
  if (!f) return 'muted';
  if (f.includes('green')) return 'live';
  if (f.includes('red')) return 'alarm';
  if (f.includes('yellow') || f.includes('slow') || f.includes('safety')) return 'accent';
  return 'muted';
}

const FLAG_CLASSES = {
  live: 'bg-live/15 text-live',
  alarm: 'bg-alarm/15 text-alarm',
  accent: 'bg-accent/20 text-accent',
  muted: 'bg-muted/15 text-muted',
};

const AppBar: React.FC<AppBarProps> = ({
  trackName,
  sessionLabel,
  sessionActive,
  flag,
  timers = [],
  connectionStatus,
  lastUpdate,
  user,
  onLogout,
  onOpenTracks,
  onOpenStats,
  onOpenDevices,
}) => {
  const { isDark, toggleTheme } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const connDot =
    connectionStatus === 'connected'
      ? 'bg-live live-glow'
      : connectionStatus === 'connecting'
        ? 'bg-accent animate-live-blink'
        : 'bg-alarm';
  const connLabel =
    connectionStatus === 'connected'
      ? lastUpdate
        ? `Live · ${lastUpdate}`
        : 'Connected'
      : connectionStatus === 'connecting'
        ? 'Connecting…'
        : connectionStatus === 'error'
          ? 'Connection error'
          : 'Disconnected';

  const initials = (user?.username || '?').slice(0, 2).toUpperCase();
  const tone = flagTone(flag);
  const cleanTimers = timers.map((t) => (t || '').trim()).filter(Boolean);

  return (
    <>
    <header className="sticky top-0 z-40 h-14 border-b border-line bg-surface/80 backdrop-blur-md">
      <div className="h-full flex items-center gap-2 md:gap-4 px-3 md:px-5">
        {/* Brand (desktop only; the track button carries identity on phones) */}
        <div className="hidden md:flex items-center gap-2.5 shrink-0">
          <div className="w-[30px] h-[30px] rounded-[7px] accent-gradient accent-glow text-accent-ink font-cond font-bold text-[15px] flex items-center justify-center">
            LT
          </div>
          <span className="font-cond font-bold text-[19px] tracking-wide">LT-ANALYZER</span>
          <div className="w-px h-6 bg-line ml-1.5" />
        </div>

        {/* Track switcher */}
        <button
          type="button"
          onClick={onOpenTracks}
          aria-label="Switch track"
          className="flex items-center gap-2.5 h-10 md:h-9 pl-2.5 pr-3 rounded-lg border border-line bg-surface-2 min-w-0 max-w-full md:max-w-[420px] hover:border-muted/60 transition-colors"
        >
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${sessionActive ? 'bg-live live-glow' : 'bg-line'}`}
            data-testid="session-dot"
          />
          <span className="text-[15px] md:text-sm font-semibold truncate">{trackName || 'Select a track'}</span>
          {sessionLabel && (
            <span className="hidden sm:inline text-[13px] text-muted truncate">{sessionLabel}</span>
          )}
          <ChevronDown size={16} className="text-muted shrink-0" />
        </button>

        {/* Flag */}
        {flag && (
          <span
            className={`hidden sm:inline-flex items-center gap-1.5 h-8 px-2.5 rounded-full text-[13px] font-semibold ${FLAG_CLASSES[tone]}`}
          >
            <Flag size={14} />
            {flag}
          </span>
        )}

        <div className="flex-1 min-w-0" />

        {/* Timers from the feed */}
        {cleanTimers.length > 0 && (
          <div className="hidden lg:flex items-center gap-4">
            {cleanTimers.map((t, i) => (
              <span key={i} className="font-mono tabular text-[15px] font-semibold text-ink whitespace-nowrap">
                {t}
              </span>
            ))}
            <div className="w-px h-6 bg-line" />
          </div>
        )}

        {/* Connection */}
        <div className="hidden md:flex items-center gap-1.5 text-xs text-muted whitespace-nowrap" title={connLabel}>
          <span className={`w-2 h-2 rounded-full ${connDot}`} data-testid="conn-dot" />
          {connLabel}
        </div>

        {/* Driver stats */}
        <button
          type="button"
          onClick={onOpenStats}
          className="hidden md:flex items-center gap-1.5 h-9 px-2.5 rounded-lg text-sm font-semibold text-ink hover:bg-surface-2 transition-colors"
        >
          <BarChart3 size={16} />
          Driver stats
        </button>

        {/* Help */}
        <button
          type="button"
          onClick={() => setHelpOpen(true)}
          aria-label="Open dashboard guide"
          className="h-10 w-10 md:w-auto md:h-9 md:px-2.5 rounded-lg border border-line flex items-center justify-center gap-1.5 text-muted hover:text-ink hover:bg-surface-2 transition-colors"
        >
          <HelpCircle size={16} />
          <span className="hidden lg:inline text-xs font-semibold">Guide</span>
        </button>

        {/* Theme */}
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          className="h-10 w-10 md:w-auto md:h-9 md:px-2.5 rounded-lg border border-line flex items-center justify-center gap-1.5 text-muted hover:text-ink hover:bg-surface-2 transition-colors"
        >
          {isDark ? <Sun size={16} /> : <Moon size={16} />}
          <span className="hidden lg:inline text-xs font-semibold">{isDark ? 'Light' : 'Dark'}</span>
        </button>

        {/* User */}
        {user && (
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((o) => !o)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="Account menu"
              className="w-10 h-10 md:w-auto md:h-9 md:px-2 rounded-full bg-info text-white font-bold text-[13px] flex items-center justify-center gap-1"
            >
              {initials}
              <ChevronDown size={14} className="hidden md:inline" />
            </button>
            {menuOpen && (
              <div
                role="menu"
                onKeyDown={(e) => {
                  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
                  const items = Array.from(
                    menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') || [],
                  ).filter((el) => el.offsetParent !== null);
                  if (items.length === 0) return;
                  e.preventDefault();
                  const idx = items.indexOf(document.activeElement as HTMLButtonElement);
                  let next = 0;
                  if (e.key === 'ArrowDown') next = (idx + 1) % items.length;
                  else if (e.key === 'ArrowUp') next = (idx - 1 + items.length) % items.length;
                  else if (e.key === 'End') next = items.length - 1;
                  items[next].focus();
                }}
                className="absolute right-0 mt-2 w-56 rounded-xl border border-line bg-surface shadow-xl p-1.5 z-50"
              >
                <div className="px-3 py-2">
                  <div className="text-sm font-semibold truncate">{user.username}</div>
                  <div className="text-xs text-muted flex items-center gap-2">
                    {user.role === 'admin' ? 'Administrator' : 'Member'}
                  </div>
                </div>
                <div className="md:hidden border-t border-line my-1" />
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    onOpenStats();
                  }}
                  className="md:hidden w-full flex items-center gap-2 h-11 px-3 rounded-lg text-sm font-medium hover:bg-surface-2"
                >
                  <BarChart3 size={16} />
                  Driver stats
                </button>
                <div className="md:hidden flex items-center gap-2 h-11 px-3 text-xs text-muted">
                  <span className={`w-2 h-2 rounded-full ${connDot}`} />
                  {connLabel}
                </div>
                {onOpenDevices && (
                  <>
                    <div className="border-t border-line my-1" />
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false);
                        onOpenDevices();
                      }}
                      className="w-full flex items-center gap-2 h-11 md:h-10 px-3 rounded-lg text-sm font-medium hover:bg-surface-2"
                    >
                      <Cpu size={16} />
                      Devices
                    </button>
                  </>
                )}
                <div className="border-t border-line my-1" />
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    onLogout();
                  }}
                  className="w-full flex items-center gap-2 h-11 md:h-10 px-3 rounded-lg text-sm font-medium text-alarm hover:bg-alarm/10"
                >
                  <LogOut size={16} />
                  Log out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
    {helpOpen && <HelpDrawer onClose={() => setHelpOpen(false)} />}
    </>
  );
};

export default AppBar;
