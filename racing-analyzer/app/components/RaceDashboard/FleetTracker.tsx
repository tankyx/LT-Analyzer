'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext, DragOverlay, PointerSensor, TouchSensor, useSensor, useSensors,
  useDraggable, useDroppable, closestCenter,
  DragStartEvent, DragEndEvent,
} from '@dnd-kit/core';
import ApiService from '../../services/ApiService';
import { FleetKartState } from '../../services/WebSocketService';

// Physical-kart registry item (mirrors the backend fleet_karts row).
export interface FleetKart {
  id: number;
  label: string;
  notes?: string | null;
  is_active: boolean;
}

interface FleetTrackerProps {
  isDarkMode?: boolean;
  fleetBoard: FleetKartState[];
  registry: FleetKart[];
  trackId: number;
  sessionId?: number | null;
  isActive?: boolean;
  canEditRegistry: boolean;
  onReassign: (fleetKartId: number) => void;
  onAddAssignment: () => void;
  onRegistryChange: () => void;
}

const DEFAULT_LANES = 4;
const MAX_LANES = 8;

// Selectable lane colors — literal class strings so Tailwind keeps them.
interface ColorOpt { key: string; light: string; dark: string; dot: string; }
const COLOR_OPTIONS: ColorOpt[] = [
  { key: 'blue', light: 'bg-blue-50 border-blue-300', dark: 'bg-blue-900/30 border-blue-700', dot: 'bg-blue-500' },
  { key: 'emerald', light: 'bg-emerald-50 border-emerald-300', dark: 'bg-emerald-900/30 border-emerald-700', dot: 'bg-emerald-500' },
  { key: 'amber', light: 'bg-amber-50 border-amber-300', dark: 'bg-amber-900/30 border-amber-700', dot: 'bg-amber-500' },
  { key: 'violet', light: 'bg-violet-50 border-violet-300', dark: 'bg-violet-900/30 border-violet-700', dot: 'bg-violet-500' },
  { key: 'rose', light: 'bg-rose-50 border-rose-300', dark: 'bg-rose-900/30 border-rose-700', dot: 'bg-rose-500' },
  { key: 'cyan', light: 'bg-cyan-50 border-cyan-300', dark: 'bg-cyan-900/30 border-cyan-700', dot: 'bg-cyan-500' },
  { key: 'lime', light: 'bg-lime-50 border-lime-300', dark: 'bg-lime-900/30 border-lime-700', dot: 'bg-lime-500' },
  { key: 'orange', light: 'bg-orange-50 border-orange-300', dark: 'bg-orange-900/30 border-orange-700', dot: 'bg-orange-500' },
  { key: 'pink', light: 'bg-pink-50 border-pink-300', dark: 'bg-pink-900/30 border-pink-700', dot: 'bg-pink-500' },
  { key: 'slate', light: 'bg-slate-100 border-slate-300', dark: 'bg-slate-700/40 border-slate-600', dot: 'bg-slate-500' },
];
const COLOR_MAP: Record<string, ColorOpt> = Object.fromEntries(COLOR_OPTIONS.map(c => [c.key, c]));
const defaultColorKey = (lane: number) => COLOR_OPTIONS[(lane - 1) % COLOR_OPTIONS.length].key;

const fmtDelta = (d: number | null): string =>
  d == null ? '' : `${d < 0 ? '-' : '+'}${Math.abs(d).toFixed(1)}s`;

const paceChipClass = (cls: string, dark: boolean) => {
  if (cls === 'fast') return dark ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-800';
  if (cls === 'slow') return dark ? 'bg-red-900 text-red-200' : 'bg-red-100 text-red-800';
  if (cls === 'insufficient') return dark ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-500';
  return dark ? 'bg-gray-700 text-gray-200' : 'bg-gray-100 text-gray-700';
};

// Presentational card body, shared by the draggable card and the drag overlay.
const CardBody: React.FC<{ kart: FleetKartState; isDarkMode: boolean }> = ({ kart, isDarkMode }) => {
  const subtle = isDarkMode ? 'text-gray-400' : 'text-gray-500';
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="font-bold">{kart.label}</span>
        {kart.classification !== 'insufficient' && kart.pace_delta_vs_fleet != null ? (
          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${paceChipClass(kart.classification, isDarkMode)}`}
            data-testid="pace-chip">{fmtDelta(kart.pace_delta_vs_fleet)}</span>
        ) : (
          <span className={`px-2 py-0.5 rounded-full text-xs ${paceChipClass('insufficient', isDarkMode)}`}>low data</span>
        )}
      </div>
      <div className={`text-xs mt-1 ${subtle}`}>
        {kart.holder_team
          ? <>{kart.holder_team}{kart.holder_kart_number != null ? ` #${kart.holder_kart_number}` : ''}{kart.holder_position != null ? ` · P${kart.holder_position}` : ''}</>
          : 'unassigned'}
      </div>
    </>
  );
};

