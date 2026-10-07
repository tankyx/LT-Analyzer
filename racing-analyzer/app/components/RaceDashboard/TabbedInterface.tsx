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
  /**
   * id of a tab whose panel is pinned as a persistent left column on desktop
   * (the timing tower). The remaining tabs become the bottom console dock.
   * The pinned panel must be purely presentational (rendered twice: once in
   * the desktop tower, once as a normal panel on phones).
   */
  pinnedId?: string;
  /** Always-visible header above the active panel (e.g. the My-team strip). */
  top?: React.ReactNode;
}

/**
 * The pit-wall shell. On desktop it shows the pinned tower on the left and a
 * single active workbench panel on the right, switched by a bottom console
 * dock. On phones it collapses to one active panel with a thumb-reach bottom
 * nav. Panels stay mounted and are hidden, so charts and planners keep their
 * state when the user switches away.
 */
const TabbedInterface: React.FC<TabbedInterfaceProps> = ({
  tabs,
  defaultTab,
  children,
  onTabChange,
  pinnedId,
  top,
}) => {
  const [activeTab, setActiveTab] = useState<string>(defaultTab || tabs[0]?.id || '');

  const pinnedIndex = pinnedId ? tabs.findIndex((t) => t.id === pinnedId) : -1;
  const pinnedTab = pinnedIndex >= 0 ? tabs[pinnedIndex] : undefined;
  const dockTabs = pinnedTab ? tabs.filter((t) => t.id !== pinnedId) : tabs;

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

  const onTablistKeyDown = (list: TabProps[], e: React.KeyboardEvent) => {
    const idx = list.findIndex((t) => t.id === activeTab);
    let next: number | null = null;
    if (e.key === 'ArrowRight') next = (idx + 1) % list.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + list.length) % list.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = list.length - 1;
    if (next === null) return;
    e.preventDefault();
    const target = list[next];
    handleTabChange(target.id);
    document.getElementById(tabId(target.id))?.focus();
  };

  // On desktop the pinned panel is always visible, so the active workbench
  // panel must always be a non-pinned one.
  const workbenchTab = pinnedTab && activeTab === pinnedId ? dockTabs[0]?.id : activeTab;

  return (
    <div className="flex-1 flex min-h-0 w-full">
      {/* Desktop: pinned timing tower */}
      {pinnedTab && (
        <aside className="hidden lg:flex w-[340px] xl:w-[380px] shrink-0 flex-col border-r border-line bg-surface min-h-0">
          {children[pinnedIndex]}
        </aside>
      )}

      {/* Workbench column */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        {/* Scrollable content: header + active panel */}
        <div className="flex-1 overflow-y-auto scroll-thin p-3 md:p-5 pb-24 lg:pb-5 flex flex-col gap-3 md:gap-4">
          {top}
          {children.map((child, index) => {
            const tab = tabs[index];
            if (!tab) return null;
            if (tab.id === pinnedId) {
              // Pinned panel: phones get it as a normal tab panel.
              return (
                <div key={tab.id} role="tabpanel" id={panelId(tab.id)} aria-labelledby={tabId(tab.id)} className="lg:hidden" hidden={activeTab !== tab.id}>
                  {child}
                </div>
              );
            }
            return (
              <div key={tab.id} role="tabpanel" id={panelId(tab.id)} aria-labelledby={tabId(tab.id)} hidden={workbenchTab !== tab.id}>
                {child}
              </div>
            );
          })}
        </div>

        {/* Desktop: bottom console dock (non-pinned tools) */}
        {pinnedTab && (
          <nav
            role="tablist"
            aria-label="Dashboard tools"
            className="hidden lg:flex shrink-0 items-stretch border-t border-line bg-surface px-3 py-2 gap-2 overflow-x-auto scroll-thin"
            onKeyDown={(e) => onTablistKeyDown(dockTabs, e)}
          >
            {dockTabs.map((tab) => {
              const active = workbenchTab === tab.id;
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
                  className={`relative flex flex-col items-center justify-center gap-1 min-w-[72px] px-3 py-2 rounded-none border text-xs font-semibold transition-all ${
                    active
                      ? 'bg-accent text-accent-ink border-accent shadow-[0_0_18px_-2px_rgb(var(--c-accent)/0.9)]'
                      : 'bg-surface text-muted border-line hover:text-ink hover:bg-surface-2 hover:border-muted'
                  }`}
                >
                  {tab.icon}
                  <span className="truncate max-w-full">{tab.label}</span>
                  {tab.count !== undefined && (
                    <span
                      className={`absolute -top-1.5 -right-1.5 font-mono tabular text-[10px] leading-none px-1 py-0.5 rounded-none ${
                        active ? 'bg-accent-ink/85 text-accent' : 'bg-line text-muted'
                      }`}
                    >
                      {tab.count}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        )}

        {/* Phone: fixed bottom tab bar (a nav, not a second tablist). */}
        <nav
          aria-label="Dashboard sections"
          className="lg:hidden fixed bottom-0 inset-x-0 z-40 flex items-stretch border-t border-line bg-surface/80 backdrop-blur-md pb-[env(safe-area-inset-bottom)]"
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
                {active && (
                  <span className="absolute top-0 inset-x-0 h-[3px] bg-accent shadow-[0_0_10px_rgb(var(--c-accent)/0.9)]" aria-hidden />
                )}
                {tab.icon}
                <span className="truncate max-w-full px-1">{tab.label}</span>
                {tab.count !== undefined && tab.count > 0 && (
                  <span className="absolute top-1.5 right-[calc(50%-22px)] font-mono tabular text-[10px] leading-none px-1 py-0.5 rounded-none bg-line text-muted">
                    {tab.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>
    </div>
  );
};

export default TabbedInterface;
