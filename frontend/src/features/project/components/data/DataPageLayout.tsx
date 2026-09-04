import { Button as ESButton } from "@/components/ui"
/**
 * DataPageLayout - 通用数据页面布局
 *
 * 提供: 顶部 Toolbar（搜索、CRUD、AI、导出等）+ 可排序/可选择的表格 + 分页
 * 每个数据页面（Projects、Collections 等）使用此布局，传入自己的列定义、数据和表单字段。
 */

import { Children, Fragment, isValidElement, useState, useMemo, useEffect, useLayoutEffect, useRef, useCallback } from "react"
import type { Key, ReactNode } from "react"
import type { LucideIcon } from "lucide-react"
import dayjs, { type Dayjs } from "dayjs"
import { useAppStore } from "@/store/useAppStore"
import { EmptyState } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { useDelayedFlag } from "@/hooks/useDelayedFlag"
import {
    Plus,
    Pencil,
    Trash2,
    Download,
    FileUp,
    Info,
    RotateCcw,
    MoreHorizontal,
    Eye,
    ChevronsUpDown,
    ChevronUp,
    ChevronDown,
} from "lucide-react"
import { CrudFormModal } from "../modals/CrudFormModal"
import { AIModelsPanel } from "../modals/AIModelsPanel"
import { AcousticIndicesPanel } from "../modals/AcousticIndicesPanel"
import { ConfirmDialog } from "../modals/ConfirmDialog"
import { submitTabularImport } from "@/api/tabularImport"
import { IMPORT_RESOURCE_CONFIGS, type ImportResourceKey } from "@/features/imports/importConfigs"
import { useTabularImport } from "@/features/imports/useTabularImport"
import { useProjectStore } from "../../stores/useProjectStore"
import { Checkbox, Combobox, ConfigProvider, DataTable, DatePicker, DropdownMenu, getTooltipText, Input, RowActions, TableToolbar, Tooltip, theme as antdTheme } from "@/components/ui"
import type { ThemeConfig } from "@/components/ui"
import type { RowCapabilities } from "@/api/capabilities"
import type { MenuProps } from "@/components/ui"
import { INTERNAL_COL_DEFINE } from "@/components/ui"
import "./styles/DataPageLayout.css"

const { RangePicker } = DatePicker

/** 复选框列固定宽度（px）；须为 number 供 rc-table 列宽计算 */
export const SELECTION_COL_W = 50

const SELECTION_COL_PX = `${SELECTION_COL_W}px`

function DataToolbarTooltips({ children }: { children: ReactNode }) {
    return (
        <>
            {Children.map(children, (child) => {
                if (!isValidElement(child)) return child

                if (child.type === Fragment) {
                    return (
                        <DataToolbarTooltips key={child.key}>
                            {child.props.children}
                        </DataToolbarTooltips>
                    )
                }

                const className = typeof child.props.className === "string" ? child.props.className : ""
                const isDataAction = className.includes("data-btn") || className.includes("nav-center-btn")
                const title = typeof child.props.title === "string" ? child.props.title : undefined
                if (!isDataAction || !title) return child

                const trigger = child.props.disabled ? (
                    <span className="data-toolbar-tooltip-trigger">{child}</span>
                ) : child

                return (
                    <Tooltip key={child.key} title={getTooltipText(title)}>
                        {trigger}
                    </Tooltip>
                )
            })}
        </>
    )
}

/** Status 列彩色标签：queue / task / review 各领域枚举不同，统一做小写归一 */
export type StatusBadgeSemantic = "queue" | "task" | "review" | "labelType"

function statusBadgeClassName(semantic: StatusBadgeSemantic, raw: unknown): string {
    const v = String(raw ?? "")
        .toLowerCase()
        .trim()
        .replace(/\s+/g, " ")

    if (semantic === "queue") {
        if (v === "finished" || v === "done" || v === "complete" || v === "completed") return "data-badge-success"
        if (v === "running") return "data-badge-info"
        if (v === "failed" || v === "error") return "data-badge-danger"
        if (v === "warning") return "data-badge-warning"
        if (v === "queued" || v === "pending" || v === "waiting") return "data-badge-neutral"
        return "data-badge-neutral"
    }

    if (semantic === "task") {
        if (v === "reviewed") return "data-badge-success"
        if (v === "assigned") return "data-badge-info"
        if (v === "completed") return "data-badge-success"
        if (v === "in progress") return "data-badge-info"
        if (v === "pending") return "data-badge-warning"
        if (v === "canceled" || v === "cancelled") return "data-badge-neutral"
        return "data-badge-neutral"
    }

    if (semantic === "labelType") {
        if (v === "private") return "data-badge-label-private"
        if (v === "public") return "data-badge-success"
        return "data-badge-neutral"
    }

    // review
    if (v === "accept" || v === "accepted") return "data-badge-success"
    if (v === "corrected") return "data-badge-info"
    if (v === "rejected" || v === "reject") return "data-badge-danger"
    if (v === "uncertain") return "data-badge-neutral"
    return "data-badge-neutral"
}

function rowIdForCurrentHighlight(record: RowData, idField: string): string | null {
    const primary = record[idField]
    if (primary !== undefined && primary !== null && String(primary).trim() !== "") {
        return String(primary)
    }
    return null
}

function resolveColumnMaxWidth(width?: string | number, maxWidth?: string | number): string | number | undefined {
    if (maxWidth != null) return maxWidth
    if (width == null) return undefined
    if (typeof width === "number") return width * 2
    return `calc(${width} * 2)`
}

function resolveColumnWidthPx(width?: string | number): number | null {
    if (width == null) return null
    if (typeof width === "number" && Number.isFinite(width)) return width
    const raw = String(width).trim()
    const pxMatch = raw.match(/^(\d+(?:\.\d+)?)px$/i)
    if (pxMatch) return Number(pxMatch[1])
    const num = Number(raw)
    return Number.isFinite(num) ? num : null
}

/** rc-table useWidthColumns 只识别 number/%，ColumnDef 的 "140px" 需转成 number */
function resolveAntdColumnWidth(width?: string | number): number | undefined {
    const px = resolveColumnWidthPx(width)
    return px ?? undefined
}

function columnHasSelectFilter(col: ColumnDef): boolean {
    return Array.isArray(col.filterOptions) && col.filterOptions.length > 0
}

function numberRangeBoundsForColumn(key: string): { min: number; max: number } | null {
    if (key === "latitude") return { min: -90, max: 90 }
    if (key === "longitude") return { min: -180, max: 180 }
    return null
}

function isPartialNumberInput(value: string): boolean {
    return value === "" || value === "-" || value === "." || value === "-."
}

function isNumberInputWithinBounds(value: string, bounds: { min: number; max: number } | null): boolean {
    if (isPartialNumberInput(value)) return true
    const n = Number(value)
    if (!Number.isFinite(n)) return false
    if (!bounds) return true
    return n >= bounds.min && n <= bounds.max
}

function sanitizeNumberRangeFilterValue(
    rawValue: string,
    bounds: { min: number; max: number } | null,
): string {
    const parts = rawValue.split(",")
    const nextParts = [parts[0] ?? "", parts[1] ?? ""].map((part) =>
        isNumberInputWithinBounds(part, bounds) && !isPartialNumberInput(part) ? part : "",
    )
    return nextParts[0] || nextParts[1] ? nextParts.join(",") : ""
}

/** Convert the serialized date-range filter back to the value expected by AntD. */
function dateRangeValueForFilter(value: string | undefined): [Dayjs | null, Dayjs | null] | null {
    if (!value) return null
    const [start, end] = value.split(",")
    const parsedStart = start ? dayjs(start) : null
    const parsedEnd = end ? dayjs(end) : null
    return [
        parsedStart?.isValid() ? parsedStart : null,
        parsedEnd?.isValid() ? parsedEnd : null,
    ]
}

