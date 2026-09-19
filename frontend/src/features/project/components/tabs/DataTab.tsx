import { Button as ESButton } from "@/components/ui"
/**
 * DataTab - 数据管理页
 *
 * 包含: 左侧 TableNav（实体表导航）+ 右侧由独立页面组件渲染
 * 每个左侧菜单项对应独立的页面组件，可单独编辑。
 */

import { useState, useLayoutEffect, useRef, useEffect, useDeferredValue, useMemo } from "react"
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
    AudioLines,
    Image,
    Images,
    ChevronDown,
    ChevronRight,
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

interface NavGroup {
    key: string
    label: string
    icon: LucideIcon
    children: NavItem[]
}

type NavNode = NavItem | NavGroup

function isNavGroup(node: NavNode): node is NavGroup {
    return "children" in node
}

/** 菜单项图标映射 */
const ICON_MAP: Record<string, LucideIcon> = {
    "project": FolderKanban,
    "collection": Library,
    "user": Users,
    "audio": AudioLines,
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

const MEDIA_GROUP_CHILD_KEYS = ["audio", "photo"] as const
const ANNOTATION_GROUP_CHILD_KEYS = ["annotation", "review", "task"] as const

const GROUP_EXPANDED_STORAGE_PREFIX = "eco-signal.data-nav.group-expanded."

function readGroupExpanded(groupKey: string, fallback: boolean): boolean {
    try {
        const raw = sessionStorage.getItem(`${GROUP_EXPANDED_STORAGE_PREFIX}${groupKey}`)
        if (raw === "1") return true
        if (raw === "0") return false
    } catch {
        // ignore
    }
    return fallback
}

function writeGroupExpanded(groupKey: string, expanded: boolean) {
    try {
        sessionStorage.setItem(`${GROUP_EXPANDED_STORAGE_PREFIX}${groupKey}`, expanded ? "1" : "0")
    } catch {
        // ignore
    }
}

/**
 * Build hierarchical nav: Media (Audios/Photos) and Annotations (Annotations/Reviews/Tasks).
 * Group parents are labels only — they do not open a page (unlike Settings → Sensors).
 */
function buildNavTree(items: NavItem[]): NavNode[] {
    const byKey = new Map(items.map((item) => [item.key, item]))
    const used = new Set<string>()
    const result: NavNode[] = []

    const takeGroup = (groupKey: string, label: string, icon: LucideIcon, childKeys: readonly string[]) => {
        const children = childKeys
            .map((key) => byKey.get(key))
            .filter((item): item is NavItem => item != null)
        if (children.length === 0) return
        for (const child of children) used.add(child.key)
        if (children.length === 1) {
            result.push(children[0]!)
            return
        }
        result.push({ key: groupKey, label, icon, children })
    }

    const topLevelOrder = [
        "project",
        "collection",
        "site",
        "user",
        "media",
        "annotation-group",
        "index-log",
        "queue",
    ] as const

    for (const slot of topLevelOrder) {
        if (slot === "media") {
            takeGroup("media", "Media", Images, MEDIA_GROUP_CHILD_KEYS)
            continue
        }
        if (slot === "annotation-group") {
            takeGroup("annotation-group", "Annotations", ScanLine, ANNOTATION_GROUP_CHILD_KEYS)
            continue
        }
        const item = byKey.get(slot)
        if (!item) continue
        used.add(item.key)
        result.push(item)
    }

    for (const item of items) {
        if (!used.has(item.key)) result.push(item)
    }

    return result
}

function flattenNavLeaves(nodes: NavNode[]): NavItem[] {
    const leaves: NavItem[] = []
    for (const node of nodes) {
        if (isNavGroup(node)) leaves.push(...node.children)
        else leaves.push(node)
    }
    return leaves
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
    const [refreshCounter, setRefreshCounter] = useState(0)
    const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
    const resizeRafRef = useRef<number | null>(null)
    const resizeRafNestedRef = useRef<number | null>(null)
    const didInitRef = useRef(false)

    const navTree = useMemo(() => buildNavTree(navItems), [navItems])
    const leafItems = useMemo(() => flattenNavLeaves(navTree), [navTree])

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

        const visibleKeys = new Set(leafItems.map((item) => item.key))
        const urlKey = dataNavFromUrl && visibleKeys.has(dataNavFromUrl) ? dataNavFromUrl : null
        const targetKey =
            dataTabTargetNavKey && visibleKeys.has(dataTabTargetNavKey) ? dataTabTargetNavKey : null
        const nextKey = urlKey ?? targetKey ?? leafItems[0]?.key ?? null

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
        leafItems,
        dataNavFromUrl,
        dataTabTargetNavKey,
        clearDataTabTargetNavKey,
        searchParams,
        setSearchParams,
    ])

    useEffect(() => {
        setExpandedGroups((prev) => {
            const next = { ...prev }
            let changed = false
            for (const node of navTree) {
                if (!isNavGroup(node)) continue
                if (next[node.key] !== undefined) continue
                next[node.key] = readGroupExpanded(node.key, true)
                changed = true
            }
            // Keep groups with the active child expanded
            for (const node of navTree) {
                if (!isNavGroup(node)) continue
                if (node.children.some((child) => child.key === activeKey) && next[node.key] !== true) {
                    next[node.key] = true
                    writeGroupExpanded(node.key, true)
                    changed = true
                }
            }
            return changed ? next : prev
        })
    }, [navTree, activeKey])

    useLayoutEffect(() => {
        if (!activeKey) return
        const next = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "")
        if (next.get("dataNav") === activeKey) return
        next.set("dataNav", activeKey)
        setSearchParams(next, { replace: true })
    }, [activeKey, setSearchParams])

    const handleNavClick = (key: string) => {
        if (activeKey === key) {
            setRefreshCounter((c) => c + 1)
        } else {
            setActiveKey(key)
            const next = new URLSearchParams(searchParams)
            next.set("dataNav", key)
            setSearchParams(next, { replace: true })
        }
    }

    const toggleGroup = (groupKey: string) => {
        setExpandedGroups((prev) => {
            const nextExpanded = !(prev[groupKey] ?? true)
            writeGroupExpanded(groupKey, nextExpanded)
            return { ...prev, [groupKey]: nextExpanded }
        })
    }

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
    if (leafItems.length === 0 || !activeKey) return <div className="data-layout" />

    // activeKey 不在可见菜单内时回退到第一项，保证右侧始终有页面渲染
    const effectiveKey = leafItems.some((item) => item.key === activeKey) ? activeKey : leafItems[0]?.key ?? activeKey
    // 页面内容用延迟后的 key：切换瞬间旧页保持可见，新页在后续渲染中挂载
    const pageKey = leafItems.some((item) => item.key === deferredActiveKey) ? deferredActiveKey : effectiveKey

    const renderLeafButton = (item: NavItem, className = "") => {
        const Icon = item.icon
        return (
            <ESButton
                appearance="unstyled"
                key={item.key}
                className={`data-nav-item ${className} ${effectiveKey === item.key ? "active" : ""}`.trim()}
                title={`Open the ${item.label.toLowerCase()} data table`}
                onClick={() => handleNavClick(item.key)}
            >
                <Icon size={16} />
                <span>{item.label}</span>
            </ESButton>
        )
    }

    return (
        <div className="data-layout">
            {/* 左侧 TableNav */}
            <div className="data-nav">
                <div className="data-nav-header">
                    <span className="data-nav-title"><Database size={18} className="data-nav-title__icon" /> Tables</span>
                </div>
                <div className="data-nav-list">
                    {navTree.map((node) => {
                        if (!isNavGroup(node)) {
                            return renderLeafButton(node)
                        }

                        const GroupIcon = node.icon
                        const expanded = expandedGroups[node.key] ?? true
                        const childActive = node.children.some((child) => child.key === effectiveKey)

                        return (
                            <div
                                className={`data-nav-group${childActive ? " data-nav-group--child-active" : ""}`}
                                key={node.key}
                            >
                                <div className="data-nav-group-header">
                                    <button
                                        type="button"
                                        className="data-nav-group-label"
                                        aria-expanded={expanded}
                                        title={`${expanded ? "Collapse" : "Expand"} ${node.label}`}
                                        onClick={() => toggleGroup(node.key)}
                                    >
                                        <GroupIcon size={16} aria-hidden />
                                        <span>{node.label}</span>
                                        <span className="data-nav-group-chevron" aria-hidden>
                                            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                        </span>
                                    </button>
                                </div>
                                {expanded ? (
                                    <div
                                        className="data-nav-group-children"
                                        role="group"
                                        aria-label={node.label}
                                    >
                                        {node.children.map((child) =>
                                            renderLeafButton(child, "data-nav-child"),
                                        )}
                                    </div>
                                ) : null}
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* 右侧内容 - 切换或点击列表时挂载并请求最新数据 */}
            {leafItems
                .filter((item) => item.key === pageKey)
                .map((item) => {
                    const PageComponent = item.component
                    return (
                        <div
                            key={`${item.key}-${refreshCounter}`}
                            className="data-page-keepalive data-page-keepalive--active"
                        >
                            <PageComponent />
                        </div>
                    )
                })}
        </div>
    )
}
