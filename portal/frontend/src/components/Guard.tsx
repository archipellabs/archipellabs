import { useState, type FormEvent, type ReactNode } from "react";
import { Text } from "../ui";
import { useSession } from "../session";
import "./guard.css";

/** Wraps the two pages that are not read-only.
 *
 *  It renders one of four things, and the fourth is the reason this is a
 *  component rather than a redirect: a portal with no password configured has
 *  not locked *this visitor* out, it has closed the page to everyone, and the
 *  person who needs to know is whoever deployed it. Sending them to a sign-in
 *  form would be asking for a password that does not exist.
 */
export function Guard({ title, children }: { title: string; children: ReactNode }) {
  const { state, signIn } = useSession();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Not asked yet. Rendering the form here would flash it on every reload for
  // somebody who is in fact signed in.
  if (state === null) return null;

  if (state.signed_in) return <>{children}</>;

  if (!state.configured) {
    return (
      <section className="guard">
        <Text variant="h2">{title} is closed</Text>
        <Text color="muted">
          This portal has no password configured, so the pages that are not read-only are
          shut for everyone. Set <code>PORTAL_PASSWORD</code> in the backend’s environment
          and restart it.
        </Text>
      </section>
    );
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(password);
      setPassword("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="guard">
      <Text variant="h2">Sign in</Text>
      <Text color="muted">
        {title} can spend money and change how the simulated company behaves, so it asks
        for the operator’s password.
      </Text>
      <form className="guard-form" onSubmit={submit}>
        <input
          type="password"
          className="guard-input"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Password"
          aria-label="Operator password"
          autoFocus
        />
        <button type="submit" className="guard-submit" disabled={busy || !password}>
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
      {error && (
        <Text color="danger" variant="small">
          {error}
        </Text>
      )}
    </section>
  );
}
