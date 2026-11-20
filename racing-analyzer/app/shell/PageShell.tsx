'use client';

import React from 'react';
import Link from 'next/link';
import { ArrowLeft, Moon, Sun } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext';
import Button from '../ui/Button';
import { cn } from '../ui/cn';

export interface PageShellProps {
  /** Shown in the bar in the signage face, uppercase. */
  title: string;
  icon?: React.ReactNode;
  /** Where the back arrow goes, and what it is called. */
  backHref?: string;
  backLabel?: string;
  /** Extra controls on the right of the bar, before the theme toggle. */
  actions?: React.ReactNode;
  /** Max width of the content column. */
  width?: 'narrow' | 'wide';
  children: React.ReactNode;
}

const WIDTH = { narrow: 'max-w-3xl', wide: 'max-w-7xl' };

/**
 * The frame for every signed-in page that is not the live dashboard: the
 * same bar (brand, a way back, the page title, the theme toggle) over a
 * canvas content column. The dashboard keeps its own AppBar, which adds
 * the track switcher and feed timers.
 */
const PageShell: React.FC<PageShellProps> = ({
  title,
  icon,
  backHref = '/dashboard',
  backLabel = 'dashboard',
  actions,
  width = 'wide',
  children,
}) => {
  const { isDark, toggleTheme } = useTheme();
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="sticky top-0 z-40 h-14 border-b border-line bg-surface/80 backdrop-blur-md">
        <div className="h-full flex items-center gap-2 md:gap-4 px-3 md:px-5">
          <Link
            href={backHref}
            aria-label={`Back to ${backLabel}`}
            className="shrink-0 w-11 h-11 md:w-9 md:h-9 inline-flex items-center justify-center text-muted hover:text-ink hover:bg-surface-2 transition-colors"
          >
            <ArrowLeft size={18} />
          </Link>
          <Link href="/dashboard" className="hidden md:flex items-center gap-2.5 shrink-0" aria-label="LT-Analyzer dashboard">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="" width={30} height={30} className="w-[30px] h-[30px] object-cover" />
            <span className="font-cond font-bold text-xl tracking-wide">LT-ANALYZER</span>
          </Link>
          <div className="hidden md:block w-px h-6 bg-line" />
          <h1 className="min-w-0 flex items-center gap-2 font-cond font-bold text-xl tracking-wide uppercase">
            {icon && <span className="text-accent shrink-0">{icon}</span>}
            <span className="truncate">{title}</span>
          </h1>
          <div className="flex-1 min-w-0" />
          {actions}
          <Button
            onClick={toggleTheme}
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            className="w-11 px-0 md:w-auto md:px-2.5 gap-1.5 text-xs text-muted hover:text-ink"
          >
            {isDark ? <Sun size={16} /> : <Moon size={16} />}
            <span className="hidden lg:inline">{isDark ? 'Light' : 'Dark'}</span>
          </Button>
        </div>
      </header>
      <main className="px-3 md:px-6 py-4 md:py-6">
        <div className={cn(WIDTH[width], 'mx-auto')}>{children}</div>
      </main>
    </div>
  );
};

export default PageShell;
