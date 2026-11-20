import React from 'react';
import { cn } from './cn';

export type IconButtonVariant = 'quiet' | 'outline' | 'alarm';
export type IconButtonSize = 'sm' | 'md';

const VARIANT: Record<IconButtonVariant, string> = {
  quiet: 'text-muted hover:text-ink hover:bg-surface-2',
  outline: 'border border-line-strong text-muted hover:text-ink hover:bg-surface-2',
  alarm: 'text-alarm hover:bg-alarm/15',
};

const SIZE: Record<IconButtonSize, string> = {
  sm: 'w-8 h-8',
  // 44px on phones, 36px from md up
  md: 'w-11 h-11 md:w-9 md:h-9',
};

export interface IconButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  /** Names the action and its object: "Monitor Apex Hunters". Required — the
   *  icon is the only visible content. */
  label: string;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
}

/** A square button holding one icon. */
const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = 'quiet', size = 'md', type = 'button', className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      className={cn(
        'shrink-0 inline-flex items-center justify-center transition-colors',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

export default IconButton;
