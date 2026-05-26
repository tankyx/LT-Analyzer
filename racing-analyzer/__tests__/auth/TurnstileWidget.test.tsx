import { render, waitFor } from '@testing-library/react';

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://localhost:5000',
  WS_BASE_URL: 'ws://localhost:5000',
  TURNSTILE_SITE_KEY: '',
  INVITE_REQUIRED: true,
}));

import TurnstileWidget from '@/app/components/TurnstileWidget';

describe('TurnstileWidget', () => {
  test('with no sitekey, calls onVerify with placeholder and renders nothing', async () => {
    const onVerify = jest.fn();
    const { container } = render(<TurnstileWidget onVerify={onVerify} />);
    await waitFor(() => expect(onVerify).toHaveBeenCalledWith('dev-no-turnstile'));
    expect(container.querySelector('.cf-turnstile')).toBeNull();
  });

  test('still renders nothing visible in dev mode', () => {
    const { container } = render(<TurnstileWidget onVerify={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
