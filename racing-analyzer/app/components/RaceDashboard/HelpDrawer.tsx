'use client';

import React from 'react';
import { X } from 'lucide-react';
import Dialog from '../../ui/Dialog';
import IconButton from '../../ui/IconButton';

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
  return (
    <Dialog
      label="Dashboard guide"
      onClose={onClose}
      className="gap-4 p-4 pb-[max(16px,env(safe-area-inset-bottom))] md:w-[520px] max-h-[85vh] md:max-h-[75vh]"
    >
        <div className="flex items-center justify-between px-1">
          <h2 className="font-cond font-bold text-xl tracking-wide">DASHBOARD GUIDE</h2>
          <IconButton label="Close guide" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin flex flex-col gap-3 -mx-1 px-1">
          {SECTIONS.map((s) => (
            <div key={s.title} className="border border-line bg-canvas p-3">
              <h3 className="font-cond font-bold text-lg tracking-wide text-accent">{s.title}</h3>
              <p className="text-sm text-muted mt-1">{s.body}</p>
            </div>
          ))}

          <div className="border border-line bg-surface-2 p-3">
            <h3 className="font-cond font-bold text-lg tracking-wide text-ink">Keyboard</h3>
            <ul className="mt-1 flex flex-col gap-1">
              {SHORTCUTS.map(([key, desc]) => (
                <li key={key} className="flex items-center gap-2 text-sm text-muted">
                  <kbd className="font-mono tabular text-xs px-1.5 py-0.5 bg-surface border border-line text-ink">{key}</kbd>
                  {desc}
                </li>
              ))}
            </ul>
          </div>
        </div>
    </Dialog>
  );
};

export default HelpDrawer;
