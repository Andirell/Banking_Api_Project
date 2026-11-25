import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Set DJANGO_SERVER if Django is running on a different port.
const djangoServer = process.env.DJANGO_SERVER || "http://127.0.0.1:8000";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // Django serves the built files from /static/app/ (see STATICFILES_DIRS).
  base: command === "build" ? "/static/app/" : "/",
  server: {
    // Keeps the app and the API on one origin in development too, like production.
    proxy: {
      "/users": djangoServer,
      "/wallets": djangoServer,
      "/transactions": djangoServer,
      "/loans": djangoServer,
    },
  },
}));
