import { Button as ESButton } from "@/components/ui"
/**
 * DataTab - 数据管理页
 *
 * 包含: 左侧 TableNav（实体表导航）+ 右侧由独立页面组件渲染
 * 每个左侧菜单项对应独立的页面组件，可单独编辑。
 */

import { useState, useLayoutEffect, useRef, useEffect, useDeferredValue } from "react"
import { useSearchParams } from "react-router-dom"
import {
    FolderKanban,
    Library,
    Users,
    MapPin,
    ScanLine,
    Database,
    ClipboardCheck,
    ListChecks,
    Activity,
    ScrollText,
    Mic,
    Image,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useProjectStore } from "../../stores/useProjectStore"
import { usersApi } from "@/api/endpoints/users"
import { getApiData } from "@/api/utils"

// ---- 各数据页面组件 ----
import { ProjectsPage } from "../data/pages/ProjectsPage"
import { CollectionsPage } from "../data/pages/CollectionsPage"
import { UsersPage } from "../data/pages/UsersPage"
import { AudiosPage } from "../data/pages/AudiosPage"
import { PhotosPage } from "../data/pages/PhotosPage"
import { SitesPage } from "../data/pages/SitesPage"
import { AnnotationsPage } from "../data/pages/AnnotationsPage"
import { ReviewsPage } from "../data/pages/ReviewsPage"
import { TasksPage } from "../data/pages/TasksPage"
import { QueuePage } from "../data/pages/QueuePage"
import { IndexLogsPage } from "../data/pages/IndexLogsPage"

// ---- 导航项定义 ----
interface NavItem {
    key: string
    label: string
    icon: LucideIcon
    component: React.ComponentType
}

/** 菜单项图标映射 */
const ICON_MAP: Record<string, LucideIcon> = {
    "project": FolderKanban,
    "collection": Library,
    "user": Users,
    "audio": Mic,
    "photo": Image,
    "site": MapPin,
    "annotation": ScanLine,
    "review": ClipboardCheck,
    "task": ListChecks,
    "queue": Activity,
    "index-log": ScrollText,
}

/** 菜单项组件映射 */
const COMPONENT_MAP: Record<string, React.ComponentType> = {
    "project": ProjectsPage,
    "collection": CollectionsPage,
    "user": UsersPage,
    "audio": AudiosPage,
    "photo": PhotosPage,
    "site": SitesPage,
    "annotation": AnnotationsPage,
    "review": ReviewsPage,
    "task": TasksPage,
    "queue": QueuePage,
    "index-log": IndexLogsPage,
}

/** menu-items 会话级缓存：命中时立即渲染菜单并后台刷新，避免每次进入 Data 区域白屏 */
const menuItemsCache = new Map<string, NavItem[]>()

