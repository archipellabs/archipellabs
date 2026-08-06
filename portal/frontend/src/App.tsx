import { Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { Analytics } from "./routes/Analytics";
import { Ask } from "./routes/Ask";
import { Cartography } from "./routes/Cartography";
import { Settings } from "./routes/Settings";
import { SessionProvider } from "./components/SessionProvider";

export function App() {
  return (
    // The provider wraps the header as well as the routes: the header's sign-in
    // button and the guarded pages read one session, so signing out in the
    // corner cannot leave a page still believing it has one.
    <SessionProvider>
      <div className="portal-shell">
        <Header />
        <main className="portal-main">
          <Routes>
            <Route path="/" element={<Cartography />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/ask" element={<Ask />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </SessionProvider>
  );
}
