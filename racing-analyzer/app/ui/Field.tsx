import React, { useId } from 'react';
import { cn } from './cn';

// 44px on phones, 40px from md up. The line-strong border is the control's
// only edge against a surface panel, so it has to reach 3:1.
const CONTROL =
  'w-full min-w-0 h-11 md:h-10 px-3 border border-line-strong bg-canvas text-sm text-ink placeholder:text-muted disabled:opacity-50';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid, className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(CONTROL, invalid && 'border-alarm', className)}
      {...rest}
    />
  );
});

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { invalid, className, children, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(CONTROL, invalid && 'border-alarm', className)}
      {...rest}
    >
      {children}
    </select>
  );
});

export interface FieldProps {
  label: string;
  /** Shown under the control; replaced by `error` when there is one. */
  hint?: React.ReactNode;
  /** Says how to fix it. Sets the control's invalid state. */
  error?: React.ReactNode;
  className?: string;
  /** One Input or Select. It receives the id, invalid state and description. */
  children: React.ReactElement<{ id?: string; invalid?: boolean; 'aria-describedby'?: string }>;
}

/** A visible label above one control, with an optional hint or error below. */
export const Field: React.FC<FieldProps> = ({ label, hint, error, className, children }) => {
  const autoId = useId();
  const id = children.props.id ?? autoId;
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className={cn('flex flex-col gap-1.5 min-w-0', className)}>
      <label htmlFor={id} className="text-xs font-semibold text-muted">
        {label}
      </label>
      {React.cloneElement(children, {
        id,
        invalid: error ? true : children.props.invalid,
        'aria-describedby': note ? noteId : undefined,
      })}
      {note && (
        <span id={noteId} className={cn('text-xs', error ? 'text-alarm' : 'text-muted')} role={error ? 'alert' : undefined}>
          {note}
        </span>
      )}
    </div>
  );
};

export default Field;
