'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import AdminManager from '../components/AdminManager';

export default function AdminDashboard() {
  const { user, loading: authLoading } = useAuth();
  const { isDark } = useTheme();
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
    <div className="min-h-screen bg-canvas text-ink">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold">Admin Dashboard</h1>
          <button
            onClick={() => router.push('/dashboard')}
            className="px-4 py-2 bg-surface-2 border border-line rounded-lg hover:bg-line"
          >
            Back to Dashboard
          </button>
        </div>

        {/* Shared admin UI (users + tracks + per-track layouts) */}
        <AdminManager isDarkMode={isDark} />
      </div>
    </div>
  );
}
