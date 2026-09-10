import React from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider, resolveInitialTheme, useTheme, THEME_STORAGE_KEY } from '@/app/contexts/ThemeContext';

describe('resolveInitialTheme', () => {
  test('explicit saved choice wins over OS preference', () => {
    expect(resolveInitialTheme('light', true)).toBe('light');
    expect(resolveInitialTheme('dark', false)).toBe('dark');
  });
  test('falls back to OS preference when nothing is saved or the value is junk', () => {
    expect(resolveInitialTheme(null, true)).toBe('dark');
    expect(resolveInitialTheme(undefined, false)).toBe('light');
    expect(resolveInitialTheme('blue', true)).toBe('dark');
  });
});

const Probe = () => {
  const { theme, isDark, toggleTheme } = useTheme();
  return (
    <button onClick={toggleTheme} data-testid="probe" data-dark={String(isDark)}>
      {theme}
    </button>
  );
};

describe('ThemeProvider', () => {
  let getItem: jest.SpyInstance;
  let setItem: jest.SpyInstance;
  beforeEach(() => {
    document.documentElement.classList.remove('dark');
    getItem = jest.spyOn(Storage.prototype, 'getItem');
    setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
  });
  afterEach(() => {
    getItem.mockRestore();
    setItem.mockRestore();
  });

  test('applies the saved theme to <html> and toggles + persists on demand', async () => {
    getItem.mockReturnValue('dark');
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await act(async () => {});
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(screen.getByTestId('probe')).toHaveAttribute('data-dark', 'true');

    await userEvent.click(screen.getByTestId('probe'));
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(screen.getByTestId('probe')).toHaveTextContent('light');
    expect(setItem).toHaveBeenCalledWith(THEME_STORAGE_KEY, 'light');
  });

  test('defaults to light when nothing is saved and the OS does not prefer dark', async () => {
    getItem.mockReturnValue(null);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await act(async () => {});
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(screen.getByTestId('probe')).toHaveTextContent('light');
  });
});
