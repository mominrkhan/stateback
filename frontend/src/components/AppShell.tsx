import { Dialog } from "@base-ui/react/dialog";
import { Activity, Command, LayoutDashboard, LogOut, Menu, Plug, RotateCcw, Search, ShieldCheck, X, type LucideIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent, type ReactNode, type RefObject } from "react";

interface AppShellProps { children: ReactNode; currentPath: string; onNavigate: (href: string) => void; onLogout: () => void }
interface NavigationLink { href: string; label: string; icon: LucideIcon }

const PRIMARY_LINKS: NavigationLink[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/operations", label: "Operations", icon: Activity },
  { href: "/approvals", label: "Approvals", icon: ShieldCheck },
  { href: "/providers", label: "Providers", icon: Plug },
];
const SECONDARY_LINKS: NavigationLink[] = [{ href: "/recovery", label: "Recovery", icon: RotateCcw }];

function selected(currentPath: string, href: string) {
  return href === "/" ? currentPath === "/" : currentPath === href || currentPath.startsWith(`${href}/`) || currentPath.startsWith(`${href}?`);
}

function StatebackMark() {
  return <span className="stateback-mark" aria-hidden="true"><i /><i /><i /></span>;
}

function Navigation({ currentPath, follow, firstLinkRef }: { currentPath: string; follow: (event: MouseEvent<HTMLAnchorElement>, href: string) => void; firstLinkRef?: RefObject<HTMLAnchorElement | null> }) {
  const renderLink = ({ href, label, icon: Icon }: NavigationLink) => <a key={href} ref={href === "/" ? firstLinkRef : undefined} href={href} aria-current={selected(currentPath, href) ? "page" : undefined} onClick={(event) => follow(event, href)}><Icon size={18} strokeWidth={1.8} aria-hidden="true" /><span>{label}</span></a>;
  return <><div className="app-navigation__brand"><StatebackMark /><span>Stateback</span></div><nav aria-label="Operator navigation">{PRIMARY_LINKS.map(renderLink)}<p className="app-navigation__group-label">System</p>{SECONDARY_LINKS.map(renderLink)}</nav><p className="app-navigation__footer">Transactions for AI agents</p></>;
}

function pageTitle(path: string) {
  if (path.startsWith("/operations/")) return "Operations / Detail";
  return [...PRIMARY_LINKS, ...SECONDARY_LINKS].find((link) => selected(path, link.href))?.label ?? "Stateback";
}

export function AppShell({ children, currentPath, onNavigate, onLogout }: AppShellProps) {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [query, setQuery] = useState("");
  const paletteInput = useRef<HTMLInputElement>(null);
  const mobileFirstLink = useRef<HTMLAnchorElement>(null);
  const mobileMenuTrigger = useRef<HTMLButtonElement>(null);
  const restoreMobileMenuFocus = useRef(false);
  const mobileFocusTimer = useRef<number | null>(null);

  useEffect(() => {
    restoreMobileMenuFocus.current = false;
    if (mobileFocusTimer.current !== null) window.clearTimeout(mobileFocusTimer.current);
    setNavigationOpen(false);
    setPaletteOpen(false);
  }, [currentPath]);
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPaletteOpen(true); }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  useLayoutEffect(() => {
    if (navigationOpen) mobileFirstLink.current?.focus({ preventScroll: true });
  }, [navigationOpen]);
  useLayoutEffect(() => {
    if (paletteOpen) paletteInput.current?.focus({ preventScroll: true });
  }, [paletteOpen]);

  function follow(event: MouseEvent<HTMLAnchorElement>, href: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); restoreMobileMenuFocus.current = false; setNavigationOpen(false); setPaletteOpen(false); onNavigate(href);
  }
  function openOperation(event: FormEvent) {
    event.preventDefault();
    const value = query.trim();
    if (value) onNavigate(`/operations/${encodeURIComponent(value)}`);
  }
  const filteredLinks = useMemo(() => [...PRIMARY_LINKS, ...SECONDARY_LINKS].filter((link) => link.label.toLowerCase().includes(query.trim().toLowerCase())), [query]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="app-navigation" aria-label="Stateback operator"><Navigation currentPath={currentPath} follow={follow} /></aside>
      <Dialog.Root open={navigationOpen} onOpenChange={(open) => {
        setNavigationOpen(open);
        if (!open && restoreMobileMenuFocus.current) {
          mobileFocusTimer.current = window.setTimeout(() => {
            restoreMobileMenuFocus.current = false;
            mobileMenuTrigger.current?.focus({ preventScroll: true });
          }, 200);
        }
      }}>
        <Dialog.Portal><Dialog.Backdrop className="mobile-navigation__backdrop" /><Dialog.Viewport className="mobile-navigation__viewport"><Dialog.Popup className="mobile-navigation" initialFocus={mobileFirstLink} finalFocus={false}><Dialog.Title className="visually-hidden">Navigation</Dialog.Title><Dialog.Close tabIndex={-1} className="icon-button mobile-navigation__close" aria-label="Close navigation"><X size={18} /></Dialog.Close><Navigation currentPath={currentPath} follow={follow} firstLinkRef={mobileFirstLink} /></Dialog.Popup></Dialog.Viewport></Dialog.Portal>
      </Dialog.Root>
      <header className="app-topbar">
        <button ref={mobileMenuTrigger} type="button" className="icon-button app-navigation__toggle" aria-label="Open navigation" onClick={() => {
          if (mobileFocusTimer.current !== null) window.clearTimeout(mobileFocusTimer.current);
          restoreMobileMenuFocus.current = true;
          setNavigationOpen(true);
        }}><Menu size={19} /></button>
        <span className="app-topbar__title">{pageTitle(currentPath)}</span>
        <div className="app-topbar__actions">
          <button type="button" className="command-trigger" aria-label="Search" onClick={() => setPaletteOpen(true)}><Search size={15} aria-hidden="true" /><span>Search</span><kbd>⌘ K</kbd></button>
          <button className="icon-button" type="button" aria-label="Log out" title="Log out" onClick={onLogout}><LogOut size={16} /></button>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>{children}</main>

      <Dialog.Root open={paletteOpen} onOpenChange={(open) => { setPaletteOpen(open); if (!open) setQuery(""); }}>
        <Dialog.Portal><Dialog.Backdrop className="command-palette__backdrop" /><Dialog.Viewport className="command-palette__viewport"><Dialog.Popup className="command-palette" initialFocus={paletteInput}><Dialog.Title className="visually-hidden">Command palette</Dialog.Title><form className="command-palette__search" onSubmit={openOperation}><Search size={19} aria-hidden="true" /><input ref={paletteInput} value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder="Navigate or open operation by ID…" aria-label="Search commands" /><kbd>ESC</kbd></form><div className="command-palette__results"><p>Navigation</p>{filteredLinks.map(({ href, label, icon: Icon }) => <a key={href} href={href} onClick={(event) => follow(event, href)}><Icon size={17} /><span>{label}</span><small>Open</small></a>)}{query.trim() && <button type="button" onClick={() => onNavigate(`/operations/${encodeURIComponent(query.trim())}`)}><Activity size={17} /><span>Open operation <code>{query.trim()}</code></span><small>↵</small></button>}</div><footer><Command size={14} /> Stateback command palette</footer></Dialog.Popup></Dialog.Viewport></Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
