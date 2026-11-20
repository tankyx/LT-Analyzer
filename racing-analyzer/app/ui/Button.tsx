import React from 'react';
import { cn } from './cn';

export type ButtonVariant = 'primary' | 'danger' | 'outline' | 'quiet';
export type ButtonSize = 'sm' | 'md' | 'lg';

const VARIANT: Record<ButtonVariant, string> = {
  // One per view. Flat accent-hi with accent-ink (6.5:1 in both themes).
  primary: 'accent-block text-accent-ink hover:brightness-95',
  // Pit alert and destructive confirmations. on-signal, never white.
  danger: 'bg-alarm text-on-signal hover:brightness-95',
  outline: 'border border-line-strong text-ink hover:bg-surface-2',
  quiet: 'text-muted hover:text-ink hover:bg-surface-2',
};

// md and lg grow to a 44px target below the md breakpoint; sm is for toasts
// and dense toolbars where the row itself is the target.
const SIZE: Record<ButtonSize, string> = {
  sm: 'h-8 px-2.5 text-xs',
  md: 'h-11 md:h-9 px-3 text-sm',
  lg: 'h-11 md:h-10 px-4 text-sm',
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Stretch to the container's width. */
  block?: boolean;
}

/** The text button. Focus ring and square corners come from globals.css. */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'outline', size = 'md', block = false, type = 'button', className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        'inline-flex items-center justify-center gap-2 font-semibold whitespace-nowrap transition-colors',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        VARIANT[variant],
        SIZE[size],
        block && 'flex w-full',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

export default Button;
