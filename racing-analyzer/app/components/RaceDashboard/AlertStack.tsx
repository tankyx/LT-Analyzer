'use client';

import React from 'react';
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react';
import Button from '../../ui/Button';
import IconButton from '../../ui/IconButton';

export interface DashboardAlert {
  id: number;
  message: string;
  type?: 'info' | 'warning' | 'success' | 'error';
  customContent?: React.ReactNode;
  teamKart?: string;
  fleetKartId?: number;
  persistent?: boolean;
  action?: { label: string; onClick: () => void };
}

interface AlertStackProps {
  alerts: DashboardAlert[];
  onDismiss: (id: number) => void;
  onLocate?: (kart: string) => void;
}

const TONE: Record<NonNullable<DashboardAlert['type']>, { wrap: string; icon: React.ReactNode }> = {
  error: { wrap: 'border-alarm/50 bg-surface text-ink', icon: <XCircle size={18} className="text-alarm shrink-0" /> },
  warning: { wrap: 'border-accent/60 bg-surface text-ink', icon: <AlertTriangle size={18} className="text-accent shrink-0" /> },
  success: { wrap: 'border-live/50 bg-surface text-ink', icon: <CheckCircle2 size={18} className="text-live shrink-0" /> },
  info: { wrap: 'border-info/50 bg-surface text-ink', icon: <Info size={18} className="text-info shrink-0" /> },
};

/** Toast stack: top-right on desktop, top edge on phones. */
const AlertStack: React.FC<AlertStackProps> = ({ alerts, onDismiss, onLocate }) => {
  if (alerts.length === 0) return null;
  return (
    <div
      className="fixed z-50 top-16 inset-x-2 md:inset-x-auto md:right-4 md:w-[380px] flex flex-col gap-2 pointer-events-none"
      aria-live="polite"
    >
      {alerts.map((alert) => {
        const t = TONE[alert.type || 'info'];
        const isPit = alert.message.includes('in the pits');
        return (
          <div
            key={alert.id}
            role="status"
            className={`pointer-events-auto flex items-start gap-3 p-3 border shadow-overlay ${t.wrap} ${isPit ? 'pit-alert' : ''}`}
          >
            {!alert.customContent && t.icon}
            <div className="flex-1 min-w-0 text-sm">{alert.customContent || alert.message}</div>
            <div className="flex items-center gap-1 shrink-0">
              {isPit && alert.teamKart && onLocate && (
                <Button size="sm" onClick={() => onLocate(alert.teamKart!)}>
                  Locate
                </Button>
              )}
              {alert.action && (
                <Button size="sm" onClick={() => { alert.action!.onClick(); onDismiss(alert.id); }}>
                  {alert.action.label}
                </Button>
              )}
              <IconButton label="Dismiss" size="sm" onClick={() => onDismiss(alert.id)}>
                <X size={16} />
              </IconButton>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default AlertStack;
