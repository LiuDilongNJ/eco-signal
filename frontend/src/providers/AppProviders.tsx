/**
 * AppProviders - 组合所有全局 Provider
 *
 * 统一管理应用级别的 Context Providers，包括:
 * - React Router
 * - TanStack Query
 * - Toast 通知
 */

import { QueryClientProvider } from "@tanstack/react-query"
import { ConfigProvider, EmptyState } from "@/components/ui"
import { BrowserRouter } from "react-router-dom"
import { getStagePopupContainer } from "@/providers/StageOverlayContext"
import { useAppStore } from "@/store/useAppStore"
import { createEcoSignalAntdTheme } from "@/styles/antdTheme"
import { appQueryClient } from "./queryClient"

interface AppProvidersProps {
    children: React.ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
    const effectiveTheme = useAppStore((state) => state.effectiveTheme)

    return (
        <QueryClientProvider client={appQueryClient}>
            <ConfigProvider
                theme={createEcoSignalAntdTheme(effectiveTheme === "dark")}
                renderEmpty={() => <EmptyState className="antd-no-data-empty" title="No Data" />}
                getPopupContainer={getStagePopupContainer}
            >
                <BrowserRouter>
                    {children}
                </BrowserRouter>
            </ConfigProvider>
            {/* <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" /> */}
        </QueryClientProvider>
    )
}
