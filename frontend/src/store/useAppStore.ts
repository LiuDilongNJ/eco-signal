import { create } from "zustand"
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware"
import { message } from "@/components/ui"
import { userPreferenceApi } from "@/api/endpoints/users"
import { isFunctionalCookiesAllowed } from "@/features/home/cookieConsent"
import { authUtils } from "@/utils/auth"

export type Theme = "light" | "dark" | "auto"
export type EffectiveTheme = "light" | "dark"

export const normalizeTheme = (value: unknown): Theme =>
    value === "light" || value === "dark" || value === "auto" ? value : "auto"

interface AppState {
    /** 主题模式 */
    theme: Theme
    /** 当前实际生效的主题（auto 会解析为 light/dark） */
    effectiveTheme: EffectiveTheme
    /** 最后一次从账号加载或成功保存的主题 */
    persistedTheme: Theme
    /** 侧边栏是否折叠 */
    sidebarCollapsed: boolean
    /** 是否正在切换主题（显示全局遮罩） */
    isThemeTransitioning: boolean

    // ---- Actions ----
    setTheme: (theme: Theme) => void
    applyAccountTheme: (theme: Theme) => void
    setThemePreference: (theme: Theme) => Promise<boolean>
    syncEffectiveTheme: () => void
    toggleTheme: () => void
    toggleSidebar: () => void
    setSidebarCollapsed: (collapsed: boolean) => void
}

const getSystemTheme = (): EffectiveTheme => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "light"
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

const resolveTheme = (theme: Theme): EffectiveTheme => (theme === "auto" ? getSystemTheme() : theme)

/** 辅助函数：将主题应用到 DOM 根节点 */
const applyThemeToDOM = (theme: Theme): EffectiveTheme => {
    const effectiveTheme = resolveTheme(theme)
    if (typeof document === "undefined") return effectiveTheme

    const root = document.documentElement
    root.classList.remove("light", "dark")
    root.classList.add(effectiveTheme)
    root.setAttribute("data-theme", effectiveTheme)
    return effectiveTheme
}

const functionalPreferenceStorage: StateStorage = {
    getItem: (name) => {
        if (typeof window === "undefined") return null
        if (!isFunctionalCookiesAllowed()) return null
        return window.localStorage.getItem(name)
    },
    setItem: (name, value) => {
        if (typeof window === "undefined") return
        if (!isFunctionalCookiesAllowed()) return
        window.localStorage.setItem(name, value)
    },
    removeItem: (name) => {
        if (typeof window === "undefined") return
        window.localStorage.removeItem(name)
    },
}

let themeSaveQueue: Promise<void> = Promise.resolve()
let themeSaveGeneration = 0

export const useAppStore = create<AppState>()(
    persist(
        (set, get) => ({
            theme: "auto",
            effectiveTheme: getSystemTheme(),
            persistedTheme: "auto",
            sidebarCollapsed: false,
            isThemeTransitioning: false,

            setTheme: (theme) => {
                const effectiveTheme = applyThemeToDOM(theme)
                set({ theme, effectiveTheme })
            },

            applyAccountTheme: (theme) => {
                const effectiveTheme = applyThemeToDOM(theme)
                set({ theme, effectiveTheme, persistedTheme: theme })
            },

            setThemePreference: async (theme) => {
                const token = authUtils.getToken()
                const generation = ++themeSaveGeneration
                get().setTheme(theme)
                if (!token) return true

                let saved = false
                const saveOperation = themeSaveQueue.then(async () => {
                    if (authUtils.getToken() !== token) return
                    await userPreferenceApi.patch({ theme })
                    saved = true
                })
                themeSaveQueue = saveOperation.catch(() => undefined)

                try {
                    await saveOperation
                    if (saved && authUtils.getToken() === token) {
                        set({ persistedTheme: theme })
                    }
                    return saved
                } catch (error) {
                    if (generation === themeSaveGeneration && authUtils.getToken() === token) {
                        get().setTheme(get().persistedTheme)
                        message.error(error instanceof Error ? error.message : "Failed to save theme")
                    }
                    return false
                }
            },

            syncEffectiveTheme: () => {
                const theme = get().theme
                const effectiveTheme = applyThemeToDOM(theme)
                set({ effectiveTheme })
            },

            toggleTheme: async () => {
                if (get().isThemeTransitioning) return
                const current = get().theme
                let next: Theme
                if (current === "auto") {
                    next = get().effectiveTheme === "dark" ? "light" : "dark"
                } else {
                    next = current === "light" ? "dark" : "light"
                }

                // 1. 立即开启全局过渡状态
                set({ isThemeTransitioning: true })

                // 2. 延迟 150ms 再真正修改 DOM 主题，确保遮罩已盖住
                await new Promise((resolve) => window.setTimeout(resolve, 150))
                await get().setThemePreference(next)

                // 3. 再等一会儿关闭遮罩
                window.setTimeout(() => {
                    set({ isThemeTransitioning: false })
                }, 200)
            },

            toggleSidebar: () =>
                set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

            setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
        }),
        {
            name: "eco-app-store", // 统一 localStorage 键名
            storage: createJSONStorage(() => functionalPreferenceStorage),
            onRehydrateStorage: () => (state) => {
                if (state) {
                    const theme = normalizeTheme(state.theme)
                    state.theme = theme
                    // 页面加载或存储恢复时立即应用主题
                    state.syncEffectiveTheme()
                }
            },
            partialize: (state) => ({
                theme: state.theme,
                sidebarCollapsed: state.sidebarCollapsed,
            }),
        }
    )
)

/** 方便组件获取当前实际生效的模式（处理 auto 情况） */
export const getEffectiveTheme = resolveTheme
