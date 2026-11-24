'use client';

import React from 'react';
import { Check } from 'lucide-react';
import Button from '../../ui/Button';
import { buildQuickStartSteps, QuickStartState } from './lib/quickStart';

export interface QuickStartProps extends QuickStartState {
  /** Closes the guide and opens the track picker. */
  onChooseTrack: () => void;
}

/**
 * The setup steps for a new account. Steps the dashboard can see are complete
 * show a tick, so reopening the guide tells the user what is left.
 */
const QuickStart: React.FC<QuickStartProps> = ({ onChooseTrack, ...state }) => {
  const steps = buildQuickStartSteps(state);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted px-1">Four steps and your pit wall is ready.</p>

      <ol className="flex flex-col gap-2">
        {steps.map((step, i) => (
          <li key={step.id} className="border border-line bg-canvas p-3 flex gap-3">
            <span
              aria-hidden
              className={`w-8 h-8 shrink-0 flex items-center justify-center font-cond font-bold text-lg ${
                step.done ? 'bg-live/15' : 'border border-line-strong text-ink'
              }`}
            >
              {step.done ? <Check size={18} className="text-live" /> : i + 1}
            </span>
            <div className="flex flex-col gap-1 min-w-0 flex-1">
              <h3 className="font-cond font-bold text-lg tracking-wide leading-8">
                {step.title}
                {step.done && <span className="sr-only"> (done)</span>}
              </h3>
              <p className="text-sm text-muted">{step.body}</p>
              {step.status && <p className="text-xs font-semibold text-ink">{step.status}</p>}
              {step.id === 'track' && (
                <Button onClick={onChooseTrack} className="self-start mt-1">
                  Switch track
                </Button>
              )}
            </div>
          </li>
        ))}
      </ol>

      <p className="text-xs text-muted px-1">
        Your picks are saved to your account for each track, so they follow you to any device.
      </p>
    </div>
  );
};

export default QuickStart;