/** 复选框列保持 baseWidths[0]，其余列按定义宽度比例分配额外空间以填满容器 */
function expandColumnsToFill(baseWidths: number[], targetTotal: number): number[] {
    const currentTotal = baseWidths.reduce((sum, w) => sum + w, 0)
    if (targetTotal <= currentTotal || baseWidths.length <= 1) return baseWidths

    const extra = targetTotal - currentTotal
    const dataWidths = baseWidths.slice(1)
    const dataSum = dataWidths.reduce((sum, w) => sum + w, 0)
    if (dataSum <= 0) return baseWidths

    const selectionW = baseWidths[0] ?? 0
    const result: number[] = [selectionW]
    let distributed = 0
    for (let i = 0; i < dataWidths.length; i++) {
        const colW = dataWidths[i] ?? 0
        if (i === dataWidths.length - 1) {
            result.push(colW + extra - distributed)
        } else {
            const add = Math.floor((extra * colW) / dataSum)
            result.push(colW + add)
            distributed += add
        }
    }
    return result
}

// ---- 类型定义 ----
export interface ColumnDef {
    key: string
    label: string
    /** Optional explanation shown when hovering the column label. */
    tooltip?: string
    /** 列的类型 */
    type: "text" | "number" | "date" | "select" | "badge" | "boolean" | "actions"
    /** 自定义单元格渲染 */
    renderCell?: (value: unknown, record: RowData) => ReactNode
    /** Set false when a column should show full text and rely on horizontal scroll. */
    ellipsis?: boolean
    width?: string | number
    maxWidth?: string | number
    sortable?: boolean
    /** 是否可过滤 */
    filterable?: boolean
    filterOptions?: (string | { label: string, value: string | number })[]
    filterSearch?: boolean
    /** 可过滤类型 ('dateRange', 'numberRange', or default input) */
    filterType?: "dateRange" | "numberRange"
    /** dateRange 是否显示时分；未设置时保持现有带时间行为 */
    filterShowTime?: boolean
    /** 为 true 时禁用该列表头下拉筛选（如 IUCN 联动子级未选父级时） */
    filterDisabled?: boolean
    /** type 为 badge 时：按业务语义着色（否则保留原逻辑：值为 false 时红色） */
    badgeSemantic?: StatusBadgeSemantic
}

export interface FormFieldDef {
    key: string
    label: string
    type: "text" | "number" | "select" | "textarea" | "date"
    options?: string[] | { label: string; value: string | number }[]
    required?: boolean
    readonly?: boolean
}

export type RowData = Record<string, any> & { capabilities?: Partial<RowCapabilities> }

type SortDir = "asc" | "desc" | null
export type DataNavFilter = "current" | "all"

export interface TabularImportConfig {
    endpoint: string
    resourceKey: ImportResourceKey
    importOnly?: boolean
    fields?: Record<string, string | number | boolean | null | undefined>
    disabled?: boolean
    disabledReason?: string
    importLabel?: string
    instructionsLabel?: string
    addLabel?: string
    variants?: TabularImportVariant[]
}

export interface TabularImportVariant {
    key: string
    label: string
    resourceKey: ImportResourceKey
    fields?: Record<string, string | number | boolean | null | undefined>
}

export interface TableState {
    page: number
    pageSize: number
    searchQuery: string
    filters: Record<string, string>
    sortKey: string | null
    sortDir: SortDir
    /** Current/All nav filter when `showNavFilter` is enabled */
    navFilter?: "current" | "all"
}

export interface DataPageLayoutProps {
    /** 页面标题，如 "Projects" */
    title: string
    /** 标题前的图标，与左侧菜单一致 */
    icon?: LucideIcon
    /** 列定义 */
    columns: ColumnDef[]
    /** 行数据 */
    rows: RowData[]
    /** CRUD 表单字段 */
    formFields: FormFieldDef[]
    /** 每页行数，默认 10 */
    pageSize?: number
    /** 是否显示 Current/All 筛选按钮 */
    showNavFilter?: boolean
    /** Nav filter 的默认值 */
    defaultNavFilter?: DataNavFilter
    /** Controlled Current/All nav filter. */
    navFilterValue?: DataNavFilter
    /** Called when the Current/All nav filter changes. */
    onNavFilterChange?: (value: DataNavFilter) => void
    /** Default sort field used on first load and Reset table */
    defaultSortKey?: string | null
    /** Default sort direction used on first load and Reset table */
    defaultSortDir?: "asc" | "desc" | null
    /** 额外的工具栏内容（在标准按钮之后渲染） */
    extraToolbar?: React.ReactNode
    /** Render actions immediately after Export CSV with access to the current selection. */
    renderAfterExportActions?: (selectedRows: Set<Key>) => React.ReactNode
    /** 额外的页面内容（在表格之后渲染） */
    extraContent?: React.ReactNode
    /** Loading state for the table */
    loading?: boolean
    /** Custom row key, defaults to "id" */
    rowKey?: string | ((record: RowData) => string)
    /** Indicates if filtering, sorting, and pagination are handled by the server */
    serverSide?: boolean
    /** Total number of rows available on the server (used when serverSide is true) */
    totalRows?: number
    /** Callback fired when any table state (page, filters, sort, search) changes */
    onTableStateChange?: (state: TableState) => void
    /** Custom handler for Add button - if provided, replaces the built-in CrudFormModal */
    onAddCustom?: () => void
    /** Custom handler for Edit button - if provided, replaces the built-in CrudFormModal and receives the selected keys */
    onEditCustom?: (selectedKeys: any[]) => void
    /** Custom handler for Delete sequence - if provided, handles the deletion process with the selected keys */
    onDeleteCustom?: (selectedKeys: any[]) => void
    /** Require the selected record name before deleting high-impact entities. */
    deleteConfirmation?: {
        entityLabel: string
        nameField: string
    }
    /** Render function for custom actions inserted after Edit */
    renderCustomActions?: (selectedRows: Set<Key>) => React.ReactNode
    /** Custom handler for Export CSV button */
    onExportCustom?: () => void
    /** Hide the Export button completely */
    hideExport?: boolean
    /** Optional synchronous CSV/TXT/JSON import endpoint for this list. */
    importConfig?: TabularImportConfig
    /** View：选中行时跳转，传入当前选中行的 key 列表 */
    onViewCustom?: (selectedKeys: Key[]) => void
    /** Custom row double-click handler; when provided it replaces the default edit-on-double-click behavior. */
    onRowDoubleClickCustom?: (record: RowData) => void
    /** 隐藏 View 按钮 */
    hideView?: boolean
    /** 为 false 时允许多选后点击 View（默认仅允许单选） */
    viewRequiresSingle?: boolean
    /** 返回 true 时禁用 View（如选中 metadata） */
    isViewDisabled?: (selectedRows: Set<Key>) => boolean
    /** Dropdown menu items to use instead of the default Add button handler */
    addDropdownItems?: MenuProps['items']
    /** Disable the Add button */
    addDisabled?: boolean
    /** Tooltip shown when the Add button is disabled */
    addDisabledTooltip?: string
    /** Hide the Add button completely */
    hideAdd?: boolean
    /** Hide the Edit button completely */
    hideEdit?: boolean
    /** Hide the Delete button completely */
    hideDelete?: boolean
    /**
     * 写权限门禁：为 false 时禁用对应操作入口（含双击行进入编辑）。
     * 权限未加载完成时应传 false，避免先可点后禁用。
     * / Write gating: disable the matching entry point (including edit-on-double-click)
     * when false. Pass false while permissions load so the control never flips
     * from enabled to disabled.
     */
    canAdd?: boolean
    canEdit?: boolean
    canDelete?: boolean
    canEditRecord?: (record: RowData) => boolean
    canDeleteRecord?: (record: RowData) => boolean
    /** 权限不足时按钮的提示文案 / Tooltip shown when an action is gated by permissions */
    noPermissionTooltip?: string
    /**
     * 表头筛选联动清空：某列筛选变更时，清空列出的子列筛选值（如 realm_name → biome / functional_type）
     */
    filterCascadeClear?: Record<string, string[]>
    /**
     * All 模式下在 `idField` 列给「当前」行打 Current 标签（与全局当前项目/集合/用户对应）
     */
    currentRowHighlight?: {
        idField: string
        currentId: number | string | null | undefined
    }
    /**
     * 在指定列单元格内、主内容右侧显示一枚标签（如 Reviews：当前用户自己的评审显示 Task）
     */
    taskPill?: {
        columnKey: string
        isTaskRow: (record: RowData) => boolean
        label?: string
    }
    /** Override AntD theme for hosts that should not inherit project sphere theme, e.g. Settings. */
    antdThemeOverride?: ThemeConfig
}

