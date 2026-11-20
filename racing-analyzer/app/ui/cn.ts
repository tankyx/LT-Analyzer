import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Join class names; a later class wins over an earlier one for the same
 *  property, so a call site can override a primitive's default. */
export const cn = (...inputs: ClassValue[]): string => twMerge(clsx(inputs));
