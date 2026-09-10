'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Search, Settings, X } from 'lucide-react';
import { buildTrackTrie, searchTrackTrie } from './lib/trackTrie';

export interface RailTrack {
  track_id: number;
  track_name: string;
  active: boolean;
  teams_count?: number;
  provider?: string;
  last_update?: string;
}

const PROVIDER_LABEL: Record<string, string> = { apex: 'Apex', alphahub: 'AlphaHub' };

/**
 * Split tracks into live / idle groups (each alphabetical) after applying the
 * trie-backed search. Provider names are searchable too ("alpha", "apex").
 */
export function groupTracks(tracks: RailTrack[], query: string): { live: RailTrack[]; idle: RailTrack[] } {
  const sorted = [...tracks].sort((a, b) =>
    (a.track_name || '').toLowerCase().localeCompare((b.track_name || '').toLowerCase()),
  );
  const trie = buildTrackTrie(
    sorted.map((t) => ({
      track_id: t.track_id,
      track_name: t.track_name,
      extra_tokens: t.provider ? [t.provider] : undefined,
    })),
  );
  const ids = searchTrackTrie(trie, query);
  const visible = ids === null ? sorted : sorted.filter((t) => ids.has(t.track_id));
  return {
    live: visible.filter((t) => t.active),
    idle: visible.filter((t) => !t.active),
  };
}

interface TrackRailProps {
  tracks: RailTrack[];
  selectedTrackId: number;
  onSelect: (trackId: number) => void;
  /** `rail` = persistent desktop sidebar; `sheet` = full-screen picker (phones / narrow). */
  variant?: 'rail' | 'sheet';
  onClose?: () => void;
  isAdmin?: boolean;
  onOpenAdmin?: () => void;
}

const TrackRail: React.FC<TrackRailProps> = ({
  tracks,
  selectedTrackId,
  onSelect,
  variant = 'rail',
  onClose,
  isAdmin = false,
  onOpenAdmin,
}) => {
  const [query, setQuery] = useState('');
  const { live, idle } = useMemo(() => groupTracks(tracks, query), [tracks, query]);
  const isSheet = variant === 'sheet';

  useEffect(() => {
    if (!isSheet) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose?.();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isSheet, onClose]);

  const pick = (id: number) => {
    onSelect(id);
    if (isSheet) onClose?.();
  };

  const renderItem = (t: RailTrack) => {
    const selected = t.track_id === selectedTrackId;
    return (
      <button
        key={t.track_id}
        type="button"
        onClick={() => pick(t.track_id)}
        aria-current={selected ? 'true' : undefined}
        className={`w-full flex items-center gap-2.5 min-h-11 md:min-h-10 px-3 rounded-lg text-left border transition-colors ${
          selected ? 'bg-surface-2 border-line' : 'border-transparent hover:bg-surface-2/60'
        }`}
      >
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${t.active ? 'bg-live animate-live-blink' : 'bg-line'}`}
        />
        <span className="flex flex-col min-w-0 flex-1 py-1.5">
          <span
            className={`text-sm truncate ${selected ? 'font-semibold text-ink' : t.active ? 'font-medium text-ink' : 'text-muted'}`}
          >
            {t.track_name}
          </span>
          {t.active && (
            <span className="text-[11px] text-muted">
              {t.teams_count !== undefined ? `${t.teams_count} teams · ` : ''}
              {PROVIDER_LABEL[t.provider || 'apex'] || t.provider}
            </span>
          )}
        </span>
      </button>
    );
  };

  const body = (
    <>
      <div className="relative shrink-0">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${tracks.length} tracks`}
          aria-label="Search tracks"
          autoFocus={isSheet}
          className="w-full h-10 md:h-9 pl-9 pr-8 rounded-lg border border-line bg-canvas text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery('')}
            aria-label="Clear search"
            className="absolute right-1 top-1/2 -translate-y-1/2 w-8 h-8 flex items-center justify-center text-muted hover:text-ink"
          >
            <X size={14} />
          </button>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scroll-thin flex flex-col gap-3 -mx-1 px-1">
        {tracks.length === 0 ? (
          <div className="text-sm text-muted px-3 py-2">No tracks configured</div>
        ) : live.length + idle.length === 0 ? (
          <div className="text-sm text-muted px-3 py-2">No tracks match &ldquo;{query}&rdquo;</div>
        ) : (
          <>
            {live.length > 0 && (
              <div className="flex flex-col gap-0.5">
                <div className="text-[11px] font-bold tracking-[.08em] uppercase text-live px-3 pt-1 pb-1">
                  Live now · {live.length}
                </div>
                {live.map(renderItem)}
              </div>
            )}
            {idle.length > 0 && (
              <div className="flex flex-col gap-0.5">
                <div className="text-[11px] font-bold tracking-[.08em] uppercase text-muted px-3 pt-1 pb-1">
                  Idle · {idle.length}
                </div>
                {idle.map(renderItem)}
              </div>
            )}
          </>
        )}
      </div>

      {isAdmin && onOpenAdmin && (
        <button
          type="button"
          onClick={onOpenAdmin}
          className="shrink-0 flex items-center gap-2 h-10 px-3 rounded-lg text-sm text-muted hover:text-ink hover:bg-surface-2"
        >
          <Settings size={15} />
          Admin
        </button>
      )}
    </>
  );

  if (!isSheet) {
    return (
      <div className="h-full flex flex-col gap-3 p-3 bg-surface border-r border-line" data-testid="track-rail">
        {body}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end md:justify-center md:items-center" role="dialog" aria-modal="true" aria-label="Choose a track">
      <button type="button" aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/60" />
      <div className="relative flex flex-col gap-3 p-3 pb-[max(12px,env(safe-area-inset-bottom))] bg-surface border border-line rounded-t-2xl md:rounded-2xl w-full md:w-[440px] h-[85vh] md:h-[70vh] shadow-2xl">
        <div className="flex items-center justify-between px-1">
          <span className="font-cond font-bold text-lg tracking-wide">TRACKS</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close track picker"
            className="w-10 h-10 flex items-center justify-center rounded-lg text-muted hover:text-ink hover:bg-surface-2"
          >
            <X size={18} />
          </button>
        </div>
        {body}
      </div>
    </div>
  );
};

export default TrackRail;
