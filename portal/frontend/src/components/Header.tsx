import { Link, NavLink } from "react-router-dom";
import { Badge } from "../ui";
import { useSession } from "../session";

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? "is-active" : undefined;

// Padlock glyph — marks the two pages that are not read-only.
const LOCK = (
  <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="4" y="10.5" width="16" height="10.5" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
    <path d="M8 10.5 V7 a4 4 0 0 1 8 0 V10.5" fill="none" stroke="currentColor" strokeWidth="2" />
  </svg>
);

export function Header() {
  const { state, signOut } = useSession();
  const signedIn = state?.signed_in === true;
  // With auth off everyone is 'signed in' and there is nothing to sign out
  // of, so the corner stays empty rather than offering a no-op.
  const asks = state?.required !== false;

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
        {/* The two pages that are not read-only appear once there is a session.
            A visitor to a public lab has no use for a tab that can only ask for
            a password; the way in is the sign-in button beside this nav, and
            both routes still answer directly with the same guard. */}
        {signedIn && (
          <>
            <NavLink to="/ask" className={navClass} title="Ask an analyst">
              Ask
            </NavLink>
            <NavLink to="/settings" className={navClass} title="Control the simulator">
              Settings
            </NavLink>
          </>
        )}
      </nav>
      {signedIn && !asks ? null : signedIn ? (
        <button
          type="button"
          className="portal-login"
          onClick={() => void signOut()}
          title="Sign out"
        >
          {LOCK}
          <span className="portal-login__text">Sign out</span>
        </button>
      ) : (
        // A link to a guarded page rather than a second password form in the
        // corner: the form lives once, in the guard, and this is the way to it.
        <Link className="portal-login" to="/settings" title="Sign in to control the simulator">
          {LOCK}
          <span className="portal-login__text">Sign in</span>
        </Link>
      )}
    </header>
  );
}
