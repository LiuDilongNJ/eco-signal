/**
 * Header - 顶部导航栏
 */

import { useAppStore } from "@/store/useAppStore"
import { Moon, Sun, Monitor } from "lucide-react"
import { IconButton } from "@/components/ui"

export function Header() {
    const { theme, setThemePreference } = useAppStore()

    const themeOptions = [
        { value: "light" as const, icon: <Sun size={16} />, label: "Light" },
        { value: "dark" as const, icon: <Moon size={16} />, label: "Dark" },
        { value: "auto" as const, icon: <Monitor size={16} />, label: "Auto" },
    ]

    return (
        <header className="flex h-16 items-center justify-between border-b border-border bg-card px-6">
            {/* 左侧：面包屑或标题 */}
            <div>
                <h2 className="text-lg font-semibold text-foreground">
                    EcoSignal Management Platform
                </h2>
            </div>

            {/* 右侧：工具栏 */}
            <div className="flex items-center gap-2">
                {/* 主题切换 */}
                <div className="flex items-center rounded-lg border border-border bg-muted p-1">
                    {themeOptions.map((opt) => (
                        <IconButton
                            key={opt.value}
                            onClick={() => void setThemePreference(opt.value)}
                            label={opt.label}
                            icon={opt.icon}
                            pressed={theme === opt.value}
                            className={`flex h-7 w-7 items-center justify-center rounded-md text-sm transition-colors ${theme === opt.value
                                    ? "bg-background text-foreground shadow-sm"
                                    : "text-muted-foreground hover:text-foreground"
                                }`}
                        />
                    ))}
                </div>

                {/* 用户头像占位 */}
                <div className="ml-3 flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                    U
                </div>
            </div>
        </header>
    )
}
