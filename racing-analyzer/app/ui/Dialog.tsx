'use client';

import React, { useEffect, useRef } from 'react';
import { cn } from './cn';

const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface DialogProps {
  /** Accessible name: "Choose a track". */
  label: string;
  onClose: () => void;
  /** Classes for the panel (width, height, padding). */
  className?: string;
  /** Test id for the backdrop, which closes the dialog when clicked. */
  scrimTestId?: string;
  children: React.ReactNode;
}

/**
 * Esc to close, and Tab kept inside `panelRef`, for as long as the caller is
 * mounted. Dialog uses it; so does the feature tour, whose card is placed
 * beside a spotlight and so cannot be a Dialog.
 */
export function useDialogKeys(panelRef: React.RefObject<HTMLElement | null>, onClose: () => void): void {
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeRef.current();
        return;
      }
      if (e.key !== 'Tab' || !panelRef.current) return;
      const focusables = panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      const outside = !panelRef.current.contains(active);
      if (e.shiftKey && (active === first || outside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || outside)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [panelRef]);
}

/**
 * A modal layer: scrim, Esc to close, and focus kept inside while open.
 * A bottom sheet on phones, centred from md up. The one place the
 * scrim, the overlay shadow and the focus trap are written.
 */
const Dialog: React.FC<DialogProps> = ({ label, onClose, className, scrimTestId, children }) => {
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogKeys(panelRef, onClose);

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-end md:justify-center md:items-center"
      role="dialog"
      aria-modal="true"
      aria-label={label}
    >
      <button
        type="button"
        aria-label="Close"
        tabIndex={-1}
        onClick={onClose}
        data-testid={scrimTestId}
        className="absolute inset-0 bg-scrim cursor-default"
      />
      <div
        ref={panelRef}
        className={cn(
          'relative flex flex-col w-full md:w-[440px] max-h-[90vh] bg-surface text-ink border border-line shadow-overlay',
          'pb-[env(safe-area-inset-bottom)]',
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
};

export default Dialog;
