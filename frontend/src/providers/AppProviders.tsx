/**
 * AppProviders - 组合所有全局 Provider
 *
 * 统一管理应用级别的 Context Providers，包括:
 * - React Router
 * - TanStack Query
 * - Toast 通知
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ConfigProvider, EmptyState } from "@/components/ui"
import { BrowserRouter } from "react-router-dom"
import { getStagePopupContainer } from "@/providers/StageOverlayContext"
import { useAppStore } from "@/store/useAppStore"
import { createEcoSignalAntdTheme } from "@/styles/antdTheme"

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 5 * 60 * 1000, // 5 分钟
            gcTime: 10 * 60 * 1000, // 10 分钟 (原 cacheTime)
            retry: 1,
            refetchOnWindowFocus: false,
        },
        mutations: {
            retry: 0,
        },
    },
})

interface AppProvidersProps {
    children: React.ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
    const effectiveTheme = useAppStore((state) => state.effectiveTheme)

    return (
        <QueryClientProvider client={queryClient}>
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
