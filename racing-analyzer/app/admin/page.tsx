'use client';

import { useEffect } from 'react';
import { Settings } from 'lucide-react';
import PageShell from '../shell/PageShell';
import { useRouter } from 'next/navigation';
import { useAuth } from '../contexts/AuthContext';
import AdminManager from '../components/AdminManager';

export default function AdminDashboard() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && (!user || user.role !== 'admin')) {
      router.push('/login');
    }
  }, [user, authLoading, router]);

  if (authLoading || !user || user.role !== 'admin') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-canvas text-ink">
        <div className="text-muted">Loading...</div>
      </div>
    );
  }

  return (
    <PageShell title="Admin" icon={<Settings size={18} />}>
        {/* Shared admin UI (users + tracks + per-track layouts) */}
        <AdminManager />
    </PageShell>
  );
}
