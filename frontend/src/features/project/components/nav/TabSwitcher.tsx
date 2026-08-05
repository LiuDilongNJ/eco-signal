import { Button as ESButton, Label } from "@/components/ui"
/**
 * TabSwitcher - 滑动药丸标签切换器
 */

import { useRef, useEffect, useCallback, useState, useMemo } from "react"
import { TAB_ITEMS } from "../../data/constants"
import { useTabStore } from "../../stores/useTabStore"
import { useProjectStore } from "../../stores/useProjectStore"
import { authUtils } from "@/utils/auth"
import { LoginModal } from "@/components/ui"
import { StableText } from "@/components/ui"
import type { TabName } from "../../types"

/** 需要登录才能访问的 tab */
const AUTH_REQUIRED_TABS: TabName[] = ["data"]

export function TabSwitcher() {
    const { activeTab, setActiveTab } = useTabStore()
    const { currentProjectId, currentCollectionId } = useProjectStore()
    const pillRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const compactRef = useRef<HTMLDivElement>(null)

    const [showLoginModal, setShowLoginModal] = useState(false)
    const [compactMode] = useState(false)
    const [compactOpen, setCompactOpen] = useState(false)
    /** 登录成功后要切换到的 tab */
    const pendingTabRef = useRef<TabName | null>(null)

    const visibleTabs = useMemo(() => {
        const tabs = TAB_ITEMS

        // If the active tab is hidden, switch to the first available tab
        if (!tabs.find((t) => t.key === activeTab)) {
            setActiveTab(tabs[0]?.key as TabName || "desc")
        }

        return tabs
    }, [activeTab, setActiveTab])

    const movePill = useCallback((el: HTMLElement) => {
        if (!pillRef.current || !containerRef.current) return
        // Use layout coordinates to avoid transform(scale) sub-pixel drift.
        pillRef.current.style.left = `${el.offsetLeft}px`
        pillRef.current.style.width = `${el.offsetWidth}px`
    }, [])

    const syncActivePill = useCallback((disableTransition = false) => {
        const activeEl = containerRef.current?.querySelector(".nav-item.active") as HTMLElement | null
        if (!activeEl) return
        if (disableTransition && pillRef.current) pillRef.current.style.transition = "none"
        movePill(activeEl)
        if (disableTransition) {
            requestAnimationFrame(() => {
                if (pillRef.current) pillRef.current.style.transition = ""
            })
        }
    }, [movePill])

    /** 首次渲染、标签切换、以及项目/集合切换导致布局变化时，同步药丸位置 */
    useEffect(() => {
        syncActivePill(true)
        // 连续两帧校准，应对 Flex 布局调整导致的瞬时位置误差
        requestAnimationFrame(() => syncActivePill(true))
        const timer = setTimeout(() => syncActivePill(true), 100) // 兜底：处理可能的长时间渲染
        return () => clearTimeout(timer)
    }, [activeTab, visibleTabs, currentProjectId, currentCollectionId, syncActivePill])

    useEffect(() => {
        const handleResize = () => {
            syncActivePill()
        }
        window.addEventListener("resize", handleResize)
        return () => window.removeEventListener("resize", handleResize)
    }, [syncActivePill])

    useEffect(() => {
        const container = containerRef.current
        if (!container) return

        let frame = 0
        const scheduleSync = () => {
            cancelAnimationFrame(frame)
            frame = requestAnimationFrame(() => syncActivePill(true))
        }

        const resizeObserver = new ResizeObserver(scheduleSync)
        resizeObserver.observe(container)
        container.querySelectorAll(".nav-item").forEach((el) => resizeObserver.observe(el))

        const mutationObserver = new MutationObserver(scheduleSync)
        mutationObserver.observe(container, {
            subtree: true,
            childList: true,
            characterData: true,
        })

        document.fonts?.ready.then(scheduleSync).catch(() => {})
        scheduleSync()

        return () => {
            cancelAnimationFrame(frame)
            resizeObserver.disconnect()
            mutationObserver.disconnect()
        }
    }, [activeTab, visibleTabs, syncActivePill])

    const handleTabClick = (tab: TabName, e: React.MouseEvent<HTMLButtonElement>) => {
        // 需要登录的 tab：未登录时弹出登录框，阻止切换
        if (AUTH_REQUIRED_TABS.includes(tab) && !authUtils.getToken()) {
            pendingTabRef.current = tab
            setShowLoginModal(true)
            return
        }
        setActiveTab(tab)
        movePill(e.currentTarget)
    }

    const handleLoginSuccess = () => {
        setShowLoginModal(false)
        const pending = pendingTabRef.current
        pendingTabRef.current = null
        if (pending) {
            setActiveTab(pending)
            // 稍延迟等 DOM 更新后再移动药丸
            requestAnimationFrame(() => {
                const btn = containerRef.current?.querySelector(
                    `.nav-item[data-key="${pending}"]`
                ) as HTMLElement | null
                if (btn) movePill(btn)
            })
        }
    }

    useEffect(() => {
        if (!compactMode || !compactOpen) return
        const onDocPointerDown = (ev: PointerEvent) => {
            const target = ev.target as Node | null
            if (!target) return
            if (compactRef.current?.contains(target)) return
            setCompactOpen(false)
        }
        document.addEventListener("pointerdown", onDocPointerDown)
        return () => document.removeEventListener("pointerdown", onDocPointerDown)
    }, [compactMode, compactOpen])

    const handleCompactSelect = (nextTab: TabName) => {
        if (AUTH_REQUIRED_TABS.includes(nextTab) && !authUtils.getToken()) {
            pendingTabRef.current = nextTab
            setShowLoginModal(true)
            setCompactOpen(false)
            return
        }
        setActiveTab(nextTab)
        setCompactOpen(false)
    }

    return (
        <div className="nav-center">
            {compactMode ? (
                <div className="nav-capsule-box nav-capsule-box--compact" ref={compactRef}>
                    <Label className="nav-center-compact-label" htmlFor="project-tab-select">Tab</Label>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="nav-center-compact-select"
                        onClick={() => setCompactOpen((v) => !v)}
                    >
                        <StableText className="nav-center-compact-select-label">
                            {visibleTabs.find((t) => t.key === activeTab)?.label ?? "Tab"}
                        </StableText>
                    </ESButton>
                    <div className={`nav-center-compact-dropdown ${compactOpen ? "open" : ""}`}>
                        {visibleTabs.map((item) => (
                            <ESButton appearance="unstyled"
                                key={item.key}
                                type="button"
                                className={`nav-center-compact-option ${activeTab === item.key ? "active" : ""}`}
                                onClick={() => handleCompactSelect(item.key as TabName)}
                            >
                                <StableText className="nav-center-compact-option-label">{item.label}</StableText>
                            </ESButton>
                        ))}
                    </div>
                </div>
            ) : (
                <div className="nav-capsule-box" ref={containerRef}>
                    <div className="sliding-pill" ref={pillRef} />
                    {visibleTabs.map((item) => (
                        <ESButton appearance="unstyled"
                            key={item.key}
                            data-key={item.key}
                            className={`nav-item ${activeTab === item.key ? "active" : ""}`}
                            onClick={(e) => handleTabClick(item.key as TabName, e)}
                        >
                            <StableText className="nav-item-label">{item.label}</StableText>
                        </ESButton>
                    ))}
                </div>
            )}

            <LoginModal
                isOpen={showLoginModal}
                onClose={() => {
                    setShowLoginModal(false)
                    pendingTabRef.current = null
                }}
                onSuccess={handleLoginSuccess}
            />
        </div>
    )
}
