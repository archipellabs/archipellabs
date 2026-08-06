import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { getSession, login as postLogin, logout as postLogout, type SessionState } from "../api";
import { SessionContext, type Session } from "../session";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState | null>(null);

  const refresh = useCallback(() => {
    getSession()
      .then(setState)
      // A portal whose own session endpoint is unreachable is not a signed-in
      // one; saying so lets the guarded pages explain themselves rather than
      // hang on `null` forever.
      .catch(() => setState({ signed_in: false, configured: false }));
  }, []);

  useEffect(refresh, [refresh]);

  const value = useMemo<Session>(
    () => ({
      state,
      refresh,
      signIn: async (password: string) => setState(await postLogin(password)),
      signOut: async () => setState(await postLogout()),
    }),
    [state, refresh],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
