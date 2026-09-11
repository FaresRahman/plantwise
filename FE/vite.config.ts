import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Shared by both `server` (vite dev, port 5173) and `preview` (vite preview,
// port 4173 — what `npm run prod` serves) so tunnelling through ngrok works
// the same way regardless of which one is running.
const ngrokFriendlyServerOptions = {
  // ngrok's free tier assigns a random *.ngrok-free.dev host each run —
  // Vite's host-header allowlist (added to block DNS rebinding) would
  // otherwise reject it with "Blocked request. This host is not allowed."
  allowedHosts: true as const,
  // Proxies API calls to the local backend so the browser only ever talks
  // to one origin (this server) — needed for tunnelling the app through
  // ngrok's single free endpoint without a second tunnel/CORS.
  proxy: {
    "/api": {
      target: "http://localhost:8010",
      changeOrigin: true,
    },
  },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, ...ngrokFriendlyServerOptions },
  preview: { port: 4173, ...ngrokFriendlyServerOptions },
});
