import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    /** 减少懒加载 chunk 在 dev 下首次解析失败 / 预构建遗漏导致的动态导入 fetch 失败 */
    optimizeDeps: {
        include: [
            "leaflet",
            "react-leaflet",
            "swiper/react",
            "swiper/modules",
        ],
    },
    server: {
        port: 5173,
        host: "0.0.0.0",
        proxy: {
            "/api": {
                target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
                changeOrigin: true,
            },
            "/sounds": {
                target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
                changeOrigin: true,
            },
        },
    },
})
