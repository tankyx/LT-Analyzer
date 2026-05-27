'use client';

import { useState, useEffect } from 'react';
import { ApiService } from '../../services/ApiService';

export interface LayoutEntry {
  id: number;
  track_id: number;
  name: string;
  min_field_best: number | null;
  max_field_best: number | null;
  is_default: boolean;
}

interface LayoutsModalTrack {
  id: number;
  name: string;
}

/**
 * Per-track physical-layout (kart-fairness band) editor. Shared by the admin
 * UI. Dark-styled (both admin surfaces render on a dark background).
 */
export default function LayoutsModal(
  { track, onClose }: { track: LayoutsModalTrack; onClose: () => void },
) {
  const [layouts, setLayouts] = useState<LayoutEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: '',
    min_field_best: '',
    max_field_best: '',
    is_default: false,
  });
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await ApiService.getTrackLayouts(track.id);
      setLayouts(res?.layouts || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load layouts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track.id]);

  const toFloat = (s: string) => (s.trim() === '' ? null : parseFloat(s));

  const submit = async () => {
    if (!form.name.trim()) { setError('Layout name is required'); return; }
    setError(null);
    try {
      const payload = {
        name: form.name.trim(),
        min_field_best: toFloat(form.min_field_best),
        max_field_best: toFloat(form.max_field_best),
        is_default: form.is_default,
      };
      if (editingId !== null) {
        await ApiService.updateTrackLayout(editingId, payload);
      } else {
        await ApiService.createTrackLayout(track.id, payload);
      }
      setForm({ name: '', min_field_best: '', max_field_best: '', is_default: false });
      setEditingId(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save layout');
    }
  };

  const startEdit = (l: LayoutEntry) => {
    setEditingId(l.id);
    setForm({
      name: l.name,
      min_field_best: l.min_field_best === null ? '' : String(l.min_field_best),
      max_field_best: l.max_field_best === null ? '' : String(l.max_field_best),
      is_default: l.is_default,
    });
  };

  const remove = async (id: number) => {
    if (!confirm('Delete this layout? Sessions assigned to it will revert to unclassified and be re-backfilled on next fairness query.')) return;
    try {
      await ApiService.deleteTrackLayout(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete layout');
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-gray-800 text-white rounded-lg p-6 max-w-2xl w-full">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Layouts — {track.name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white">✕</button>
        </div>

        <p className="text-sm text-gray-400 mb-4">
          Define physical configurations. Sessions whose field-best falls in a layout&apos;s [min, max) band are
          assigned to it automatically. Fairness analytics filter on layout to avoid mixing configs whose lap times
          differ by 10%+. One layout can be marked default to catch sessions outside any band.
        </p>

        {error && <div className="bg-red-900 text-red-200 rounded p-2 mb-3 text-sm">{error}</div>}

        <div className="bg-gray-900 rounded p-3 mb-4">
          <div className="text-xs text-gray-400 mb-2">{editingId === null ? 'Add layout' : `Editing layout #${editingId}`}</div>
          <div className="grid grid-cols-2 gap-2">
            <input
              type="text"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="name (e.g. short / long / wet)"
              className="col-span-2 px-3 py-2 bg-gray-700 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
            />
            <input
              type="number"
              step={0.1}
              value={form.min_field_best}
              onChange={e => setForm(f => ({ ...f, min_field_best: e.target.value }))}
              placeholder="min field-best (s)"
              className="px-3 py-2 bg-gray-700 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
            />
            <input
              type="number"
              step={0.1}
              value={form.max_field_best}
              onChange={e => setForm(f => ({ ...f, max_field_best: e.target.value }))}
              placeholder="max field-best (s)"
              className="px-3 py-2 bg-gray-700 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
            />
            <label className="col-span-2 flex items-center gap-2 text-sm text-gray-300">
              <input
                type="checkbox"
                checked={form.is_default}
                onChange={e => setForm(f => ({ ...f, is_default: e.target.checked }))}
              />
              default (fallback when no band matches)
            </label>
          </div>
          <div className="flex gap-2 mt-2">
            <button onClick={submit} className="px-3 py-1 bg-blue-600 rounded hover:bg-blue-700 text-sm">
              {editingId === null ? 'Add' : 'Save'}
            </button>
            {editingId !== null && (
              <button
                onClick={() => {
                  setEditingId(null);
                  setForm({ name: '', min_field_best: '', max_field_best: '', is_default: false });
                }}
                className="px-3 py-1 bg-gray-700 rounded hover:bg-gray-600 text-sm"
              >
                Cancel edit
              </button>
            )}
          </div>
        </div>

        {loading && <div className="text-gray-400 text-sm">Loading…</div>}
        {!loading && layouts.length === 0 && (
          <div className="text-gray-500 text-sm italic">No layouts defined yet.</div>
        )}
        {!loading && layouts.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-700">
              <tr className="text-left">
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Min</th>
                <th className="px-3 py-2">Max</th>
                <th className="px-3 py-2">Default</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {layouts.map(l => (
                <tr key={l.id} className="border-b border-gray-700">
                  <td className="px-3 py-2 text-white">{l.name}</td>
                  <td className="px-3 py-2 text-gray-300">{l.min_field_best ?? '—'}</td>
                  <td className="px-3 py-2 text-gray-300">{l.max_field_best ?? '—'}</td>
                  <td className="px-3 py-2 text-gray-300">{l.is_default ? '★' : ''}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => startEdit(l)} className="text-blue-400 hover:text-blue-300 mr-3">Edit</button>
                    <button onClick={() => remove(l.id)} className="text-red-400 hover:text-red-300">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="flex justify-end mt-4">
          <button onClick={onClose} className="px-4 py-2 bg-gray-700 rounded hover:bg-gray-600">Close</button>
        </div>
      </div>
    </div>
  );
}
