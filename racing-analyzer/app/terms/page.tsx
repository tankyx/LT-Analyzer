import Link from 'next/link';

export const metadata = { title: 'Terms — LT-Analyzer' };

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-gray-900 text-gray-200">
      <main className="max-w-3xl mx-auto px-4 py-10 space-y-6">
        <Link href="/" className="text-sm text-blue-300 hover:underline">← Home</Link>
        <h1 className="text-3xl font-bold">Terms of Use</h1>
        <p className="text-sm text-gray-400">Last updated: 2026-05-26</p>

        <section className="space-y-3 text-sm leading-6">
          <h2 className="text-xl font-semibold">Closed beta</h2>
          <p>
            LT-Analyzer is currently in closed beta. Access is by invite code only. The service is
            provided as-is, with no uptime or correctness guarantees while in beta.
          </p>

          <h2 className="text-xl font-semibold">Acceptable use</h2>
          <ul className="list-disc list-inside">
            <li>Don&apos;t share your account credentials. One person per account.</li>
            <li>Don&apos;t scrape, automate, or otherwise put unusual load on the service. Use the WebSocket APIs.</li>
            <li>Don&apos;t attempt to circumvent authentication, rate limits, or other security controls.</li>
            <li>Don&apos;t impersonate someone else or use a misleading username (including reserved names like &ldquo;admin&rdquo;).</li>
          </ul>

          <h2 className="text-xl font-semibold">Race-data attribution</h2>
          <p>
            Live timing data is sourced from public Apex Timing streams provided by individual karting venues.
            LT-Analyzer aggregates and analyses it. Original timing data remains the venues&apos; property.
          </p>

          <h2 className="text-xl font-semibold">Account termination</h2>
          <p>
            We may suspend or delete accounts that violate these terms or that pose a security risk.
            You can delete your own account at any time from the account page.
          </p>

          <h2 className="text-xl font-semibold">Liability</h2>
          <p>
            The service is provided without warranty. We&apos;re not liable for race-result decisions made
            based on analytics shown here — race officials&apos; results are the source of truth.
          </p>

          <h2 className="text-xl font-semibold">Contact</h2>
          <p>
            Questions: <a className="text-blue-300 underline" href="mailto:tanguy.pedrazzoli@gmail.com">tanguy.pedrazzoli@gmail.com</a>
          </p>
        </section>
      </main>
    </div>
  );
}
