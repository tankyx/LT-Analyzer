'use client';

import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

interface HelpDrawerProps {
  onClose: () => void;
}

const SECTIONS: Array<{ title: string; body: string }> = [
  {
    title: 'Standings',
    body: 'The live field order with last/best lap and gap. Tap the star on a row to track that team against yours.',
  },
  {
    title: 'Monitored',
    body: 'Your rivals’ time gap measured from your team. “Raw” is as-is; “Adjusted” adds the pit stops each side still has to make.',
  },
  {
    title: 'Pace',
    body: 'How your lap pace compares to the rest of the field at the same moment — independent of track position.',
  },
  {
    title: 'Delta',
    body: 'Your time gap to each monitored team across the last 15 laps. Dashed sections mark pit stops.',
  },
  {
    title: 'Stints',
    body: 'Plan driver stints and pit windows, and check the schedule still fits before the flag.',
  },
  {
    title: 'Fleet',
    body: 'Which physical karts are on track, in the pits, or available. You get an alert when a fast kart rolls into the pits.',
  },
];

const SHORTCUTS: Array<[string, string]> = [
  ['1–9', 'Jump straight to a tab'],
  ['Esc', 'Close this guide or the track picker'],
];

/** First-visit / on-demand guide: task-focused explanations, keyboard/reader
    accessible, dismissible. A real dialog, not a hover tooltip. */
const HelpDrawer: React.FC<HelpDrawerProps> = ({ onClose }) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'Tab' && ref.current) {
        const focusables = ref.current.querySelectorAll<HTMLElement>(
          'button, a, [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end md:justify-center md:items-center" role="dialog" aria-modal="true" aria-label="Dashboard guide">
      <button type="button" aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/60" />
      <div
        ref={ref}
        className="relative flex flex-col gap-4 p-4 pb-[max(16px,env(safe-area-inset-bottom))] bg-surface border border-line rounded-t-none md:rounded-none w-full md:w-[520px] max-h-[85vh] md:max-h-[75vh] shadow-2xl"
      >
        <div className="flex items-center justify-between px-1">
          <h2 className="font-cond font-bold text-xl tracking-wide">DASHBOARD GUIDE</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close guide"
            className="w-10 h-10 flex items-center justify-center rounded-none text-muted hover:text-ink hover:bg-surface-2"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin flex flex-col gap-3 -mx-1 px-1">
          {SECTIONS.map((s) => (
            <div key={s.title} className="rounded-none border border-line bg-canvas p-3">
              <h3 className="font-cond font-bold text-lg tracking-wide text-accent">{s.title}</h3>
              <p className="text-sm text-muted mt-1">{s.body}</p>
            </div>
          ))}

          <div className="rounded-none border border-line bg-surface-2 p-3">
            <h3 className="font-cond font-bold text-lg tracking-wide text-ink">Keyboard</h3>
            <ul className="mt-1 flex flex-col gap-1">
              {SHORTCUTS.map(([key, desc]) => (
                <li key={key} className="flex items-center gap-2 text-sm text-muted">
                  <kbd className="font-mono tabular text-xs px-1.5 py-0.5 rounded-none bg-surface border border-line text-ink">{key}</kbd>
                  {desc}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default HelpDrawer;