// Draggable kart card. A plain click (no drag movement) opens the action sheet.
const KartCard: React.FC<{ kart: FleetKartState; isDarkMode: boolean; onSelect: (k: FleetKartState) => void; }> =
  ({ kart, isDarkMode, onSelect }) => {
    const { attributes, listeners, setNodeRef, transform, isDragging } =
      useDraggable({ id: `kart-${kart.fleet_kart_id}`, data: { kart } });
    const cardBase = isDarkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200 text-gray-900';
    return (
      <div
        ref={setNodeRef}
        style={transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined}
        {...listeners} {...attributes}
        data-testid="fleet-kart-card"
        onClick={() => onSelect(kart)}
        className={`rounded-lg border p-2 mb-2 cursor-grab active:cursor-grabbing touch-none ${cardBase} ${isDragging ? 'opacity-40' : ''}`}
      >
        <CardBody kart={kart} isDarkMode={isDarkMode} />
      </div>
    );
  };

// Droppable wrapper with an "over" highlight ring.
const Droppable: React.FC<{ id: string; className?: string; testId?: string; children: React.ReactNode; }> =
  ({ id, className = '', testId, children }) => {
    const { setNodeRef, isOver } = useDroppable({ id });
    return (
      <div ref={setNodeRef} data-testid={testId}
        className={`${className} ${isOver ? 'ring-2 ring-blue-500' : ''}`}>
        {children}
      </div>
    );
  };

function byPace(a: FleetKartState, b: FleetKartState): number {
  if (a.pace_delta_vs_fleet == null && b.pace_delta_vs_fleet == null) return a.label.localeCompare(b.label);
  if (a.pace_delta_vs_fleet == null) return 1;
  if (b.pace_delta_vs_fleet == null) return -1;
  return a.pace_delta_vs_fleet - b.pace_delta_vs_fleet;
}

