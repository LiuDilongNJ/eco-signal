/**
 * AppLayout - 企业应用主布局
 *
 * 结构: 侧边栏 + 顶部导航 + 内容区
 */

import { Outlet } from "react-router-dom"
import { Sidebar } from "./Sidebar"
import { Header } from "./Header"
import { useAppStore } from "@/store/useAppStore"
import { cn } from "@/lib/utils"
import { CustomScrollArea } from "@/components/ui"

export function AppLayout() {
    const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed)

    return (
        <div className="flex h-screen overflow-hidden bg-background">
            {/* 侧边栏 */}
            <Sidebar />

            {/* 主内容区 */}
            <div
                className={cn(
                    "flex flex-1 flex-col transition-all duration-300",
                    sidebarCollapsed ? "ml-16" : "ml-64"
                )}
            >
                {/* 顶部导航 */}
                <Header />

                {/* 页面内容 */}
                <main className="flex min-h-0 flex-1 flex-col">
                    <CustomScrollArea variant="fill" className="min-h-0 flex-1" bodyClassName="p-6">
                        <Outlet />
                    </CustomScrollArea>
                </main>
            </div>
        </div>
    )
}
