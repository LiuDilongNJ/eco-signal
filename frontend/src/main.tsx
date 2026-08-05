import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "./styles/tokens.css"
import "./index.css"
import "./styles/components.css"
import "./scrollbar-brand.css"
import App from "./App"
import { bootstrapSessionFromRefreshCookie } from "./api/client"

// 静默恢复会话：localStorage 无 token 但 refresh cookie 有效时自动重新登录
void bootstrapSessionFromRefreshCookie()

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <App />
    </StrictMode>
)
