import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig(({ command }) => ({
  // CC-01: build 时资产引用重写为 /static/dist/（匹配 app.py 静态路由），dev 保持根路径
  base: command === "build" ? "/static/dist/" : "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "../quantflow/web/static/dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules")) {
            if (/[\\/]node_modules[\\/](recharts|d3-|victory-vendor)[\\/]/.test(id)) {
              return "vendor-recharts";
            }
            if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) {
              return "vendor-react";
            }
            if (/[\\/]node_modules[\\/](@radix-ui|lucide-react|class-variance-authority)[\\/]/.test(id)) {
              return "vendor-ui";
            }
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8088",
        changeOrigin: true,
      },
    },
  },
}));
