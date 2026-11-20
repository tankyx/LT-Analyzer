import React from 'react';
import { cn } from './cn';

/** The uppercase label above a figure or a group. */
export const Eyebrow: React.FC<React.HTMLAttributes<HTMLSpanElement>> = ({ className, children, ...rest }) => (
  <span className={cn('eyebrow text-muted', className)} {...rest}>
    {children}
  </span>
);

/** A small mono count beside a title or on a tab. */
export const CountBadge: React.FC<{ value: number | string; className?: string }> = ({ value, className }) => (
  <span className={cn('tabular text-3xs leading-none px-1 py-0.5 bg-surface border border-line text-ink', className)}>
    {value}
  </span>
);

export interface PanelProps extends React.HTMLAttributes<HTMLElement> {
  as?: 'section' | 'div' | 'aside';
}

/** The container for a tool: a flat surface with a line outline. No shadow,
 *  no radius; do not nest one inside another. */
export const Panel: React.FC<PanelProps> = ({ as: Tag = 'section', className, children, ...rest }) => (
  <Tag className={cn('border border-line bg-surface min-w-0', className)} {...rest}>
    {children}
  </Tag>
);

export interface PanelHeaderProps {
  title: string;
  icon?: React.ReactNode;
  count?: number | string;
  /** Controls on the right. */
  actions?: React.ReactNode;
  className?: string;
}

export const PanelHeader: React.FC<PanelHeaderProps> = ({ title, icon, count, actions, className }) => (
  <header className={cn('flex items-center gap-2 px-4 py-3 bg-surface-2 border-b border-line', className)}>
    {icon && <span className="text-accent shrink-0">{icon}</span>}
    <h2 className="font-cond font-bold text-xl tracking-wide uppercase truncate">{title}</h2>
    {count !== undefined && <CountBadge value={count} />}
    {actions && <div className="ml-auto flex items-center gap-2 shrink-0">{actions}</div>}
  </header>
);

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  /** What is missing and the one action that fills it. */
  children?: React.ReactNode;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ icon, title, children, className }) => (
  <div className={cn('flex flex-col items-center gap-1 px-4 py-8 text-center', className)}>
    {icon && <span className="text-line-strong mb-2">{icon}</span>}
    <div className="font-semibold">{title}</div>
    {children && <div className="text-sm text-muted">{children}</div>}
  </div>
);

export default Panel;
