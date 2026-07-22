import { Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { Analytics } from "./routes/Analytics";
import { Cartography } from "./routes/Cartography";

export function App() {
  return (
    <div className="portal-shell">
      <Header />
      <main className="portal-main">
        <Routes>
          <Route path="/" element={<Cartography />} />
          <Route path="/analytics" element={<Analytics />} />
        </Routes>
      </main>
    </div>
  );
}
