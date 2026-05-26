import Link from 'next/link';

export const metadata = { title: 'Privacy — LT-Analyzer' };

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-gray-900 text-gray-200">
      <main className="max-w-3xl mx-auto px-4 py-10 space-y-6">
        <Link href="/" className="text-sm text-blue-300 hover:underline">← Home</Link>
        <h1 className="text-3xl font-bold">Privacy Policy</h1>
        <p className="text-sm text-gray-400">Last updated: 2026-05-26</p>

        <section className="space-y-3 text-sm leading-6">
          <h2 className="text-xl font-semibold">Who we are</h2>
          <p>
            LT-Analyzer is operated by Tanguy Pedrazzoli. Contact:{' '}
            <a className="text-blue-300 underline" href="mailto:tanguy.pedrazzoli@gmail.com">tanguy.pedrazzoli@gmail.com</a>.
          </p>

          <h2 className="text-xl font-semibold">What we collect</h2>
          <ul className="list-disc list-inside">
            <li><strong>Account:</strong> username, email, hashed password, account creation/last-login timestamps.</li>
            <li><strong>Usage:</strong> IP address and User-Agent at the time of authentication-related events (login, register, verify, password reset).</li>
            <li><strong>Audit log:</strong> records of security-sensitive actions you take, kept for up to 12 months.</li>
            <li><strong>Race telemetry:</strong> publicly-broadcast live timing data from karting venues — these contain team names, lap times, kart numbers. They do not identify you personally.</li>
          </ul>

          <h2 className="text-xl font-semibold">Why we collect it</h2>
          <p>
            We process this data to provide the service (you can&apos;t log in without an account),
            to keep the service safe (rate limiting, abuse prevention, audit trail),
            and to debug. Legal basis: consent (your account creation) and legitimate interest (security and operations).
          </p>

          <h2 className="text-xl font-semibold">Processors we use</h2>
          <ul className="list-disc list-inside">
            <li><strong>Brevo</strong> — sends verification and password-reset emails on our behalf.</li>
            <li><strong>Cloudflare Turnstile</strong> — anti-abuse challenge on registration and login forms. It does not collect personally identifiable information.</li>
          </ul>

          <h2 className="text-xl font-semibold">Your rights</h2>
          <ul className="list-disc list-inside">
            <li>Access: <code>GET /api/auth/me</code> returns your profile.</li>
            <li>Export: <code>POST /api/auth/me/export</code> returns your profile and your audit-log entries as JSON.</li>
            <li>Deletion: <code>DELETE /api/auth/me</code> scrambles your account fields, invalidates your sessions, and marks the account deleted. Aggregated race-telemetry data is not personal data and is retained.</li>
          </ul>

          <h2 className="text-xl font-semibold">Cookies</h2>
          <p>
            We set a single session cookie when you log in (httpOnly, SameSite=Lax, Secure in production).
            No third-party analytics or tracking cookies.
          </p>

          <h2 className="text-xl font-semibold">Changes</h2>
          <p>If we materially change this policy we&apos;ll surface a notice on the dashboard before your next login.</p>
        </section>
      </main>
    </div>
  );
}
