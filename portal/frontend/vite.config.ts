import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The portal is served at the root — the gateway gives it its own port (a subdomain
// in production), so there's no base path. The dev server proxies /api to FastAPI.
export default defineConfig({
  plugins: [react()],
  resolve: { dedupe: ["react", "react-dom"] },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