export function DataPageLayout({
    title,
    icon: Icon,
    columns,
    rows: allRows,
    formFields,
    pageSize: pageSizeProp = 10,
    showNavFilter = false,
    defaultNavFilter = "current",
    navFilterValue,
    onNavFilterChange,
    defaultSortKey = null,
    defaultSortDir = null,
    extraToolbar,

    extraContent,
    loading = false,
    rowKey = "id",
    serverSide = false,
    totalRows = 0,
    onTableStateChange,
    onAddCustom,
    onEditCustom,
    onDeleteCustom,
    deleteConfirmation,
    renderCustomActions,
    onExportCustom,
    renderAfterExportActions,
    hideExport = false,
    importConfig,
    onViewCustom,
    onRowDoubleClickCustom,
    hideView,
    viewRequiresSingle = true,
    isViewDisabled,
    addDropdownItems,
    addDisabled = false,
    addDisabledTooltip,
    hideAdd = false,
    hideEdit = false,
    hideDelete = false,
    canAdd = true,
    canEdit = true,
    canDelete = true,
    canEditRecord,
    canDeleteRecord,
    noPermissionTooltip = "You do not have permission to perform this action",
    filterCascadeClear,
    currentRowHighlight,
    taskPill,
    antdThemeOverride,
}: DataPageLayoutProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)
    const [brandPrimary, setBrandPrimary] = useState("var(--brand)")
    const [importRefreshToken, setImportRefreshToken] = useState(0)

    useLayoutEffect(() => {
        const raw = getComputedStyle(document.documentElement).getPropertyValue("--brand").trim()
        if (!raw) return
        if (raw.startsWith("#")) {
            setBrandPrimary(raw)
            return
        }
        const m = raw.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/)
        if (m) {
            const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])]
            const hex = `#${[r, g, b].map((x) => x.toString(16).padStart(2, "0")).join("")}`
            setBrandPrimary(hex)
        }
    }, [isDark, currentProjectId, currentCollectionId])

    /** 勿设置全局 fontSize 为 12，会连带缩小整张 antd Table 单元格；筛选用 .dpl-filter-* 单独控制 */
    const antdAppTheme = useMemo(
        () => ({
            algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
            token: {
                colorPrimary: brandPrimary,
                colorLink: brandPrimary,
                colorInfo: brandPrimary,
                colorBorder: "var(--border-color)",
            },
            components: {
                Table: {
                    stickyScrollBarBg: brandPrimary,
                    selectionColumnWidth: SELECTION_COL_W,
                },
                Select: {
                    selectorBg: "var(--es-color-bg-surface)",
                    controlHeight: 32,
                },
                Input: {
                    colorBorder: "var(--es-color-border)",
                    colorBgContainer: "var(--es-color-bg-subtle)",
                    controlHeight: 32,
                },
                DatePicker: {
                    colorBgContainer: "var(--es-color-bg-surface)",
                    controlHeight: 32,
                }
            },
        }),
        [isDark, brandPrimary]
    )

    const tableWrapRef = useRef<HTMLDivElement>(null)
    const paginationRef = useRef<HTMLDivElement>(null)
    const [tableScrollY, setTableScrollY] = useState<number>(420)
    const [tableContainerWidth, setTableContainerWidth] = useState(0)

    // ── 自定义水平滚动条 ──
    const hTrackRef = useRef<HTMLDivElement>(null)
    const [hThumb, setHThumb] = useState({ show: false, size: 0, offset: 0 })
    const hDragRef = useRef<{
        pointerId: number
        startClient: number
        startScroll: number
        maxScroll: number
        maxOffset: number
    } | null>(null)
    const [hDragging, setHDragging] = useState(false)

    useLayoutEffect(() => {
        const wrap = tableWrapRef.current
        if (!wrap || typeof ResizeObserver === "undefined") return

        const measure = () => {
            const h = wrap.clientHeight
            const w = wrap.clientWidth
            // 隐藏页（keep-alive display:none）clientWidth 为 0，跳过测量以保留上次有效宽度，
            // 避免切回时从 0 重排导致列宽闪烁
            if (w === 0) return
            setTableContainerWidth((prev) => (prev !== w ? w : prev))
            const thead = wrap.querySelector(".ant-table-thead")
            const th = thead?.getBoundingClientRect().height ?? 88
            const ph = paginationRef.current?.getBoundingClientRect().height ?? 48
            const gap = 12
            const safety = 16
            setTableScrollY(Math.max(120, Math.floor(h - th - ph - gap - safety)))
        }

        // useLayoutEffect 在绘制前执行：可见时同步测量，保证首帧列宽一次到位（不再先挤压后撑开）
        measure()

        const ro = new ResizeObserver(() => {
            requestAnimationFrame(measure)
        })
        ro.observe(wrap)

        let pagObs: ResizeObserver | null = null
        if (paginationRef.current) {
            pagObs = new ResizeObserver(() => requestAnimationFrame(measure))
            pagObs.observe(paginationRef.current)
        }

        requestAnimationFrame(() => requestAnimationFrame(measure))
        const t0 = window.setTimeout(measure, 0)
        const t1 = window.setTimeout(measure, 120)
        const t2 = window.setTimeout(() => {
            measure()
        }, 300)
        const onResize = () => requestAnimationFrame(measure)
        window.addEventListener("resize", onResize)

        return () => {
            ro.disconnect()
            pagObs?.disconnect()
            window.clearTimeout(t0)
            window.clearTimeout(t1)
            window.clearTimeout(t2)
            window.removeEventListener("resize", onResize)
        }
    }, [loading])

    /** 根据 ant-table-body 当前的 scrollLeft 更新自定义水平滑块的尺寸和偏移 */
    const updateHThumb = useCallback(() => {
        const wrap = tableWrapRef.current
        const track = hTrackRef.current
        if (!wrap || !track) return
        const body = wrap.querySelector<HTMLElement>(".ant-table-body")
        if (!body) return

        const scrollWidth = body.scrollWidth
        const clientWidth = body.clientWidth
        const scrollLeft = body.scrollLeft
        const trackWidth = track.clientWidth

        if (scrollWidth <= clientWidth + 1 || trackWidth < 4) {
            setHThumb((prev) => (prev.show ? { show: false, size: 0, offset: 0 } : prev))
            return
        }

        const thumbSize = Math.max(28, (clientWidth / scrollWidth) * trackWidth)
        const maxScroll = scrollWidth - clientWidth
        const maxOffset = Math.max(0, trackWidth - thumbSize)
        const thumbOffset = maxScroll > 0 ? (scrollLeft / maxScroll) * maxOffset : 0
        setHThumb({ show: true, size: thumbSize, offset: thumbOffset })
    }, [])

    /** 监听 ant-table-body 的 scroll 事件并在 resize 时更新滑块 */
    useLayoutEffect(() => {
        const wrap = tableWrapRef.current
        if (!wrap) return

        let cleanupFn: (() => void) | null = null

        const attach = () => {
            cleanupFn?.()
            const body = wrap.querySelector<HTMLElement>(".ant-table-body")
            if (!body) return

            const onScroll = () => updateHThumb()
            body.addEventListener("scroll", onScroll, { passive: true })
            updateHThumb()

            const ro = new ResizeObserver(() => updateHThumb())
            ro.observe(body)
            ro.observe(wrap)

            cleanupFn = () => {
                body.removeEventListener("scroll", onScroll)
                ro.disconnect()
            }
        }

        // antd 渲染 table-body 是异步的，分两次尝试
        const t0 = window.setTimeout(attach, 0)
        const t1 = window.setTimeout(attach, 200)

        return () => {
            window.clearTimeout(t0)
            window.clearTimeout(t1)
            cleanupFn?.()
        }
    }, [updateHThumb, loading])

    const onHThumbPointerDown = useCallback((e: any) => {
        if (e.button !== 0) return
        const wrap = tableWrapRef.current
        const track = hTrackRef.current
        if (!wrap || !track) return
        const body = wrap.querySelector<HTMLElement>(".ant-table-body")
        if (!body) return

        const maxScroll = Math.max(0, body.scrollWidth - body.clientWidth)
        if (maxScroll < 1 || track.clientWidth < 4) return

        const thumbSize = Math.max(28, (body.clientWidth / body.scrollWidth) * track.clientWidth)
        const maxOffset = Math.max(0, track.clientWidth - thumbSize)
        e.preventDefault()
        e.stopPropagation()
        e.currentTarget.setPointerCapture(e.pointerId)
        hDragRef.current = {
            pointerId: e.pointerId,
            startClient: e.clientX,
            startScroll: body.scrollLeft,
            maxScroll,
            maxOffset: Math.max(maxOffset, 1e-6),
        }
        setHDragging(true)
    }, [])

    const onHThumbPointerMove = useCallback((e: any) => {
        const drag = hDragRef.current
        const wrap = tableWrapRef.current
        if (!drag || !wrap || e.pointerId !== drag.pointerId) return
        const body = wrap.querySelector<HTMLElement>(".ant-table-body")
        if (!body) return
        const delta = e.clientX - drag.startClient
        const ratio = drag.maxScroll / drag.maxOffset
        body.scrollLeft = Math.min(drag.maxScroll, Math.max(0, drag.startScroll + delta * ratio))
    }, [])

    const endHDrag = useCallback((e: any) => {
        const drag = hDragRef.current
        if (!drag || e.pointerId !== drag.pointerId) return
        hDragRef.current = null
        setHDragging(false)
        try {
            if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                e.currentTarget.releasePointerCapture(e.pointerId)
            }
        } catch { /* ignore */ }
    }, [])

    const [sortKey, setSortKey] = useState<string | null>(defaultSortKey)
    const [sortDir, setSortDir] = useState<SortDir>(defaultSortDir)
    const [currentPage, setCurrentPage] = useState(1)
    const [pageSize, setPageSize] = useState(pageSizeProp)
    const [selectedRows, setSelectedRows] = useState<Set<Key>>(new Set())
    const [crudModal, setCrudModal] = useState<{ open: boolean; mode: "add" | "edit" }>({ open: false, mode: "add" })
    const tabularImport = useTabularImport({
        label: importConfig ? IMPORT_RESOURCE_CONFIGS[importConfig.resourceKey].subject : "data",
        config: importConfig ? IMPORT_RESOURCE_CONFIGS[importConfig.resourceKey] : IMPORT_RESOURCE_CONFIGS.projects,
        variants: importConfig?.variants,
        submit: (file, dryRun, variant) => {
            if (!importConfig) return Promise.reject(new Error("Import is not configured"))
            const variantFields = importConfig.variants?.find((item) => item.key === variant)?.fields
            return submitTabularImport(importConfig.endpoint, file, dryRun, { ...importConfig.fields, ...variantFields })
        },
        onCommitted: () => setImportRefreshToken((value) => value + 1),
    })
    const [aiModelsOpen, setAiModelsOpen] = useState(false)
    const [indicesOpen, setIndicesOpen] = useState(false)
    const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
    const [exportConfirmOpen, setExportConfirmOpen] = useState(false)
    const [exportConfirmCount, setExportConfirmCount] = useState(0)
    const [internalNavFilter, setInternalNavFilter] = useState<DataNavFilter>(defaultNavFilter)
    const navFilter = navFilterValue ?? internalNavFilter
    const [columnFilters, setColumnFilters] = useState<Record<string, string>>({})
    const [searchQuery, setSearchQuery] = useState("")
    const [navChanging, setNavChanging] = useState(false)
    const isThemeTransitioning = useAppStore((s) => s.isThemeTransitioning)
    // 延迟显示遮罩：快速请求（<250ms）不闪 loading，避免视觉卡顿感
    const showLoadingOverlay = useDelayedFlag(loading, 250)

    useEffect(() => {
        setSelectedRows((prev) => (prev.size === 0 ? prev : new Set()))
    }, [allRows])

    useEffect(() => {
        // 外部 pageSize 变更时同步（例如不同页面复用组件传入不同默认值）
        setPageSize(pageSizeProp)
    }, [pageSizeProp])

    useEffect(() => {
        if (navFilterValue === undefined) {
            setInternalNavFilter(defaultNavFilter)
        }
    }, [defaultNavFilter, navFilterValue])

    // When navFilter changes, set navChanging to true to hide the pill until loading catches up
    const handleNavChange = (val: DataNavFilter) => {
        if (val !== navFilter) {
            setInternalNavFilter(val)
            onNavFilterChange?.(val)
            setNavChanging(true)
        }
    }

    useEffect(() => {
        if (loading) {
            setNavChanging(false)
        }
    }, [loading])

    // 搜索过滤与排序
    const filteredRows = useMemo(() => {
        if (serverSide) return allRows

        let result = [...allRows]
        // Global search
        if (searchQuery.trim()) {
            const q = searchQuery.toLowerCase().trim()
            result = result.filter((row) => {
                return Object.values(row).some((val) =>
                    String(val ?? "").toLowerCase().includes(q)
                )
            })
        }
        // Column filters
        Object.entries(columnFilters).forEach(([key, val]) => {
            if (val) {
                const q = val.toLowerCase()
                result = result.filter((row) => String(row[key] ?? "").toLowerCase().includes(q))
            }
        })

        // Manual Sort
        if (sortKey && sortDir) {
            result.sort((a, b) => {
                const va = a[sortKey] ?? ""
                const vb = b[sortKey] ?? ""
                let cmp = 0
                if (typeof va === "number" && typeof vb === "number") {
                    cmp = va - vb
                } else {
                    cmp = String(va).localeCompare(String(vb))
                }
                return sortDir === "asc" ? cmp : -cmp
            })
        }

        return result
    }, [allRows, columnFilters, searchQuery, serverSide, sortKey, sortDir])

    const handleExportClick = useCallback(() => {
        if (!onExportCustom) return
        const count = serverSide ? totalRows : filteredRows.length
        setExportConfirmCount(count)
        setExportConfirmOpen(true)
    }, [filteredRows.length, onExportCustom, serverSide, totalRows])

    const getRecordKey = useCallback((record: RowData): Key => {
        if (typeof rowKey === "function") return rowKey(record)
        return record[rowKey as string] as Key
    }, [rowKey])

    const selectedRecords = useMemo(
        () => allRows.filter((record) => selectedRows.has(getRecordKey(record))),
        [allRows, getRecordKey, selectedRows],
    )
    const selectionCanEdit = canEdit
        && selectedRecords.length === 1
        && (canEditRecord?.(selectedRecords[0]!) ?? true)
    const selectionCanDelete = canDelete
        && selectedRecords.length > 0
        && selectedRecords.every((record) => canDeleteRecord?.(record) ?? true)

    const deleteConfirmationName = useMemo(() => {
        if (!deleteConfirmation || selectedRows.size !== 1) return null
        const selectedKey = Array.from(selectedRows)[0]
        const selectedRow = allRows.find((row) => String(getRecordKey(row)) === String(selectedKey))
        const name = selectedRow?.[deleteConfirmation.nameField]
        return name == null ? null : String(name).trim() || null
    }, [allRows, deleteConfirmation, getRecordKey, selectedRows])

    const toggleRowSelected = useCallback((key: Key, selected: boolean) => {
        setSelectedRows((prev) => {
            const next = new Set(prev)
            if (selected) next.add(key)
            else next.delete(key)
            return next
        })
    }, [])

    const toggleRowSelection = useCallback((record: RowData) => {
        const key = getRecordKey(record)
        setSelectedRows((prev) => {
            const next = new Set(prev)
            if (next.has(key)) next.delete(key)
            else next.add(key)
            return next
        })
    }, [getRecordKey])

    const toggleSelectAllVisible = useCallback(() => {
        const keys = filteredRows.map(getRecordKey)
        if (keys.length === 0) return
        setSelectedRows((prev) => {
            const next = new Set(prev)
            const allSelected = keys.every((k) => next.has(k))
            if (allSelected) keys.forEach((k) => next.delete(k))
            else keys.forEach((k) => next.add(k))
            return next
        })
    }, [filteredRows, getRecordKey])

    const antdColumns = useMemo(() => {
        const wrapCurrentPill = (colKey: string, record: RowData, inner: ReactNode) => {
            if (!showNavFilter || !currentRowHighlight || loading || navChanging) return inner
            if (navFilter !== "all") return inner
            const { idField, currentId } = currentRowHighlight
            if (colKey !== idField) return inner
            if (currentId == null || String(currentId).trim() === "") return inner
            const rowId = rowIdForCurrentHighlight(record, idField)
            if (rowId == null || rowId !== String(currentId)) return inner
            return (
                <span className="data-cell-with-current">
                    {inner}
                    <span className="data-current-pill">Current</span>
                </span>
            )
        }

        const applyTaskPill = (inner: ReactNode, col: ColumnDef, record: RowData) => {
            if (!taskPill || col.key !== taskPill.columnKey || !taskPill.isTaskRow(record)) {
                return inner
            }
            return (
                <span className="data-cell-with-current">
                    {inner}
                    <span className="data-task-pill">{taskPill.label ?? "Task"}</span>
                </span>
            )
        }

        const visibleKeys = filteredRows.map(getRecordKey)
        const selectedSet = selectedRows
        const allVisibleSelected = visibleKeys.length > 0 && visibleKeys.every((k) => selectedSet.has(k))
        const someVisibleSelected = visibleKeys.some((k) => selectedSet.has(k))

        const selectionColumn = {
            key: "__selection",
            columnKey: "__selection",
            width: SELECTION_COL_W,
            minWidth: SELECTION_COL_W,
            maxWidth: SELECTION_COL_W,
            fixed: "left" as const,
            align: "center" as const,
            onHeaderCell: () => ({ className: "dpl-th-selection" }),
            onCell: () => ({ className: "dpl-td-selection" }),
            [INTERNAL_COL_DEFINE]: { className: "dpl-col-selection" },
            title: (
                <div className="dpl-select-head" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                        indeterminate={someVisibleSelected && !allVisibleSelected}
                        checked={allVisibleSelected}
                        onChange={toggleSelectAllVisible}
                    />
                </div>
            ),
            render: (_t: unknown, record: RowData) => {
                const key = getRecordKey(record)
                return (
                    <div className="dpl-select-cell" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                            checked={selectedSet.has(key)}
                            onChange={(e) => toggleRowSelected(key, e.target.checked)}
                        />
                    </div>
                )
            },
        }

        const dataColumns = columns.map((col) => {
            const resolvedMaxWidth = resolveColumnMaxWidth(col.width, col.maxWidth)
            const colWidth = resolveAntdColumnWidth(col.width)
            const shouldEllipsis = col.ellipsis ?? col.type !== "actions"
            return {
                key: col.key,
                dataIndex: col.key,
                width: colWidth,
                ellipsis: shouldEllipsis,
                onCell: () => ({
                    style: resolvedMaxWidth != null ? { maxWidth: resolvedMaxWidth } : undefined,
                }),
                title: (
                    <div className="dpl-th-layout">
                        <div
                            className={`dpl-th-title-container ${col.sortable ? 'sortable' : ''}`}
                            onClick={() => col.sortable && toggleSort(col.key)}
                        >
                            <div className="dpl-th-title" style={{
                                color: sortKey === col.key ? 'var(--brand)' : 'inherit',
                                fontWeight: sortKey === col.key ? 'bold' : 'normal'
                            }}>
                                {col.tooltip ? (
                                    <Tooltip title={col.tooltip}>
                                        <span className="dpl-th-label-tooltip">{col.label}</span>
                                    </Tooltip>
                                ) : col.label}
                            </div>
                            {col.sortable && (
                                <div className={`dpl-th-sort-icon ${sortKey === col.key ? 'active' : ''}`}>
                                    {sortKey === col.key ? (
                                        sortDir === 'asc' ? <ChevronUp size={18} /> : <ChevronDown size={18} />
                                    ) : (
                                        <ChevronsUpDown size={18} />
                                    )}
                                </div>
                            )}
                        </div>
                        {col.filterable && (
                            <div className="th-filter" onClick={(e) => e.stopPropagation()}>
                                {col.filterType === 'dateRange' ? (
                                    <RangePicker
                                        value={dateRangeValueForFilter(columnFilters[col.key])}
                                        showTime={col.filterShowTime === false ? false : { format: 'HH:mm' }}
                                        format={col.filterShowTime === false ? "YYYY-MM-DD" : "YYYY-MM-DD HH:mm"}
                                        size="small"
                                        className="dpl-filter-range"
                                        classNames={{
                                            popup: {
                                                root: `data-dpl-picker-popup${antdThemeOverride ? " data-dpl-picker-popup--theme-override" : ""}`,
                                            },
                                        }}
                                        onChange={(dates, dateStrings) => {
                                            if (!dates) {
                                                setColumnFilters(prev => ({ ...prev, [col.key]: "" }))
                                                setCurrentPage(1)
                                                return;
                                            }
                                            const val = dateStrings && (dateStrings[0] || dateStrings[1]) ? dateStrings.join(',') : ""
                                            setColumnFilters(prev => ({ ...prev, [col.key]: val }))
                                            setCurrentPage(1)
                                        }}
                                    />
                                ) : col.filterType === 'numberRange' ? (
                                    <div className="dpl-filter-number-group">
                                        <Input
                                            size="small"
                                            type="number"
                                            min={numberRangeBoundsForColumn(col.key)?.min}
                                            max={numberRangeBoundsForColumn(col.key)?.max}
                                            className="dpl-filter-number-input"
                                            value={(() => { const v = String(columnFilters[col.key] || ''); return v.split(',')[0] || '' })()}
                                            onChange={(e) => {
                                                const bounds = numberRangeBoundsForColumn(col.key)
                                                if (!isNumberInputWithinBounds(e.target.value, bounds)) return
                                                const parts = String(columnFilters[col.key] || '').split(',')
                                                parts[0] = e.target.value
                                                setColumnFilters(prev => ({ ...prev, [col.key]: parts.join(',') }))
                                                setCurrentPage(1)
                                            }}
                                        />
                                        <span className="dpl-filter-dash">-</span>
                                        <Input
                                            size="small"
                                            type="number"
                                            min={numberRangeBoundsForColumn(col.key)?.min}
                                            max={numberRangeBoundsForColumn(col.key)?.max}
                                            className="dpl-filter-number-input"
                                            value={(() => { const v = String(columnFilters[col.key] || ''); return v.split(',')[1] || '' })()}
                                            onChange={(e) => {
                                                const bounds = numberRangeBoundsForColumn(col.key)
                                                if (!isNumberInputWithinBounds(e.target.value, bounds)) return
                                                const parts = String(columnFilters[col.key] || '').split(',')
                                                parts[1] = e.target.value
                                                setColumnFilters(prev => ({ ...prev, [col.key]: parts.join(',') }))
                                                setCurrentPage(1)
                                            }}
                                        />
                                    </div>
                                ) : columnHasSelectFilter(col) ? (
                                    <Combobox
                                        showSearch={col.filterSearch}
                                        size="small"
                                        className="dpl-filter-select"
                                        classNames={{
                                            popup: {
                                                root: `eco-select-popup data-dpl-select-popup${antdThemeOverride ? " data-dpl-select-popup--theme-override" : ""}`,
                                            },
                                        }}
                                        disabled={col.filterDisabled}
                                        value={columnFilters[col.key] || "all"}
                                        onChange={(val) => {
                                            const newVal = val === "all" ? "" : val
                                            setColumnFilters((prev) => {
                                                const next = { ...prev, [col.key]: newVal }
                                                const toClear = filterCascadeClear?.[col.key]
                                                if (toClear) {
                                                    for (const childKey of toClear) {
                                                        next[childKey] = ""
                                                    }
                                                }
                                                return next
                                            })
                                            setCurrentPage(1)
                                        }}
                                        options={[
                                            { value: 'all', label: 'All' },
                                            ...col.filterOptions!.map(opt => typeof opt === "string" ? { value: opt, label: opt } : opt)
                                        ]}
                                        filterOption={(input, option) => {
                                            if (option?.value === 'all') return true;
                                            return String(option?.label ?? '').toLowerCase().includes(input.toLowerCase());
                                        }}
                                    />
                                ) : (
                                    <Input
                                        size="small"
                                        className="dpl-filter-input"
                                        value={columnFilters[col.key] || ""}
                                        onChange={(e) => {
                                            setColumnFilters(prev => ({ ...prev, [col.key]: e.target.value }))
                                            setCurrentPage(1)
                                        }}
                                    />
                                )}
                            </div>
                        )}
                    </div>
                ),
                render: (text: any, _record: any) => {
                    if (col.renderCell) {
                        return wrapCurrentPill(
                            col.key,
                            _record,
                            applyTaskPill(col.renderCell(text, _record), col, _record),
                        )
                    }
                    if (col.type === "badge") {
                        if (text == null || text === "") {
                            return wrapCurrentPill(col.key, _record, applyTaskPill("", col, _record))
                        }
                        const isFalse = String(text).toLowerCase() === "false"
                        const toneClass = col.badgeSemantic
                            ? statusBadgeClassName(col.badgeSemantic, text)
                            : isFalse
                                ? "data-badge-danger"
                                : "data-badge-success"
                        return wrapCurrentPill(
                            col.key,
                            _record,
                            applyTaskPill(
                                <span className={`data-badge ${toneClass}`.trim()}>{text}</span>,
                                col,
                                _record,
                            ),
                        )
                    }
                    if (col.type === "actions") {
                        return (
                            <RowActions className="data-row-actions">
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className="row-action-btn"
                                    title="Open this record in detail"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        const k =
                                            typeof rowKey === "function"
                                                ? rowKey(_record)
                                                : (_record[rowKey as string] as Key)
                                        onViewCustom?.([k])
                                    }}
                                >
                                    <Eye size={14} />
                                </ESButton>
                                <ESButton appearance="unstyled" type="button" className="row-action-btn" title="Show more actions for this record"><MoreHorizontal size={14} /></ESButton>
                            </RowActions>
                        )
                    }
                    if (col.type === "number") {
                        return wrapCurrentPill(
                            col.key,
                            _record,
                            applyTaskPill(<span className="num-cell">{text}</span>, col, _record),
                        )
                    }
                    const display = text == null || text === "" ? "" : String(text)
                    return wrapCurrentPill(
                            col.key,
                            _record,
                            applyTaskPill(
                            <span
                                className={`dpl-cell-text${shouldEllipsis ? "" : " dpl-cell-text--full"}`}
                                title={display}
                            >
                                {display}
                            </span>,
                            col,
                            _record,
                        ),
                    )
                }
            }
        })

        return [selectionColumn, ...dataColumns]
    }, [
        columns,
        columnFilters,
        sortKey,
        sortDir,
        serverSide,
        filterCascadeClear,
        onViewCustom,
        rowKey,
        showNavFilter,
        navFilter,
        currentRowHighlight,
        taskPill,
        loading,
        navChanging,
        filteredRows,
        selectedRows,
        getRecordKey,
        toggleRowSelected,
        toggleSelectAllVisible,
    ]);

    const tableColumnWidthsPx = useMemo(() => {
        const fallbackW = 180
        return [
            SELECTION_COL_W,
            ...columns.map((col) => resolveColumnWidthPx(col.width) ?? fallbackW),
        ]
    }, [columns])

    const definedColumnsTotal = useMemo(
        () => tableColumnWidthsPx.reduce((sum, w) => sum + w, 0),
        [tableColumnWidthsPx],
    )

    const tableScrollX = useMemo(() => {
        if (tableContainerWidth > definedColumnsTotal) return tableContainerWidth
        return definedColumnsTotal
    }, [definedColumnsTotal, tableContainerWidth])

    const resolvedColumnWidthsPx = useMemo(() => {
        if (tableContainerWidth > definedColumnsTotal) {
            return expandColumnsToFill(tableColumnWidthsPx, tableContainerWidth)
        }
        return tableColumnWidthsPx
    }, [tableColumnWidthsPx, tableContainerWidth, definedColumnsTotal])

    /** 锁定 col 宽度：复选框 50px，其余列填满容器时按比例扩展，表头/表体对齐 */
    const pinTableColumnWidths = useCallback(() => {
        const wrap = tableWrapRef.current
        if (!wrap) return
        // 隐藏页宽度为 0，跳过以免用 0 宽状态改写 colgroup 内联宽度
        if (wrap.clientWidth === 0) return

        const applyPx = (el: HTMLElement, px: string) => {
            el.style.setProperty("width", px, "important")
            el.style.setProperty("min-width", px, "important")
            el.style.setProperty("max-width", px, "important")
        }

        wrap.querySelectorAll("table").forEach((table) => {
            table.style.setProperty("width", "100%", "important")
            table.style.setProperty("min-width", `${tableScrollX}px`, "important")

            table.querySelectorAll<HTMLTableColElement>("colgroup > col").forEach((col, i) => {
                if (i >= resolvedColumnWidthsPx.length) return
                const w = resolvedColumnWidthsPx[i]
                if (i === 0) {
                    applyPx(col, SELECTION_COL_PX)
                } else {
                    applyPx(col, `${w}px`)
                }
            })
        })

        wrap.querySelectorAll<HTMLElement>(".dpl-th-selection, .dpl-td-selection").forEach((el) => {
            applyPx(el, SELECTION_COL_PX)
        })
    }, [resolvedColumnWidthsPx, tableScrollX])

    useLayoutEffect(() => {
        const wrap = tableWrapRef.current
        if (!wrap) return

        const run = () => requestAnimationFrame(pinTableColumnWidths)
        run()
        const t0 = window.setTimeout(pinTableColumnWidths, 0)
        const t1 = window.setTimeout(pinTableColumnWidths, 120)

        const ro = new ResizeObserver(run)
        ro.observe(wrap)

        const mo = new MutationObserver(run)
        mo.observe(wrap, { childList: true, subtree: true })

        return () => {
            ro.disconnect()
            mo.disconnect()
            window.clearTimeout(t0)
            window.clearTimeout(t1)
        }
    }, [pinTableColumnWidths, loading, filteredRows.length, columns.length, tableScrollY, tableScrollX, tableContainerWidth, resolvedColumnWidthsPx])

    const openEditForRecord = (record: RowData) => {
        const key = getRecordKey(record)
        setSelectedRows(new Set([key]))
        if (onEditCustom) onEditCustom([key])
        else setCrudModal({ open: true, mode: "edit" })
    }

    const toggleSort = (key: string) => {
        if (sortKey === key) {
            setSortDir(sortDir === "asc" ? "desc" : "asc")
        } else {
            setSortKey(key)
            setSortDir("asc")
        }
        setCurrentPage(1)
    }

    useEffect(() => {
        if (onTableStateChange) {
            const effectiveFilters = { ...columnFilters }
            columns.forEach((col) => {
                if (col.filterType !== "numberRange") return
                const rawValue = effectiveFilters[col.key]
                if (rawValue == null || rawValue === "") return
                const sanitized = sanitizeNumberRangeFilterValue(String(rawValue), numberRangeBoundsForColumn(col.key))
                if (sanitized) {
                    effectiveFilters[col.key] = sanitized
                } else {
                    delete effectiveFilters[col.key]
                }
            })
            if (navFilter === "current") {
                if (currentProjectId != null) {
                    const userPid = columnFilters["project_id"]
                    const hasUserProjectId =
                        userPid !== undefined &&
                        userPid !== null &&
                        String(userPid).trim() !== ""
                    if (!hasUserProjectId) {
                        effectiveFilters["project_id"] = String(currentProjectId)
                    }
                }
                if (title === "Collections" && currentCollectionId != null) {
                    const userCid = columnFilters["collection_id"]
                    const hasUserCollectionId =
                        userCid !== undefined &&
                        userCid !== null &&
                        String(userCid).trim() !== ""
                    if (!hasUserCollectionId) {
                        effectiveFilters["collection_id"] = String(currentCollectionId)
                    }
                }
            }

            onTableStateChange({
                page: currentPage,
                pageSize,
                searchQuery,
                filters: effectiveFilters,
                sortKey,
                sortDir,
                ...(showNavFilter ? { navFilter } : {}),
            });
        }
    }, [currentPage, pageSize, columnFilters, searchQuery, sortKey, sortDir, navFilter, currentProjectId, currentCollectionId, onTableStateChange, title, showNavFilter, columns, importRefreshToken]);

    const addBlocked = addDisabled || !canAdd
    const addBlockedTooltip = !canAdd ? noPermissionTooltip : addDisabledTooltip

    const mergedAddDropdownItems: MenuProps["items"] = []
    if (addDropdownItems) {
        mergedAddDropdownItems.push(...addDropdownItems.map((item) => {
            if (!item || item.type === "divider") return item
            return { ...item, disabled: addBlocked || (item as { disabled?: boolean }).disabled }
        }))
    } else if (!hideAdd) {
        mergedAddDropdownItems.push({
            key: "__add_record",
            label: importConfig?.addLabel ?? `Add ${title.replace(/s$/, "")}`,
            icon: <Plus size={14} />,
            disabled: addBlocked,
            onClick: () => onAddCustom ? onAddCustom() : setCrudModal({ open: true, mode: "add" }),
        })
    }
    if (importConfig) {
        if (importConfig.variants?.length) {
            importConfig.variants.forEach((variant) => {
                mergedAddDropdownItems.push({
                    key: `__import_group_${variant.key}`,
                    type: "group",
                    label: variant.label,
                    children: [
                        {
                            key: `__import_${variant.key}`,
                            label: "Import Data",
                            icon: <FileUp size={14} />,
                            disabled: importConfig.disabled || tabularImport.importing,
                            title: importConfig.disabled ? importConfig.disabledReason : undefined,
                            onClick: () => tabularImport.triggerImport(variant.key),
                        },
                        {
                            key: `__import_instructions_${variant.key}`,
                            label: "Import Instructions",
                            icon: <Info size={14} />,
                            onClick: () => tabularImport.showInstructions(variant.key),
                        },
                    ],
                })
            })
        } else {
            mergedAddDropdownItems.push({
                key: "__import_data",
                label: importConfig.importLabel ?? "Import Data",
                icon: <FileUp size={14} />,
                disabled: importConfig.disabled || tabularImport.importing,
                title: importConfig.disabled ? importConfig.disabledReason : undefined,
                onClick: tabularImport.triggerImport,
            })
            mergedAddDropdownItems.push({
                key: "__import_instructions",
                label: importConfig.instructionsLabel ?? "Import Instructions",
                icon: <Info size={14} />,
                onClick: tabularImport.showInstructions,
            })
        }
    }
    const useAddDropdown = Boolean(importConfig || addDropdownItems)
    const importOnly = importConfig?.importOnly === true
    const showAddAction = !importOnly && (Boolean(importConfig) || !hideAdd)

    return (
        <ConfigProvider theme={antdThemeOverride ?? antdAppTheme}>
            <div className={`data-content${antdThemeOverride ? " data-content--theme-override" : ""}`}>
                {/* 主题切换全屏遮罩 */}
                {isThemeTransitioning && (
                    <div className="dpl-theme-loader-overlay">
                        <LoadingState label="Updating theme..." variant="overlay" size="lg" showLabel={false} />
                    </div>
                )}
                {/* Toolbar */}
                <TableToolbar className="data-toolbar">
                    <div className="data-toolbar-left">
                        <h2 className="data-table-title">
                            {Icon && <Icon size={20} />}
                            {title}
                        </h2>
                        {showNavFilter && (
                            <div className="nav-center">
                                <ESButton appearance="unstyled"
                                    className={`nav-center-btn${navFilter === "current" ? " active" : ""}`}
                                    onClick={() => handleNavChange("current")}
                                    disabled={
                                        title === "Collections" &&
                                        (currentProjectId === null ||
                                            currentProjectId === undefined ||
                                            String(currentProjectId).trim() === "")
                                    }
                                    title={
                                        title === "Collections"
                                            ? "Show collections in the current project that you can manage (write)"
                                            : undefined
                                    }
                                >
                                    Current
                                </ESButton>
                                <ESButton appearance="unstyled"
                                    className={`nav-center-btn${navFilter === "all" ? " active" : ""}`}
                                    onClick={() => handleNavChange("all")}
                                >
                                    All
                                </ESButton>
                            </div>
                        )}
                    </div>
                    <div className="data-toolbar-right">
                        <div className="data-action-group">
                            <DataToolbarTooltips>
                            <ESButton appearance="unstyled" type="button" className="data-btn" title="Reset table" aria-label="Reset" onClick={() => { setColumnFilters({}); setSearchQuery(""); setSortKey(defaultSortKey); setSortDir(defaultSortDir); setSelectedRows(new Set()); setCurrentPage(1) }}>
                                <RotateCcw size={14} /> Reset
                            </ESButton>
                            {!hideView && (
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className="data-btn"
                                    title="Open the selected record in detail"
                                    disabled={
                                        selectedRows.size === 0 ||
                                        !onViewCustom ||
                                        (viewRequiresSingle && selectedRows.size !== 1) ||
                                        (isViewDisabled?.(selectedRows) ?? false)
                                    }
                                    onClick={() => onViewCustom?.(Array.from(selectedRows))}
                                >
                                    <Eye size={14} /> View
                                </ESButton>
                            )}

                            {useAddDropdown ? (
                                ((showAddAction || importOnly) && (
                                    <Tooltip title={addBlocked ? addBlockedTooltip : importOnly ? "Import data" : importConfig ? "Add or import data" : "Add a new record to this table"}>
                                        <span style={{ display: "inline-flex" }}>
                                            <DropdownMenu
                                                items={mergedAddDropdownItems}
                                                trigger={['click']}
                                                placement="bottomLeft"
                                                disabled={addBlocked}
                                                overlayClassName="data-add-dropdown"
                                            >
                                                <ESButton appearance="unstyled" type="button" className="data-btn" title={addBlocked ? addBlockedTooltip : importOnly ? "Import data" : importConfig ? "Add or import data" : "Add a new record to this table"} disabled={addBlocked}>
                                                    {importOnly ? <FileUp size={14} /> : <Plus size={14} />} {importOnly ? "Import" : "Add"}
                                                    <ChevronDown size={14} className="data-btn__dropdown-icon" aria-hidden />
                                                </ESButton>
                                            </DropdownMenu>
                                        </span>
                                    </Tooltip>
                                ))
                            ) : (
                                !hideAdd && (
                                    <Tooltip title={addBlocked ? addBlockedTooltip : "Add a new record to this table"}>
                                        <span style={{ display: "inline-flex" }}>
                                            <ESButton appearance="unstyled" type="button" className="data-btn" title={addBlocked ? addBlockedTooltip : "Add a new record to this table"} disabled={addBlocked} onClick={() => onAddCustom ? onAddCustom() : setCrudModal({ open: true, mode: "add" })}>
                                                <Plus size={14} /> Add
                                            </ESButton>
                                        </span>
                                    </Tooltip>
                                )
                            )}
                            {!hideEdit && (
                                <ESButton
                                    appearance="unstyled"
                                    className="data-btn"
                                    title={selectionCanEdit ? "Edit the selected record" : noPermissionTooltip}
                                    disabled={!selectionCanEdit}
                                    onClick={() => onEditCustom ? onEditCustom(Array.from(selectedRows)) : setCrudModal({ open: true, mode: "edit" })}
                                >
                                    <Pencil size={14} /> Edit
                                </ESButton>
                            )}


                            {renderCustomActions && renderCustomActions(selectedRows)}
                            {!hideDelete && (
                                <ESButton
                                    appearance="unstyled"
                                    className="data-btn danger"
                                    title={!selectionCanDelete
                                        ? noPermissionTooltip
                                        : deleteConfirmation && selectedRows.size !== 1
                                            ? "Select one record to delete"
                                            : deleteConfirmation && !deleteConfirmationName
                                                ? "This record has no name to confirm"
                                                : "Delete"}
                                    disabled={!selectionCanDelete || Boolean(deleteConfirmation && (selectedRows.size !== 1 || !deleteConfirmationName))}
                                    onClick={() => setDeleteConfirmOpen(true)}
                                >
                                    <Trash2 size={14} /> Delete
                                </ESButton>
                            )}
                            {!hideExport && (
                                <ESButton appearance="unstyled" className="data-btn" title="Download the current table as a CSV file" onClick={handleExportClick}>
                                    <Download size={14} /> Export CSV
                                </ESButton>
                            )}
                            {renderAfterExportActions?.(selectedRows)}
                            {extraToolbar}
                            </DataToolbarTooltips>
                        </div>
                    </div>
                </TableToolbar>

                {importConfig ? tabularImport.controls : null}

                {/* Table：scroll.y + CSS 固定表体高度（antd 默认 max-height 会随内容收缩，导致横条贴在行下） */}
                <div
                    className="data-table-wrapper data-table-wrapper--data-module"
                    ref={tableWrapRef}
                    style={{
                        ["--dpl-scroll-y" as string]: `${tableScrollY}px`,
                        ["--dpl-selection-col-width" as string]: SELECTION_COL_PX,
                        ["--dpl-table-scroll-x" as string]: `${tableScrollX}px`,
                    }}
                >
                    <div className="data-table-shell">
                        {showLoadingOverlay ? (
                            <LoadingState
                                label="Loading data..."
                                variant="overlay"
                                size="lg"
                                className="data-table-loading-overlay"
                            />
                        ) : null}
                        <DataTable
                            loading={false}
                            rowKey={rowKey}
                            tableLayout="fixed"
                            columns={antdColumns as any}
                            dataSource={filteredRows}
                            locale={{
                                // 加载中的空表只留空白占位，避免切换时先闪 "No Data" 再跳出数据
                                emptyText: loading ? (
                                    <div className="data-table-empty-state" aria-hidden />
                                ) : (
                                    <EmptyState className="data-table-empty-state" title="No Data" />
                                ),
                            }}
                            scroll={{
                                // 字符串 x：避免 rc-table 在容器宽于列宽之和时等比拉伸（50→67 等）
                                x: `${tableScrollX}`,
                                y: tableScrollY,
                            }}
                            onRow={(record) => ({
                                className: selectedRows.has(getRecordKey(record)) ? "dpl-row-selected" : undefined,
                                onClick: (e) => {
                                    const target = e.target as HTMLElement
                                    // Keep controls and cell actions independent from row selection.
                                    if (target.closest(
                                        ".dpl-td-selection, .dpl-select-cell, button, a, input, textarea, select, [role='button'], [contenteditable='true']",
                                    )) return
                                    toggleRowSelection(record)
                                },
                                onDoubleClick: (e) => {
                                    const t = e.target as HTMLElement
                                    if (t.closest(".dpl-td-selection") || t.closest(".dpl-select-cell")) return
                                    if (t.closest(".ant-checkbox-wrapper") || t.closest("input[type='checkbox']")) return
                                    if (onRowDoubleClickCustom) {
                                        onRowDoubleClickCustom(record)
                                        return
                                    }
                                    if (hideEdit || !canEdit || (canEditRecord && !canEditRecord(record))) return
                                    openEditForRecord(record)
                                },
                            })}
                            pagination={{
                                current: currentPage,
                                pageSize,
                                total: serverSide ? totalRows : filteredRows.length,
                                showSizeChanger: true,
                                showTotal: (total, range) => `${range?.[0] || 0}-${range?.[1] || 0} of ${total} records`,
                                onChange: (page, nextPageSize) => {
                                    if (nextPageSize !== pageSize) setPageSize(nextPageSize)
                                    setCurrentPage(page)
                                },
                                onShowSizeChange: (page, nextPageSize) => {
                                    setPageSize(nextPageSize)
                                    setCurrentPage(page)
                                },
                            }}
                            paginationContainerRef={paginationRef}
                            size="middle"
                        />
                    </div>
                </div>

                {/* 自定义水平滚动条（同步 ant-table-body 横向滚动，原生条已隐藏） */}
                <div ref={hTrackRef} className="dpl-hscroll-track" aria-hidden>
                    {hThumb.show && (
                        <div
                            className={"dpl-hscroll-thumb" + (hDragging ? " dpl-hscroll-thumb--dragging" : "")}
                            style={{ width: hThumb.size, transform: `translateX(${hThumb.offset}px)` }}
                            onPointerDown={onHThumbPointerDown}
                            onPointerMove={onHThumbPointerMove}
                            onPointerUp={endHDrag}
                            onPointerCancel={endHDrag}
                            onLostPointerCapture={() => { hDragRef.current = null; setHDragging(false) }}
                        />
                    )}
                </div>

                {/* Extra content slot */}
                {extraContent}

                {/* Modals */}
                <CrudFormModal
                    open={crudModal.open}
                    onClose={() => setCrudModal({ open: false, mode: "add" })}
                    mode={crudModal.mode}
                    tableName={title}
                    fields={formFields}
                    onSubmit={(data) => console.log("CRUD submit:", data)}
                />
                <AIModelsPanel open={aiModelsOpen} onClose={() => setAiModelsOpen(false)} audioCount={filteredRows.length} />
                <AcousticIndicesPanel open={indicesOpen} onClose={() => setIndicesOpen(false)} audioCount={filteredRows.length} />
                <ConfirmDialog
                    open={deleteConfirmOpen}
                    onClose={() => setDeleteConfirmOpen(false)}
                    title={deleteConfirmation ? `Delete ${deleteConfirmation.entityLabel}` : "Delete Records"}
                    message={deleteConfirmation && deleteConfirmationName
                        ? `Are you sure you want to delete the ${deleteConfirmation.entityLabel} "${deleteConfirmationName}"? This action cannot be undone.`
                        : `Are you sure you want to delete ${selectedRows.size} selected record${selectedRows.size > 1 ? "s" : ""}? This action cannot be undone.`}
                    confirmLabel="Delete"
                    variant="danger"
                    confirmationText={deleteConfirmationName ?? undefined}
                    onConfirm={() => {
                        if (onDeleteCustom) {
                            onDeleteCustom(Array.from(selectedRows))
                            setDeleteConfirmOpen(false)
                            setSelectedRows(new Set())
                        } else {
                            setSelectedRows(new Set())
                            setDeleteConfirmOpen(false)
                        }
                    }}
                />
                <ConfirmDialog
                    open={exportConfirmOpen}
                    onClose={() => setExportConfirmOpen(false)}
                    title="Export Records"
                    message={`Records to export: ${exportConfirmCount.toLocaleString()}. Continue?`}
                    confirmLabel="Export"
                    cancelLabel="Cancel"
                    onConfirm={() => onExportCustom?.()}
                />
            </div>
        </ConfigProvider>
    )
}
