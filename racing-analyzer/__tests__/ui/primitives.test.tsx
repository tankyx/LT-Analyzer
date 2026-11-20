/**
 * The shared primitives in app/ui. These pin the contracts the rest of the
 * app relies on: the token classes each variant carries, the accessible
 * names, and the dialog's keyboard behaviour.
 */
import '@testing-library/jest-dom';
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Button from '@/app/ui/Button';
import IconButton from '@/app/ui/IconButton';
import { Field, Input, Select } from '@/app/ui/Field';
import SegmentedControl from '@/app/ui/SegmentedControl';
import Dialog from '@/app/ui/Dialog';
import Stat from '@/app/ui/Stat';
import { Panel, PanelHeader, EmptyState } from '@/app/ui/Panel';
import { cn } from '@/app/ui/cn';

describe('cn', () => {
  test('a later class wins for the same property; custom sizes are sizes, not colours', () => {
    expect(cn('h-9 px-3', 'h-11')).toBe('px-3 h-11');
    expect(cn('text-sm text-muted', 'text-2xs')).toBe('text-muted text-2xs');
    expect(cn('text-muted', false && 'hidden', 'text-ink')).toBe('text-ink');
  });
});

describe('Button', () => {
  test('defaults to a non-submitting outline button', () => {
    render(<Button>Guide</Button>);
    const b = screen.getByRole('button', { name: 'Guide' });
    expect(b).toHaveAttribute('type', 'button');
    expect(b.className).toContain('border-line-strong');
  });

  test('primary is the flat accent block with accent-ink; danger uses on-signal, never white', () => {
    render(
      <>
        <Button variant="primary">Sign in</Button>
        <Button variant="danger">Pit alert</Button>
      </>,
    );
    const primary = screen.getByRole('button', { name: 'Sign in' });
    expect(primary.className).toContain('accent-block');
    expect(primary.className).toContain('text-accent-ink');
    const danger = screen.getByRole('button', { name: 'Pit alert' });
    expect(danger.className).toContain('bg-alarm');
    expect(danger.className).toContain('text-on-signal');
    expect(danger.className).not.toContain('text-white');
  });

  test('md and lg reach a 44px target on phones; a call site can override', () => {
    render(
      <>
        <Button>Default</Button>
        <Button size="sm">Small</Button>
        <Button className="h-12">Tall</Button>
      </>,
    );
    expect(screen.getByRole('button', { name: 'Default' }).className).toContain('h-11');
    expect(screen.getByRole('button', { name: 'Small' }).className).toContain('h-8');
    const tall = screen.getByRole('button', { name: 'Tall' }).className;
    expect(tall).toContain('h-12');
    expect(tall).not.toContain('h-11');
  });

  test('carries no per-element focus or radius classes', () => {
    render(<Button variant="primary">Go</Button>);
    const c = screen.getByRole('button', { name: 'Go' }).className;
    expect(c).not.toMatch(/focus:|focus-visible:|rounded-none/);
  });

  test('disabled does not fire', async () => {
    const onClick = jest.fn();
    render(<Button disabled onClick={onClick}>Save</Button>);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('IconButton', () => {
  test('the label is the accessible name', async () => {
    const onClick = jest.fn();
    render(<IconButton label="Dismiss" onClick={onClick}><svg /></IconButton>);
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  test('toggle state passes through', () => {
    render(<IconButton label="Monitor Apex Hunters" aria-pressed={true}><svg /></IconButton>);
    expect(screen.getByRole('button', { name: 'Monitor Apex Hunters' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('Field', () => {
  test('the visible label names the control, and its border reaches 3:1', () => {
    render(<Field label="Board name"><Input placeholder="e.g. datalogger-p4" /></Field>);
    const input = screen.getByLabelText('Board name');
    expect(input.tagName).toBe('INPUT');
    expect(input.className).toContain('border-line-strong');
  });

  test('an error marks the control invalid and is announced', () => {
    render(<Field label="Pit time" hint="Seconds" error="Enter a duration above zero."><Input defaultValue="-1" /></Field>);
    const input = screen.getByLabelText('Pit time');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input.className).toContain('border-alarm');
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a duration above zero.');
    expect(screen.queryByText('Seconds')).toBeNull();
    expect(input).toHaveAccessibleDescription('Enter a duration above zero.');
  });

  test('works with a select and keeps a given id', () => {
    render(
      <Field label="My team">
        <Select id="team" defaultValue="15"><option value="15">Scuderia Lenta</option></Select>
      </Field>,
    );
    expect(screen.getByLabelText('My team')).toHaveAttribute('id', 'team');
  });
});

describe('SegmentedControl', () => {
  const options = [
    { value: 'raw', label: 'Raw' },
    { value: 'adjusted', label: 'Adjusted', count: 3 },
  ];

  test('marks the selection and reports a change', async () => {
    const onChange = jest.fn();
    render(<SegmentedControl label="Gap mode" options={options} value="raw" onChange={onChange} />);
    const group = screen.getByRole('group', { name: 'Gap mode' });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Raw' })).toHaveAttribute('aria-pressed', 'true');
    const adjusted = screen.getByRole('button', { name: /Adjusted/ });
    expect(adjusted).toHaveAttribute('aria-pressed', 'false');
    expect(adjusted).toHaveTextContent('3');
    await userEvent.click(adjusted);
    expect(onChange).toHaveBeenCalledWith('adjusted');
  });
});

describe('Dialog', () => {
  const Harness = ({ onClose }: { onClose: () => void }) => (
    <Dialog label="Choose a track" onClose={onClose} scrimTestId="scrim">
      <button>First</button>
      <button>Last</button>
    </Dialog>
  );

  test('is a named modal dialog', () => {
    render(<Harness onClose={() => {}} />);
    const d = screen.getByRole('dialog', { name: 'Choose a track' });
    expect(d).toHaveAttribute('aria-modal', 'true');
  });

  test('Escape and the scrim both close it', async () => {
    const onClose = jest.fn();
    render(<Harness onClose={onClose} />);
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByTestId('scrim'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  test('Tab wraps inside the panel in both directions, and pulls stray focus back in', async () => {
    render(
      <>
        <button>Outside</button>
        <Harness onClose={() => {}} />
      </>,
    );
    const first = screen.getByRole('button', { name: 'First' });
    const last = screen.getByRole('button', { name: 'Last' });
    last.focus();
    await userEvent.tab();
    expect(first).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(last).toHaveFocus();
    screen.getByRole('button', { name: 'Outside' }).focus();
    await userEvent.tab();
    expect(first).toHaveFocus();
  });
});

describe('Stat and Panel', () => {
  test('a stat pairs an eyebrow label with a tabular figure and takes a tone', () => {
    render(<Stat label="Ahead · P3" value="−3.417" sub="closing" tone="text-live" />);
    expect(screen.getByText('Ahead · P3').className).toContain('eyebrow');
    const fig = screen.getByText('−3.417');
    expect(fig.className).toContain('tabular');
    expect(fig.className).toContain('text-live');
    expect(fig.className).not.toContain('truncate');
    expect(screen.getByText('closing')).toBeInTheDocument();
  });

  test('a panel header shows title, count and actions; panels cast no shadow', () => {
    render(
      <Panel aria-label="Monitored">
        <PanelHeader title="Monitored" count={3} actions={<button>Clear all</button>} />
        <EmptyState title="No teams monitored yet">Tap the star on a standings row.</EmptyState>
      </Panel>,
    );
    expect(screen.getByRole('heading', { name: 'Monitored' })).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear all' })).toBeInTheDocument();
    expect(screen.getByText('No teams monitored yet')).toBeInTheDocument();
    expect(screen.getByLabelText('Monitored').className).not.toMatch(/shadow/);
  });
});
