import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// base "/" because the routes are real URLs: with relative asset paths, a page
// at /contacts/someone@example.com would look for its JS under /contacts/.
// The Python server falls back to index.html for unknown paths, which is what
// makes a refresh on a deep route work.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/",
  server: {
    proxy: { "/api": "http://127.0.0.1:8787" },
  },
});
