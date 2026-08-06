import { createContext, useContext } from "react";
import type { SessionState } from "./api";

/** Who is signed in, shared by the header, the settings page and the ask page.
 *
 *  One source rather than three: the header decides what the button says, and
 *  the two guarded pages decide whether to render at all. Three independent
 *  fetches would drift — signing out in the header while a page still believed
 *  it had a session showed a form that could only fail.
 *
 *  `state === null` means *not asked yet*, which is deliberately distinct from
 *  signed-out. A page that treats "unknown" as "signed out" flashes its sign-in
 *  form for one frame on every reload, which reads as being logged out.
 *
 *  The context and its hook live here, apart from the provider that fills them,
 *  because a module that exports both a component and a plain function loses
 *  fast refresh for the whole file.
 */
export interface Session {
  state: SessionState | null;
  signIn: (password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Re-ask the server. For a page that got a 401 from a request it thought was
   *  authorised — the cookie expired mid-visit, and the header should catch up. */
  refresh: () => void;
}

export const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (session === null) throw new Error("useSession outside a SessionProvider");
  return session;
}
