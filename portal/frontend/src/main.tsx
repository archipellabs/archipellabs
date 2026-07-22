import "./ui/ui.css";
import "./global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Root } from "./ui";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root theme="light">
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </Root>
  </StrictMode>,
);
