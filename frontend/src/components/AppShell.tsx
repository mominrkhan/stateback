import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

interface AppShellProps {
  children: ReactNode;
  currentPath: string;
  onNavigate: (href: string) => void;
  onLogout: () => void;
}

const LINKS = [
  { href: "/operations", label: "Operations" },
  { href: "/approvals", label: "Approvals" },
  { href: "/recovery", label: "Recovery" },
] as const;

export function AppShell({ children, currentPath, onNavigate, onLogout }: AppShellProps) {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const navigation = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!navigationOpen) return;
    const links = Array.from(navigation.current?.querySelectorAll<HTMLAnchorElement>("nav a") ?? []);
    (links.find((link) => link.getAttribute("aria-current") === "page") ?? links[0])?.focus();

    function handleNavigationKeys(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setNavigationOpen(false);
        menuButton.current?.focus();
        return;
      }
      if (event.key !== "Tab" || links.length === 0) return;
      const first = links[0];
      const last = links.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", handleNavigationKeys);
    return () => window.removeEventListener("keydown", handleNavigationKeys);
  }, [navigationOpen]);

  useEffect(() => setNavigationOpen(false), [currentPath]);

  function follow(event: MouseEvent<HTMLAnchorElement>, href: string) {
    if (
      event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
    ) return;
    event.preventDefault();
    setNavigationOpen(false);
    onNavigate(href);
  }

  return (
    <div className={`app-shell${navigationOpen ? " app-shell--nav-open" : ""}`}>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside ref={navigation} id="operator-navigation" className="app-navigation" aria-label="Stateback operator">
        <p className="app-navigation__brand" aria-label="Stateback">STATEBACK</p>
        <nav aria-label="Operator navigation">
          {LINKS.map(({ href, label }) => (
            <a
              key={href}
              href={href}
              aria-current={currentPath === href || currentPath.startsWith(`${href}/`) ? "page" : undefined}
              onClick={(event) => follow(event, href)}
            >
              {label}
            </a>
          ))}
        </nav>
      </aside>
      <button
        type="button"
        className="app-navigation__backdrop"
        aria-label="Close navigation"
        tabIndex={navigationOpen ? 0 : -1}
        onClick={() => setNavigationOpen(false)}
      />
      <header className="app-topbar">
        <button
          ref={menuButton}
          type="button"
          className="app-navigation__toggle"
          aria-controls="operator-navigation"
          aria-expanded={navigationOpen}
          onClick={() => setNavigationOpen((open) => !open)}
        >
          Menu
        </button>
        <span className="app-topbar__title">Operator console</span>
        <button className="primitive-button" type="button" onClick={onLogout}>Log out</button>
      </header>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}
