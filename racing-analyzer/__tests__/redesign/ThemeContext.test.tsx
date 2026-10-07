import React from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider, resolveInitialTheme, useTheme, THEME_STORAGE_KEY } from '@/app/contexts/ThemeContext';

describe('resolveInitialTheme', () => {
  test('explicit saved choice wins', () => {
    expect(resolveInitialTheme('light')).toBe('light');
    expect(resolveInitialTheme('dark')).toBe('dark');
  });
  test('defaults to dark when nothing is saved or the value is junk', () => {
    expect(resolveInitialTheme(null)).toBe('dark');
    expect(resolveInitialTheme(undefined)).toBe('dark');
    expect(resolveInitialTheme('blue')).toBe('dark');
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
  let setItem: jest.SpyInstance;
  beforeEach(() => {
    document.documentElement.classList.remove('dark');
    setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
  });
  afterEach(() => {
    setItem.mockRestore();
  });

  test('adopts the boot-script theme from <html> and toggles + persists on demand', async () => {
    document.documentElement.classList.add('dark'); // simulate the inline boot script
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

  test('renders light when the boot script did not set dark', async () => {
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
