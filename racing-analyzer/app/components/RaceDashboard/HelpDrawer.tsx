'use client';

import React, { useState } from 'react';
import { Route, X } from 'lucide-react';
import Button from '../../ui/Button';
import Dialog from '../../ui/Dialog';
import IconButton from '../../ui/IconButton';
import SegmentedControl from '../../ui/SegmentedControl';
import QuickStart, { QuickStartProps } from './QuickStart';

export type GuideView = 'quickstart' | 'tabs';

interface HelpDrawerProps {
  onClose: () => void;
  /** Page to open on. The first-visit offer opens on the quick start. */
  initialView?: GuideView;
  /** Live setup state for the quick start. Without it only the tab reference is shown. */
  quickStart?: QuickStartProps;
  /** Closes the guide and replays the feature tour. */
  onStartTour?: () => void;
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

const VIEWS: Array<{ value: GuideView; label: string }> = [
  { value: 'quickstart', label: 'Quick start' },
  { value: 'tabs', label: 'Tabs & keys' },
];

/**
 * The guide: a quick start for setting the dashboard up (opened unprompted on
 * a new account's first visit) and a reference for what each tab does.
 * Keyboard/reader accessible, dismissible. A real dialog, not a hover tooltip.
 */
const HelpDrawer: React.FC<HelpDrawerProps> = ({ onClose, initialView = 'tabs', quickStart, onStartTour }) => {
  const [chosenView, setChosenView] = useState<GuideView>(initialView);
  const view: GuideView = quickStart ? chosenView : 'tabs';
  const title = view === 'quickstart' ? 'Quick start' : 'Dashboard guide';

  return (
    <Dialog
      label={title}
      onClose={onClose}
      className="gap-4 p-4 pb-[max(16px,env(safe-area-inset-bottom))] md:w-[520px] max-h-[85vh] md:max-h-[75vh]"
    >
        <div className="flex items-center justify-between px-1">
          <h2 className="font-cond font-bold text-xl tracking-wide uppercase">{title}</h2>
          <IconButton label="Close guide" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </div>

        {(quickStart || onStartTour) && (
          <div className="flex items-center justify-between gap-2 flex-wrap">
            {quickStart && (
              <SegmentedControl label="Guide section" options={VIEWS} value={view} onChange={setChosenView} />
            )}
            {onStartTour && (
              <Button variant="quiet" onClick={onStartTour} className="gap-1.5">
                <Route size={16} />
                Take the tour
              </Button>
            )}
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin flex flex-col gap-3 -mx-1 px-1">
          {view === 'quickstart' && quickStart ? (
            <QuickStart {...quickStart} />
          ) : (
            <>
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
            </>
          )}
        </div>

        {view === 'quickstart' && (
          <Button variant="primary" size="lg" block onClick={onClose}>
            Got it
          </Button>
        )}
    </Dialog>
  );
};

export default HelpDrawer;
