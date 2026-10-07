import React, { useEffect, useRef, useState } from 'react';

export interface TabProps {
  id: string;
  label: string;
  icon?: React.ReactNode;
  count?: number;
  /** One-line explanation shown as a hover tooltip on the tab. */
  hint?: string;
}

interface TabbedInterfaceProps {
  tabs: TabProps[];
  defaultTab?: string;
  children: React.ReactNode[];
  /** Kept for call-site compatibility; theming now comes from CSS tokens. */
  isDarkMode?: boolean;
  onTabChange?: (tabId: string) => void;
}

/**
 * Tabs with two navigations for one state: a segmented bar above the content
 * on desktop, and a fixed bottom tab bar (thumb reach, 44px+ targets) on
 * phones. Panels stay mounted and are hidden, so charts and planners keep
 * their state when the user switches away.
 */
const TabbedInterface: React.FC<TabbedInterfaceProps> = ({
  tabs,
  defaultTab,
  children,
  onTabChange,
}) => {
  const [activeTab, setActiveTab] = useState<string>(defaultTab || tabs[0]?.id || '');

  const handleTabChange = (tabId: string) => {
    setActiveTab(tabId);
    onTabChange?.(tabId);
  };

  // Keyboard accelerator: 1-9 jumps straight to a tab. Ignored while typing
  // in a field or when a modifier is held. Ref-mirrored so the listener is
  // registered once, not per live update (~1/s).
  const tabsRef = useRef(tabs);
  useEffect(() => { tabsRef.current = tabs; }, [tabs]);
  const changeRef = useRef(handleTabChange);
  useEffect(() => { changeRef.current = handleTabChange; });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const idx = parseInt(e.key, 10);
      if (idx >= 1 && idx <= tabsRef.current.length) {
        e.preventDefault();
        changeRef.current(tabsRef.current[idx - 1].id);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const panelId = (id: string) => `tab-panel-${id}`;
  const tabId = (id: string) => `tab-${id}`;

  const onTablistKeyDown = (e: React.KeyboardEvent) => {
    const idx = tabs.findIndex((t) => t.id === activeTab);
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (idx + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    const target = tabs[next];
    handleTabChange(target.id);
    document.getElementById(tabId(target.id))?.focus();
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Desktop: segmented tab bar */}
      <div role="tablist" aria-label="Dashboard sections" className="hidden md:flex items-center gap-1.5" onKeyDown={onTablistKeyDown}>
        {tabs.map((tab) => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              role="tab"
              id={tabId(tab.id)}
              aria-selected={active}
              aria-controls={panelId(tab.id)}
              tabIndex={active ? 0 : -1}
              title={tab.hint}
              onClick={() => handleTabChange(tab.id)}
              className={`flex items-center gap-2 h-10 px-3.5 rounded-lg text-sm font-semibold border transition-colors ${
                active
                  ? 'bg-surface-2 text-ink border-line'
                  : 'text-muted border-transparent hover:text-ink hover:bg-surface'
              }`}
            >
              {tab.icon}
              {tab.label}
              {tab.count !== undefined && (
                <span
                  className={`font-mono tabular text-[11px] px-1.5 py-px rounded-full ${
                    active ? 'bg-accent text-accent-ink' : 'bg-line text-muted'
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Panels */}
      <div>
        {children.map((child, index) => {
          const tab = tabs[index];
          if (!tab) return null;
          return (
            <div key={tab.id} role="tabpanel" id={panelId(tab.id)} aria-labelledby={tabId(tab.id)} hidden={activeTab !== tab.id}>
              {child}
            </div>
          );
        })}
      </div>

      {/* Phone: fixed bottom tab bar (a nav, not a second tablist — one
          logical tablist per surface, this is the thumb-reach navigator). */}
      <nav
        aria-label="Dashboard sections"
        className="md:hidden fixed bottom-0 inset-x-0 z-40 flex items-stretch border-t border-line bg-surface/80 backdrop-blur-md pb-[env(safe-area-inset-bottom)]"
      >
        {tabs.map((tab) => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              aria-current={active ? 'page' : undefined}
              title={tab.hint}
              className={`relative flex-1 min-w-0 h-14 flex flex-col items-center justify-center gap-1 text-[11px] font-semibold ${
                active ? 'text-accent' : 'text-muted'
              }`}
            >
              {tab.icon}
              <span className="truncate max-w-full px-1">{tab.label}</span>
              {tab.count !== undefined && tab.count > 0 && (
                <span className="absolute top-1.5 right-[calc(50%-22px)] font-mono tabular text-[10px] leading-none px-1 py-0.5 rounded-full bg-line text-muted">
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
};

export default TabbedInterface;