const FleetTracker: React.FC<FleetTrackerProps> = ({
  isDarkMode = false, fleetBoard, registry, trackId, sessionId, isActive, canEditRegistry,
  onReassign, onAddAssignment, onRegistryChange,
}) => {
  const [showRegistry, setShowRegistry] = useState(false);
  const [newLabel, setNewLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [autoMsg, setAutoMsg] = useState<string | null>(null);
  const [laneCount, setLaneCount] = useState(DEFAULT_LANES);
  const [laneColors, setLaneColors] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<FleetKartState | null>(null);
  const [activeKart, setActiveKart] = useState<FleetKartState | null>(null);
  const autoAttemptedTrack = useRef<number | null>(null);

  const sensors = useSensors(
    // Desktop: a small move threshold so plain clicks still open the sheet.
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    // Touch: long-press to start dragging; a quick tap opens the sheet.
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
  );

  // Per-track display prefs (lane count + colors), kept client-side.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const n = parseInt(window.localStorage.getItem(`fleet_lanes_${trackId}`) || '', 10);
    setLaneCount(Number.isFinite(n) && n >= 1 ? Math.min(n, MAX_LANES) : DEFAULT_LANES);
    try {
      setLaneColors(JSON.parse(window.localStorage.getItem(`fleet_lane_colors_${trackId}`) || '{}'));
    } catch { setLaneColors({}); }
  }, [trackId]);

  const persist = (lanes: number, colors: Record<number, string>) => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(`fleet_lanes_${trackId}`, String(lanes));
    window.localStorage.setItem(`fleet_lane_colors_${trackId}`, JSON.stringify(colors));
  };
  const changeLaneCount = (n: number) => {
    const c = Math.max(1, Math.min(MAX_LANES, n));
    setLaneCount(c); persist(c, laneColors);
  };
  const setLaneColor = (lane: number, key: string) => {
    const next = { ...laneColors, [lane]: key };
    setLaneColors(next); persist(laneCount, next);
  };
  const laneStyleFor = (lane: number) => COLOR_MAP[laneColors[lane] || defaultColorKey(lane)];

  const subtle = isDarkMode ? 'text-gray-400' : 'text-gray-500';
  const colHeader = isDarkMode ? 'text-gray-200' : 'text-gray-700';
  const columnWrap = isDarkMode ? 'bg-gray-900/40' : 'bg-gray-50';

  const onTrack = useMemo(() => fleetBoard.filter(k => k.column === 'on_track').sort(byPace), [fleetBoard]);
  const inPit = useMemo(() => fleetBoard.filter(k => k.column === 'in_pit').sort(byPace), [fleetBoard]);
  const available = useMemo(() => fleetBoard.filter(k => k.column === 'available'), [fleetBoard]);
  const unlaned = available.filter(k => k.lane == null);
  const lanes = Array.from({ length: laneCount }, (_, i) => i + 1);

  // ---- actions --------------------------------------------------------------
  const doRelease = async (kart: FleetKartState, lane: number | null) => {
    setBusy(true);
    try { await ApiService.releaseFleetKart(trackId, kart.fleet_kart_id, lane, sessionId ?? null); onRegistryChange(); }
    catch (err) { console.error('release failed', err); }
    finally { setBusy(false); setSelected(null); }
  };
  const doSetLane = async (kart: FleetKartState, lane: number | null) => {
    setBusy(true);
    try { await ApiService.setFleetKartLane(trackId, kart.fleet_kart_id, lane); onRegistryChange(); }
    catch (err) { console.error('move lane failed', err); }
    finally { setBusy(false); setSelected(null); }
  };
  const doAssign = (kart: FleetKartState) => { setSelected(null); onReassign(kart.fleet_kart_id); };

  // ---- drag-and-drop --------------------------------------------------------
  const handleDragStart = (e: DragStartEvent) => setActiveKart((e.active.data.current?.kart as FleetKartState) ?? null);
  const handleDragEnd = (e: DragEndEvent) => {
    setActiveKart(null);
    const kart = e.active.data.current?.kart as FleetKartState | undefined;
    const over = e.over?.id?.toString();
    if (!kart || !over) return;
    if (over === 'col-on-track') {
      if (kart.column === 'available') doAssign(kart);
    } else if (over.startsWith('lane-')) {
      const lane = parseInt(over.slice(5), 10);
      if (!Number.isFinite(lane)) return;
      if (kart.column === 'available') doSetLane(kart, lane);
      else doRelease(kart, lane);
    }
  };

  // ---- registry management --------------------------------------------------
  const handleAutoPopulate = async () => {
    setBusy(true); setAutoMsg(null);
    try {
      const res = await ApiService.autoPopulateFleet(trackId);
      const n = res.created_karts?.length ?? 0;
      setAutoMsg(n > 0 ? `Added ${n} kart${n === 1 ? '' : 's'} from the session.` : 'Fleet already matches the session.');
      onRegistryChange();
    } catch (err) { setAutoMsg(`Auto-add failed: ${err instanceof Error ? err.message : 'error'}`); }
    finally { setBusy(false); }
  };
  const handleAddKart = async () => {
    const label = newLabel.trim();
    if (!label) return;
    setBusy(true);
    try { await ApiService.createFleetKart(trackId, label); setNewLabel(''); onRegistryChange(); }
    catch (err) { console.error('add kart failed', err); }
    finally { setBusy(false); }
  };
  const handleDeleteKart = async (kartId: number) => {
    setBusy(true);
    try { await ApiService.deleteFleetKart(trackId, kartId); onRegistryChange(); }
    catch (err) { console.error('delete kart failed', err); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (isActive && canEditRegistry && registry.length === 0 && sessionId != null
        && autoAttemptedTrack.current !== trackId && !busy) {
      autoAttemptedTrack.current = trackId;
      handleAutoPopulate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, canEditRegistry, registry.length, sessionId, trackId]);

  const cardBase = isDarkMode ? 'bg-gray-800 border-gray-700 text-gray-100' : 'bg-white border-gray-200 text-gray-900';

  return (
    <div className="p-3 sm:p-4">
      {/* Quick actions */}
      <div className="flex flex-wrap gap-2 mb-3">
        <button onClick={onAddAssignment}
          className="flex-1 min-h-[44px] px-4 rounded-lg font-semibold text-white bg-blue-600 hover:bg-blue-700">
          + Record kart assignment
        </button>
        {canEditRegistry && (
          <button onClick={() => setShowRegistry(s => !s)}
            className={`min-h-[44px] px-4 rounded-lg font-medium border ${isDarkMode ? 'border-gray-600 text-gray-200' : 'border-gray-300 text-gray-700'}`}>
            {showRegistry ? 'Close fleet' : 'Manage fleet'}
          </button>
        )}
      </div>

      {/* Registry + lane settings */}
      {canEditRegistry && showRegistry && (
        <div className={`mb-4 p-3 rounded-lg border ${cardBase}`}>
          <button onClick={handleAutoPopulate} disabled={busy}
            className="w-full min-h-[44px] mb-2 px-4 rounded-lg font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50">
            Auto-add karts from session
          </button>
          {autoMsg && <p className={`text-xs mb-3 ${subtle}`}>{autoMsg}</p>}

          <div className="flex items-center justify-between mb-3">
            <span className={`text-sm ${subtle}`}>Pit lanes</span>
            <div className="flex items-center gap-2">
              <button onClick={() => changeLaneCount(laneCount - 1)}
                className={`w-9 h-9 rounded-lg border text-lg ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>−</button>
              <span className="w-6 text-center font-semibold">{laneCount}</span>
              <button onClick={() => changeLaneCount(laneCount + 1)}
                className={`w-9 h-9 rounded-lg border text-lg ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>+</button>
            </div>
          </div>

          {/* Lane color editor */}
          <div className="mb-3" data-testid="lane-color-editor">
            <span className={`text-sm ${subtle}`}>Lane colors</span>
            {lanes.map(lane => (
              <div key={lane} className="flex items-center gap-2 mt-1 flex-wrap">
                <span className={`w-3 h-3 rounded-full ${laneStyleFor(lane).dot}`} />
                <span className={`text-xs w-12 ${colHeader}`}>Lane {lane}</span>
                {COLOR_OPTIONS.map(c => {
                  const isSel = (laneColors[lane] || defaultColorKey(lane)) === c.key;
                  return (
                    <button key={c.key} aria-label={`Lane ${lane} ${c.key}`}
                      onClick={() => setLaneColor(lane, c.key)}
                      className={`w-6 h-6 rounded-full ${c.dot} ${isSel ? 'ring-2 ring-offset-1 ring-gray-500' : ''}`} />
                  );
                })}
              </div>
            ))}
          </div>

          <div className="flex gap-2 mb-2">
            <input value={newLabel} onChange={e => setNewLabel(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAddKart(); }}
              placeholder="Add a kart (e.g. K-12)"
              className={`flex-1 min-h-[44px] px-3 rounded-lg border ${isDarkMode ? 'bg-gray-900 border-gray-600 text-white' : 'bg-white border-gray-300'}`} />
            <button onClick={handleAddKart} disabled={busy || !newLabel.trim()}
              className="min-h-[44px] px-4 rounded-lg font-semibold text-white bg-green-600 hover:bg-green-700 disabled:opacity-50">Add</button>
          </div>
          {registry.length > 0 && (
            <ul className="space-y-1 max-h-32 overflow-y-auto">
              {registry.map(k => (
                <li key={k.id} className="flex items-center justify-between text-sm">
                  <span>{k.label}</span>
                  <button onClick={() => handleDeleteKart(k.id)} disabled={busy}
                    className="min-h-[36px] px-3 text-red-500 hover:text-red-600">Retire</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {registry.length === 0 ? (
        <div className={`text-center py-10 ${subtle}`}>
          <p className="font-medium">No physical karts registered yet.</p>
          {canEditRegistry ? (
            <>
              <p className="text-sm mt-1 mb-4">One tap creates a kart for every team in the session.</p>
              <button onClick={handleAutoPopulate} disabled={busy}
                className="min-h-[44px] px-5 rounded-lg font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50">
                Auto-add karts from session
              </button>
              {autoMsg && <p className="text-xs mt-3">{autoMsg}</p>}
            </>
          ) : <p className="text-sm mt-1">Ask an admin to set up the fleet.</p>}
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter}
          onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="flex flex-col gap-3">
            {/* Top row: On track + In pit side by side */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* On track (also a drop target: assign an Available kart) */}
              <Droppable id="col-on-track" testId="col-on-track" className={`rounded-lg p-2 ${columnWrap}`}>
                <h3 className={`font-semibold mb-2 ${colHeader}`}>On track <span className={subtle}>({onTrack.length})</span></h3>
                {onTrack.map(k => <KartCard key={k.fleet_kart_id} kart={k} isDarkMode={isDarkMode} onSelect={setSelected} />)}
                {onTrack.length === 0 && <p className={`text-xs ${subtle}`}>Drag an Available kart here to assign it.</p>}
              </Droppable>

              {/* In pit (timing-driven; not a drop target) */}
              <div className={`rounded-lg p-2 ${columnWrap}`} data-testid="col-in-pit">
                <h3 className={`font-semibold mb-2 ${colHeader}`}>In pit <span className={subtle}>({inPit.length})</span></h3>
                {inPit.map(k => <KartCard key={k.fleet_kart_id} kart={k} isDarkMode={isDarkMode} onSelect={setSelected} />)}
                {inPit.length === 0 && <p className={`text-xs ${subtle}`}>Teams currently in the pits appear here.</p>}
              </div>
            </div>

            {/* Available: full width, lanes laid out horizontally (parallel) */}
            <div className={`rounded-lg p-2 ${columnWrap}`} data-testid="col-available">
              <h3 className={`font-semibold mb-2 ${colHeader}`}>Available <span className={subtle}>({available.length})</span></h3>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {lanes.map(lane => {
                  const st = laneStyleFor(lane);
                  const karts = available.filter(k => k.lane === lane);
                  return (
                    <Droppable key={lane} id={`lane-${lane}`} testId={`lane-${lane}`}
                      className={`rounded-lg border p-2 flex-1 min-w-[9rem] self-start ${isDarkMode ? st.dark : st.light}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`w-3 h-3 rounded-full ${st.dot}`} />
                        <span className={`text-xs font-medium ${colHeader}`}>Lane {lane}</span>
                      </div>
                      {karts.map(k => <KartCard key={k.fleet_kart_id} kart={k} isDarkMode={isDarkMode} onSelect={setSelected} />)}
                      {karts.length === 0 && <p className={`text-xs ${subtle}`}>empty</p>}
                    </Droppable>
                  );
                })}
              </div>
              {unlaned.length > 0 && (
                <div data-testid="lane-unsorted"
                  className={`rounded-lg border border-dashed p-2 mt-2 ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                  <span className={`text-xs font-medium ${colHeader}`}>Just dropped — place in a lane</span>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {unlaned.map(k => (
                      <div key={k.fleet_kart_id} className="min-w-[9rem]">
                        <KartCard kart={k} isDarkMode={isDarkMode} onSelect={setSelected} />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <DragOverlay>
            {activeKart ? (
              <div className={`rounded-lg border p-2 shadow-lg ${cardBase}`}>
                <CardBody kart={activeKart} isDarkMode={isDarkMode} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      )}

      {/* Tap-to-move action sheet */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50"
          onClick={() => setSelected(null)} data-testid="kart-action-sheet">
          <div onClick={e => e.stopPropagation()}
            className={`w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-xl p-4 sm:p-6 ${isDarkMode ? 'bg-gray-800 text-gray-100' : 'bg-white text-gray-900'}`}>
            <h2 className="text-lg font-bold mb-1">Kart {selected.label}</h2>
            <p className={`text-sm mb-4 ${subtle}`}>
              {selected.column === 'available'
                ? (selected.lane != null ? `In lane ${selected.lane}` : 'Just dropped (no lane)')
                : `On ${selected.holder_team || 'a team'}${selected.holder_kart_number != null ? ` #${selected.holder_kart_number}` : ''} (${selected.column === 'in_pit' ? 'in pit' : 'on track'})`}
            </p>

            {selected.column === 'available' ? (
              <>
                <button onClick={() => doAssign(selected)}
                  className="w-full min-h-[48px] mb-3 rounded-lg font-semibold text-white bg-blue-600 hover:bg-blue-700">
                  Assign to a team…
                </button>
                <p className={`text-sm mb-2 ${subtle}`}>Move to lane</p>
              </>
            ) : (
              <p className={`text-sm mb-2 ${subtle}`}>Team dropped it — release to lane</p>
            )}

            <div className="flex flex-wrap gap-2 mb-2">
              {lanes.map(lane => {
                const st = laneStyleFor(lane);
                return (
                  <button key={lane} disabled={busy}
                    onClick={() => selected.column === 'available' ? doSetLane(selected, lane) : doRelease(selected, lane)}
                    className={`min-h-[44px] px-4 rounded-lg border font-medium flex items-center gap-2 ${isDarkMode ? st.dark : st.light}`}>
                    <span className={`w-3 h-3 rounded-full ${st.dot}`} />Lane {lane}
                  </button>
                );
              })}
            </div>

            <button onClick={() => setSelected(null)}
              className={`w-full min-h-[44px] mt-2 rounded-lg font-medium border ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default FleetTracker;
