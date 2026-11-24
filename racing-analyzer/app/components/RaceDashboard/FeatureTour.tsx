'use client';

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import Button from '../../ui/Button';
import IconButton from '../../ui/IconButton';
import { useDialogKeys } from '../../ui/Dialog';
import { Box, Size, TOUR_STEPS, TourStep, findTourTarget, placeTourCard, spotlightBox } from './lib/tour';

interface FeatureTourProps {
  steps?: TourStep[];
  /** Brings a tab forward for the step being shown. */
  onShowTab: (tabId: string) => void;
  /** Skip, Esc or Done. */
  onClose: () => void;
  /** The last step's main action: end the tour and open the quick start. */
  onOpenQuickStart: () => void;
}

/** How often the target is re-measured: standings rows move as laps come in. */
const MEASURE_MS = 250;

const sameBox = (a: Box | null, b: Box | null): boolean =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

const viewportSize = (): Size => ({ width: window.innerWidth, height: window.innerHeight });

/**
 * The first-launch tour. One feature at a time: the real element is
 * spotlighted, the rest of the page is dimmed and inert, and a card beside
 * the spotlight says what it is for. Tab steps bring their tab forward so the
 * tool itself is visible behind the dim. Next/Back (or the arrow keys) move
 * through it; Esc or the close button skips it.
 */
const FeatureTour: React.FC<FeatureTourProps> = ({ steps = TOUR_STEPS, onShowTab, onClose, onOpenQuickStart }) => {
  const [index, setIndex] = useState(0);
  const [target, setTarget] = useState<Box | null>(null);
  const [card, setCard] = useState<Size>({ width: 0, height: 0 });
  const [viewport, setViewport] = useState<Size>(viewportSize);
  const cardRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);

  const step = steps[index];
  const isLast = index === steps.length - 1;

  useDialogKeys(cardRef, onClose);

  const next = useCallback(() => setIndex((i) => Math.min(i + 1, steps.length - 1)), [steps.length]);
  const back = useCallback(() => setIndex((i) => Math.max(i - 1, 0)), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') next();
      else if (e.key === 'ArrowLeft') back();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [next, back]);

  // Bring the step's tab forward. Ref-mirrored so a new callback identity
  // from the parent does not replay the switch.
  const showTabRef = useRef(onShowTab);
  useEffect(() => {
    showTabRef.current = onShowTab;
  });
  useEffect(() => {
    if (step.tab) showTabRef.current(step.tab);
  }, [step]);

  // Follow the target: before the first paint, on the next frame (the tab
  // switch above lands a render later), then on a timer and on resize, since
  // live rows keep moving.
  useLayoutEffect(() => {
    let scrolledIntoView = false;
    const measure = () => {
      setViewport((prev) => {
        const now = viewportSize();
        return prev.width === now.width && prev.height === now.height ? prev : now;
      });
      const el = findTourTarget(step.targets);
      if (!el) {
        setTarget(null);
        return;
      }
      if (!scrolledIntoView) {
        scrolledIntoView = true;
        el.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
      }
      const r = el.getBoundingClientRect();
      const box: Box = {
        top: Math.round(r.top),
        left: Math.round(r.left),
        width: Math.round(r.width),
        height: Math.round(r.height),
      };
      setTarget((prev) => (sameBox(prev, box) ? prev : box));
    };
    measure();
    const frame = window.requestAnimationFrame(measure);
    const timer = window.setInterval(measure, MEASURE_MS);
    window.addEventListener('resize', measure);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearInterval(timer);
      window.removeEventListener('resize', measure);
    };
  }, [step]);

  // The card's size changes with the copy, and placement depends on it.
  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const size = { width: el.offsetWidth, height: el.offsetHeight };
    setCard((prev) => (prev.width === size.width && prev.height === size.height ? prev : size));
  }, [index, viewport]);

  // Keep the keyboard on the way forward.
  useEffect(() => {
    primaryRef.current?.focus();
  }, [index]);

  const hole = target ? spotlightBox(target, viewport) : null;
  const position = placeTourCard(hole, card, viewport);

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="Feature tour">
      {/* Keeps the page inert while the tour runs, the spotlighted element included. */}
      <div className="absolute inset-0" />

      {hole ? (
        <>
          <div className="absolute inset-x-0 top-0 bg-scrim" style={{ height: hole.top }} />
          <div className="absolute inset-x-0 bottom-0 bg-scrim" style={{ top: hole.top + hole.height }} />
          <div className="absolute left-0 bg-scrim" style={{ top: hole.top, height: hole.height, width: hole.left }} />
          <div
            className="absolute right-0 bg-scrim"
            style={{ top: hole.top, height: hole.height, left: hole.left + hole.width }}
          />
          <div
            className="absolute border-2 border-accent pointer-events-none"
            style={{ top: hole.top, left: hole.left, width: hole.width, height: hole.height }}
            data-testid="tour-spotlight"
          />
        </>
      ) : (
        <div className="absolute inset-0 bg-scrim" />
      )}

      <div
        ref={cardRef}
        className="absolute w-[min(360px,calc(100vw-24px))] flex flex-col gap-3 p-4 bg-surface text-ink border border-line shadow-overlay"
        style={{ top: position.top, left: position.left }}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="eyebrow text-muted">
            Tour · <span className="tabular">{index + 1}</span> of <span className="tabular">{steps.length}</span>
          </span>
          <IconButton size="sm" label="Skip the tour" onClick={onClose}>
            <X size={16} />
          </IconButton>
        </div>

        <div aria-live="polite" className="flex flex-col gap-1.5">
          <h2 className="font-cond font-bold text-xl tracking-wide">{step.title}</h2>
          <p className="text-sm text-muted">{step.body}</p>
        </div>

        <div className="flex items-center gap-2">
          {index > 0 && (
            <Button variant="quiet" onClick={back}>
              Back
            </Button>
          )}
          <div className="flex-1" />
          {isLast ? (
            <>
              <Button onClick={onClose}>Done</Button>
              <Button ref={primaryRef} variant="primary" onClick={onOpenQuickStart}>
                Quick start
              </Button>
            </>
          ) : (
            <Button ref={primaryRef} variant="primary" onClick={next}>
              Next
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

export default FeatureTour;