// ---- DataTab 主组件 ----
export function DataTab() {
    const [searchParams, setSearchParams] = useSearchParams()
    const dataNavFromUrl = searchParams.get("dataNav")
    const project = useProjectStore((s) => {
        if (!s.currentProjectId) return undefined
        return s.projects.find(p => p.id === s.currentProjectId)
    })
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)
    const dataMenuRefreshVersion = useProjectStore((s) => s.dataMenuRefreshVersion)
    const dataTabTargetNavKey = useProjectStore((s) => s.dataTabTargetNavKey)
    const clearDataTabTargetNavKey = useProjectStore((s) => s.clearDataTabTargetNavKey)
    const [navItems, setNavItems] = useState<NavItem[]>([])
    const [activeKey, setActiveKey] = useState<string | null>(null)
    // 重型页面的挂载走延迟渲染，保证点击后左侧高亮能立即绘制而不被挂载阻塞
    const deferredActiveKey = useDeferredValue(activeKey)
    const [menuReady, setMenuReady] = useState(false)
    // keep-alive：本次会话内访问过的 nav 页面保持挂载，切回时零请求零闪烁
    const [visitedKeys, setVisitedKeys] = useState<Set<string>>(new Set())
    const resizeRafRef = useRef<number | null>(null)
    const resizeRafNestedRef = useRef<number | null>(null)
    const didInitRef = useRef(false)

    useEffect(() => {
        const nameToKey: Record<string, string> = {
            "Projects": "project",
            "Collections": "collection",
            "Users": "user",
            "Audios": "audio",
            "Photos": "photo",
            "Sites": "site",
            "Annotations": "annotation",
            "Reviews": "review",
            "Tasks": "task",
            "Queue": "queue",
            "Index Logs": "index-log",
        }

        let cancelled = false
        const fetchMenuItems = async () => {
            const projectIdNum =
                currentProjectId != null && String(currentProjectId).trim() !== ""
                    ? Number(currentProjectId)
                    : NaN
            const project_id = Number.isFinite(projectIdNum) ? projectIdNum : undefined
            const collectionIdNum =
                currentCollectionId != null &&
                String(currentCollectionId).trim() !== "" &&
                String(currentCollectionId).toLowerCase() !== "all"
                    ? Number(currentCollectionId)
                    : NaN
            const collection_id = Number.isFinite(collectionIdNum) ? collectionIdNum : undefined

            // 后端 menu-items 的 project_id 为必填参数；无项目上下文时不发起请求
            if (project_id == null) {
                setNavItems([])
                setMenuReady(true)
                return
            }

            const cacheKey = `${project_id}:${collection_id ?? "all"}`
            const cached = menuItemsCache.get(cacheKey)
            if (cached) {
                // 缓存命中：立即渲染旧菜单后台刷新，不再白屏
                setNavItems(cached)
                setMenuReady(true)
            } else {
                setMenuReady(false)
            }
            try {
                const res = await usersApi.getMenuItems({
                    project_id,
                    ...(collection_id != null ? { collection_id } : {}),
                })
                if (cancelled) return
                const data = getApiData(res)
                if (data && Array.isArray(data)) {
                    const mappedItems = data
                        .filter(item => item.visible)
                        .map(item => {
                            const key = nameToKey[item.name] || item.name.toLowerCase().replace(/\s+/g, "-")
                            const Icon = ICON_MAP[key] || Database
                            const Component = COMPONENT_MAP[key]
                            if (!Component) return null
                            return {
                                key,
                                label: item.name,
                                icon: Icon,
                                component: Component
                            }
                        })
                        .filter((item): item is NavItem => item !== null)

                    menuItemsCache.set(cacheKey, mappedItems)
                    setNavItems(mappedItems)
                } else if (!cached) {
                    setNavItems([])
                }
            } catch (error) {
                console.error("Failed to fetch menu items:", error)
                if (!cancelled && !cached) {
                    setNavItems([])
                }
            } finally {
                if (!cancelled) setMenuReady(true)
            }
        }
        fetchMenuItems()
        return () => {
            cancelled = true
        }
    }, [currentProjectId, currentCollectionId, dataMenuRefreshVersion])

    useEffect(() => {
        if (!menuReady) return

        const visibleKeys = new Set(navItems.map((item) => item.key))
        const urlKey = dataNavFromUrl && visibleKeys.has(dataNavFromUrl) ? dataNavFromUrl : null
        const targetKey =
            dataTabTargetNavKey && visibleKeys.has(dataTabTargetNavKey) ? dataTabTargetNavKey : null
        const nextKey = urlKey ?? targetKey ?? navItems[0]?.key ?? null

        setActiveKey((prev) => (prev === nextKey ? prev : nextKey))

        const next = new URLSearchParams(searchParams)
        const currentParam = next.get("dataNav")
        if (nextKey) {
            if (currentParam !== nextKey) {
                next.set("dataNav", nextKey)
                setSearchParams(next, { replace: true })
            }
        } else if (currentParam !== null) {
            next.delete("dataNav")
            setSearchParams(next, { replace: true })
        }

        if (dataTabTargetNavKey) {
            clearDataTabTargetNavKey()
        }
    }, [
        menuReady,
        navItems,
        dataNavFromUrl,
        dataTabTargetNavKey,
        clearDataTabTargetNavKey,
        searchParams,
        setSearchParams,
    ])

    useLayoutEffect(() => {
        if (!activeKey) return
        const next = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "")
        if (next.get("dataNav") === activeKey) return
        next.set("dataNav", activeKey)
        setSearchParams(next, { replace: true })
    }, [activeKey, setSearchParams])

    // 登记已访问页跟随延迟 key：避免在高亮绘制前的紧急渲染里提前挂载新页
    useEffect(() => {
        if (!deferredActiveKey) return
        setVisitedKeys((prev) => (prev.has(deferredActiveKey) ? prev : new Set(prev).add(deferredActiveKey)))
    }, [deferredActiveKey])

    // 项目/集合切换后卸载非激活页，避免隐藏页批量后台重拉数据或跨项目串数据
    useEffect(() => {
        setVisitedKeys(new Set())
    }, [currentProjectId, currentCollectionId])

    useLayoutEffect(() => {
        if (!didInitRef.current) {
            didInitRef.current = true
            return
        }

        resizeRafRef.current = window.requestAnimationFrame(() => {
            resizeRafNestedRef.current = window.requestAnimationFrame(() => {
                window.dispatchEvent(new Event("resize"))
            })
        })

        return () => {
            if (resizeRafRef.current != null) {
                window.cancelAnimationFrame(resizeRafRef.current)
                resizeRafRef.current = null
            }
            if (resizeRafNestedRef.current != null) {
                window.cancelAnimationFrame(resizeRafNestedRef.current)
                resizeRafNestedRef.current = null
            }
        }
    // resize 跟随延迟 key：新页真正挂载/显示后再触发 antd 表格重新测量
    }, [deferredActiveKey])

    if (!project) return null
    if (!menuReady) return <div className="data-layout" />
    if (navItems.length === 0 || !activeKey) return <div className="data-layout" />

    // activeKey 不在可见菜单内时回退到第一项，保证右侧始终有页面渲染
    const effectiveKey = navItems.some((item) => item.key === activeKey) ? activeKey : navItems[0]?.key ?? activeKey
    // 页面内容用延迟后的 key：切换瞬间旧页保持可见，新页在后续渲染中挂载
    const pageKey = navItems.some((item) => item.key === deferredActiveKey) ? deferredActiveKey : effectiveKey

    return (
        <div className="data-layout">
            {/* 左侧 TableNav */}
            <div className="data-nav">
                <div className="data-nav-header">
                    <span className="data-nav-title"><Database size={18} className="data-nav-title__icon" /> Tables</span>
                </div>
                <div className="data-nav-list">
                    {navItems.map((item) => {
                        const Icon = item.icon
                        return (
                            <ESButton appearance="unstyled"
                                key={item.key}
                                className={`data-nav-item ${effectiveKey === item.key ? "active" : ""}`}
                                title={`Open the ${item.label.toLowerCase()} data table`}
                                onClick={() => {
                                    setActiveKey(item.key)
                                    const next = new URLSearchParams(searchParams)
                                    next.set("dataNav", item.key)
                                    setSearchParams(next, { replace: true })
                                }}
                            >
                                <Icon size={16} />
                                <span>{item.label}</span>
                                {/* <span className="data-count-badge">{item.count}</span> */}
                            </ESButton>
                        )
                    })}
                </div>
            </div>

            {/* 右侧内容 - keep-alive：已访问页面隐藏而不卸载，切换无重拉闪烁 */}
            {navItems
                .filter((item) => item.key === pageKey || visitedKeys.has(item.key))
                .map((item) => {
                    const PageComponent = item.component
                    return (
                        <div
                            key={item.key}
                            className={`data-page-keepalive${item.key === pageKey ? " data-page-keepalive--active" : ""}`}
                        >
                            <PageComponent />
                        </div>
                    )
                })}
        </div>
    )
}
