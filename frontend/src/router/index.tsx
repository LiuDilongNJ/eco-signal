/**
 * 路由配置
 *
 * 使用 React Router v6 的声明式路由配置。
 * 顶栏页面使用静态导入，避免部分环境下 `lazy(() => import(...))` 出现
 * “Failed to fetch dynamically imported module”（HMR/代理/缓存导致 chunk 拉取失败）。
 */

import { useEffect, useState, type ReactNode } from "react"
import { Navigate, Routes, Route } from "react-router-dom"
import ProjectPage from "@/features/project/pages/ProjectPage"
import HomePage from "@/features/home/pages/HomePage"
import PrivacyPolicyPage from "@/features/home/pages/PrivacyPolicyPage"
import SettingsPage from "@/features/settings/pages/SettingsPage"
import NotFoundPage from "@/features/errors/pages/NotFoundPage"
import { AUTH_LANDING_PATH, authUtils } from "@/utils/auth"

function RequireAuth({ children }: { children: ReactNode }) {
    const [hasToken, setHasToken] = useState(() => authUtils.hasToken())

    useEffect(() => {
        const syncAuth = () => setHasToken(authUtils.hasToken())
        window.addEventListener("eco-auth-change", syncAuth)
        window.addEventListener("storage", syncAuth)
        return () => {
            window.removeEventListener("eco-auth-change", syncAuth)
            window.removeEventListener("storage", syncAuth)
        }
    }, [])

    if (!hasToken) {
        return <Navigate to={AUTH_LANDING_PATH} replace />
    }

    return <>{children}</>
}

export function AppRouter() {
    return (
        <Routes>
            {/* 项目页面（独立布局，不使用 AppLayout）；更具体的路径在前 */}
            <Route path="/dashboard/:id/media/:mediaId" element={<ProjectPage />} />
            <Route path="/dashboard/:id" element={<ProjectPage />} />
            <Route path="/dashboard" element={<ProjectPage />} />

            {/* 主页：/ 与 /index 均可 */}
            <Route path="/" element={<HomePage />} />
            <Route path="/index" element={<HomePage />} />
            <Route path="/privacy-policy" element={<PrivacyPolicyPage />} />

            {/* 设置页 */}
            <Route
                path="/settings"
                element={
                    <RequireAuth>
                        <SettingsPage />
                    </RequireAuth>
                }
            />

            {/* 404 */}
            <Route path="*" element={<NotFoundPage />} />
        </Routes>
    )
}
