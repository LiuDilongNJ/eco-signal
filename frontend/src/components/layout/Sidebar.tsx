/**
 * Sidebar - 侧边栏导航
 */

import { NavLink } from "react-router-dom"
import { useAppStore } from "@/store/useAppStore"
import { cn } from "@/lib/utils"
import { LayoutDashboard, Users, Settings, ChevronLeft, ChevronRight } from "lucide-react"
import { IconButton } from "@/components/ui"

interface NavItem {
    label: string
    path: string
    icon: React.ReactNode
}

const navItems: NavItem[] = [
    { label: "Dashboard", path: "/dashboard", icon: <LayoutDashboard size={20} /> },
    { label: "Examples", path: "/example", icon: <Users size={20} /> },
    { label: "Settings", path: "/settings", icon: <Settings size={20} /> },
]

export function Sidebar() {
    const { sidebarCollapsed, toggleSidebar } = useAppStore()

    return (
        <aside
            className={cn(
                "fixed left-0 top-0 z-40 flex h-full flex-col border-r border-sidebar-border bg-sidebar-background transition-all duration-300",
                sidebarCollapsed ? "w-16" : "w-64"
            )}
        >
            {/* Logo 区域 */}
            <div className="flex h-16 items-center justify-between border-b border-sidebar-border px-4">
                {!sidebarCollapsed && (
                    <span className="text-lg font-bold text-sidebar-foreground">
                        EcoSignal
                    </span>
                )}
                <IconButton
                    onClick={toggleSidebar}
                    label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                    icon={sidebarCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
                    className="flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground hover:bg-sidebar-accent"
                />
            </div>

            {/* 导航菜单 */}
            <nav className="flex-1 space-y-1 px-2 py-4">
                {navItems.map((item) => (
                    <NavLink
                        key={item.path}
                        to={item.path}
                        className={({ isActive }) =>
                            cn(
                                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                                isActive
                                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                            )
                        }
                    >
                        <span className="shrink-0">{item.icon}</span>
                        {!sidebarCollapsed && <span>{item.label}</span>}
                    </NavLink>
                ))}
            </nav>

            {/* 底部 */}
            {!sidebarCollapsed && (
                <div className="border-t border-sidebar-border p-4">
                    <p className="text-xs text-sidebar-foreground/50">v0.1.0</p>
                </div>
            )}
        </aside>
    )
}
