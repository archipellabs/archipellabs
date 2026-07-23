import { Link, NavLink } from "react-router-dom";
import { Badge } from "../ui";

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? "is-active" : undefined;

// Padlock glyph — the sign-in is gated to a future admin console.
const LOCK = (
  <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="4" y="10.5" width="16" height="10.5" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
    <path d="M8 10.5 V7 a4 4 0 0 1 8 0 V10.5" fill="none" stroke="currentColor" strokeWidth="2" />
  </svg>
);

export function Header() {
  return (
    <header className="portal-header">
      <Link to="/" className="portal-brand">
        <img
          src="/archipellabs-logo.png"
          width={24}
          height={24}
          alt=""
        />
        <span className="portal-brand__name">Archipel Labs</span>
        <Badge appearance="solid" tone="success" size="sm">
          SIMULATOR
        </Badge>
      </Link>
      <nav className="portal-nav">
        <NavLink to="/" end className={navClass}>
          The chart
        </NavLink>
        <NavLink to="/analytics" className={navClass}>
          Analytics
        </NavLink>
      </nav>
      {/* Admin sign-in — disabled until the control console (trigger simulator
          actions, admin-only) ships. Kept visible so the gate is discoverable. */}
      <button
        type="button"
        className="portal-login"
        disabled
        title="Admin sign-in — coming soon (control the simulator)"
      >
        {LOCK}
        <span className="portal-login__text">Sign in</span>
      </button>
    </header>
  );
}
