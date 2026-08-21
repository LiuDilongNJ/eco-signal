import { Button as ESButton } from "@/components/ui"
import { useState, useEffect, useCallback, useMemo } from "react"

import { Button, Input, Select, message, Divider, Popover, Popconfirm, ConfigProvider, Space, Form } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { LoadingState } from "@/components/ui"

import { X } from "lucide-react"
import { collectionsApi } from "../../../../api/endpoints/collections"
import { usersApi } from "../../../../api/endpoints/users"
import type { TaxonPublic } from "../../../../api/endpoints/taxons"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import { isSelectScrollNearBottom } from "@/hooks/usePagedSelectOptions"
import { useTaxonSearchOptions } from "@/hooks/useTaxonSearchOptions"
import "./styles/FormDrawer.css"
import "./styles/SetTaxonsDrawer.css"

interface SetTaxonsDrawerProps {
    open: boolean
    collectionId: number | null
    projectId: number | null
    onClose?: () => void
    onSuccess?: () => void
    embedded?: boolean
    onDraftChange?: (taxons: CollectionTaxonDraft[]) => void
}

export interface CollectionTaxonDraft {
    col_taxon_id: string
    cached_name: string
    col_rank: string
    notes?: string
}

/** GET /v1/collections/{id}/taxons 单项 */
interface CollectionTaxonResponse {
    id: number
    collection_id: number
    col_taxon_id: string
    col_rank: string
    cached_name?: string | null
    asserted_by?: number | null
    asserted_by_name?: string | null
    asserted_at?: string | null
    notes?: string | null
}

interface SelectedTaxon extends CollectionTaxonDraft {
    /** Persisted row id from API; unset for rows added before save */
    rowId?: number
    col_taxon_id: string
    cached_name: string
    col_rank: string
    notes?: string
    asserted_by?: number | null
    asserted_by_name?: string | null
    asserted_at?: string | null
}

/** Stable ID for collection_taxon row: COL species id when present, else internal dictionary id. */
function colTaxonIdFromPublic(t: TaxonPublic): string {
    const col = t.col_species_id?.trim()
    if (col) return col
    return `taxon:${t.taxon_id}`
}

function displayNameFromPublic(t: TaxonPublic): string {
    return (
        t.cached_scientific_name?.trim() ||
        t.cached_common_name?.trim() ||
        `Taxon #${t.taxon_id}`
    )
}

const taxonIdToString = (taxonId: number) => String(taxonId)

function formatRankTitle(rank: string): string {
    const r = rank.trim()
    if (!r) return "Taxon"
    return r.charAt(0).toUpperCase() + r.slice(1).toLowerCase()
}

/** Formats the local audit timestamp the same way as the collection API response. */
export function formatAuditTimestamp(date = new Date()): string {
    const pad = (value: number) => String(value).padStart(2, "0")
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function pendingTaxonAudit(userName: string, date = new Date()) {
    return {
        asserted_by: null,
        asserted_by_name: userName.trim() || "Current user",
        asserted_at: formatAuditTimestamp(date),
    }
}

function TaxonTagPopoverBody({ item }: { item: SelectedTaxon }) {
    const by = item.asserted_by_name?.trim() || "-"
    const at = item.asserted_at?.trim() || "-"
    const notesText = item.notes?.trim() || "-"

    return (
        <div className="set-taxons-tag-popover-inner">
            <div className="set-taxons-tag-popover-rank">{formatRankTitle(item.col_rank)}</div>
            <div className="set-taxons-tag-popover-row">
                <span className="set-taxons-tag-popover-label">BY:</span>
                <span className="set-taxons-tag-popover-value">{by}</span>
            </div>
            <div className="set-taxons-tag-popover-row">
                <span className="set-taxons-tag-popover-label">AT:</span>
                <span className="set-taxons-tag-popover-value">{at}</span>
            </div>
            <div className="set-taxons-tag-popover-row">
                <span className="set-taxons-tag-popover-label">Notes:</span>
                <span className="set-taxons-tag-popover-value">{notesText}</span>
            </div>
        </div>
    )
}

function toDrafts(items: SelectedTaxon[]): CollectionTaxonDraft[] {
    return items.map(({ col_taxon_id, cached_name, col_rank, notes }) => ({
        col_taxon_id,
        cached_name,
        col_rank,
        notes,
    }))
}

export function SetTaxonsDrawer({
    open,
    collectionId,
    projectId,
    onClose,
    onSuccess,
    embedded = false,
    onDraftChange,
}: SetTaxonsDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [currentUserName, setCurrentUserName] = useState("Current user")

    const [selectedTaxonId, setSelectedTaxonId] = useState<string | null>(null)
    const [selectedTaxonData, setSelectedTaxonData] = useState<TaxonPublic | null>(null)
    const [notes, setNotes] = useState("")
    const taxonSearch = useTaxonSearchOptions<string>({ toValue: taxonIdToString })

    const [selectedList, setSelectedList] = useState<SelectedTaxon[]>([])

    useEffect(() => {
        if (!open || !projectId) {
            setCurrentUserName("Current user")
            return
        }

        let cancelled = false
        ;(async () => {
            try {
                const res = await usersApi.getMe({ ignoreUnauthorized: true, project_id: projectId })
                if (cancelled || !(res.code === 0 || res.code === 200) || !res.data) return
                const name = res.data.name?.trim() || res.data.username?.trim()
                if (name) setCurrentUserName(name)
            } catch (error) {
                console.error("Failed to fetch current user for taxon audit:", error)
            }
        })()

        return () => {
            cancelled = true
        }
    }, [open, projectId])

    useEffect(() => {
        if (!currentUserName || currentUserName === "Current user") return
        setSelectedList((prev) => {
            let changed = false
            const next = prev.map((item) => {
                if (item.rowId != null || item.asserted_by_name !== "Current user") return item
                changed = true
                return { ...item, asserted_by_name: currentUserName }
            })
            return changed ? next : prev
        })
    }, [currentUserName])

    const selectedColIdSet = useMemo(
        () => new Set(selectedList.map((i) => i.col_taxon_id.trim())),
        [selectedList],
    )

    const selectOptionsFiltered = useMemo(
        () =>
            taxonSearch.options.filter((o) => !selectedColIdSet.has(colTaxonIdFromPublic(o.taxon).trim())),
        [taxonSearch.options, selectedColIdSet],
    )

    const fetchExistingTaxons = useCallback(async () => {
        if (!collectionId || !projectId) return
        setLoading(true)
        try {
            const res = await collectionsApi.getCollectionTaxons(collectionId, projectId)
            if (res.code === 0 || res.code === 200) {
                const rows = (res.data ?? []) as CollectionTaxonResponse[]
                const seen = new Set<string>()
                const existing: SelectedTaxon[] = []
                for (const t of rows) {
                    const key = String(t.col_taxon_id ?? "").trim()
                    if (!key || seen.has(key)) continue
                    seen.add(key)
                    existing.push({
                        rowId: t.id,
                        col_taxon_id: key,
                        cached_name: (t.cached_name ?? "").trim() || key,
                        col_rank: t.col_rank || "species",
                        notes: t.notes ?? undefined,
                        asserted_by: t.asserted_by ?? null,
                        asserted_by_name: t.asserted_by_name?.trim() || null,
                        asserted_at: t.asserted_at != null ? String(t.asserted_at) : null,
                    })
                }
                setSelectedList(existing)
                onDraftChange?.(toDrafts(existing))
            }
        } catch (error) {
            console.error("Failed to fetch taxons:", error)
            message.error("Failed to load collection taxa")
        } finally {
            setLoading(false)
        }
    }, [collectionId, projectId, onDraftChange])

    useEffect(() => {
        if (open && collectionId && projectId) {
            void fetchExistingTaxons()
        } else if (!open) {
            setSelectedList([])
            onDraftChange?.([])
            setSelectedTaxonId(null)
            setSelectedTaxonData(null)
            setNotes("")
            taxonSearch.reset()
        }
        // Pagination state methods are stable and drawer identity defines a reset.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, collectionId, projectId, fetchExistingTaxons, onDraftChange])

    const handleSelectTaxon = (val: string | null) => {
        setSelectedTaxonId(val)
        if (val == null || val === "") {
            setSelectedTaxonData(null)
            taxonSearch.setCurrentOption(null)
            return
        }
        const opt = taxonSearch.options.find((o) => o.value === val)
        setSelectedTaxonData(opt?.taxon ?? null)
        taxonSearch.setCurrentOption(opt ?? null)
    }

    const handleAdd = () => {
        if (!selectedTaxonData) {
            message.warning("Please select a taxon first")
            return
        }

        const colId = colTaxonIdFromPublic(selectedTaxonData).trim()
        if (selectedColIdSet.has(colId)) {
            message.warning("This taxon is already in the list")
            return
        }

        const newItem: SelectedTaxon = {
            col_taxon_id: colId,
            cached_name: displayNameFromPublic(selectedTaxonData),
            col_rank: "species",
            notes: notes.trim() || undefined,
            ...pendingTaxonAudit(currentUserName),
        }

        setSelectedList((prev) => {
            const next = [...prev, newItem]
            onDraftChange?.(toDrafts(next))
            return next
        })

        setSelectedTaxonId(null)
        setSelectedTaxonData(null)
        taxonSearch.setCurrentOption(null)
        setNotes("")
    }

    const handleRemove = (id: string) => {
        setSelectedList((prev) => {
            const next = prev.filter((item) => item.col_taxon_id !== id)
            onDraftChange?.(toDrafts(next))
            return next
        })
    }

    const handleSave = async () => {
        if (!collectionId || !projectId) return
        setSaving(true)
        try {
            const taxons = selectedList.map(
                ({ col_taxon_id, cached_name, col_rank, notes: n }) => ({
                    col_taxon_id,
                    cached_name,
                    col_rank,
                    notes: n,
                }),
            )
            const res = await collectionsApi.setCollectionTaxons(collectionId, projectId, { taxons })
            if (isSuccessfulDrawerResponse(res.code, res.message)) {
                message.success("Taxa updated successfully")
                onSuccess?.()
                onClose?.()
            } else {
                message.error(res.message || "Failed to update taxa")
            }
        } catch (error: unknown) {
            message.error(error instanceof Error ? error.message : "An error occurred during save")
        } finally {
            setSaving(false)
        }
    }

    const editorContent = (
        <div className="set-taxons-content shared-drawer-form" style={{ padding: embedded ? undefined : "24px" }}>
            <Form layout="vertical" component="div">
                <Form.Item label={embedded ? undefined : "Taxa"}>
                    <Select
                        showSearch
                        allowClear
                        value={selectedTaxonId}
                        defaultActiveFirstOption={false}
                        showArrow={false}
                        filterOption={false}
                        onSearch={taxonSearch.search}
                        onPopupScroll={(event) => {
                            if (isSelectScrollNearBottom(event.currentTarget)) {
                                taxonSearch.loadNext()
                            }
                        }}
                        onChange={handleSelectTaxon}
                        notFoundContent={
                            taxonSearch.loading ? (
                                <LoadingState label="Loading taxon..." variant="inline" size="sm" showLabel={false} />
                            ) : (
                                <EmptyState
                                    className="set-taxons-select-empty"
                                    title={taxonSearch.query ? "No taxon found" : "Type a taxon name to search"}
                                />
                            )
                        }
                        options={selectOptionsFiltered}
                        loading={taxonSearch.loading}
                        popupRender={(menu) => (
                            <>
                                {menu}
                                {taxonSearch.loading ? (
                                    <LoadingState
                                        label="Loading taxon..."
                                        variant="inline"
                                        size="sm"
                                        showLabel={false}
                                    />
                                ) : null}
                            </>
                        )}
                        style={{ width: "100%" }}
                        className="custom-select set-taxons-select"
                        classNames={{ popup: { root: "eco-select-popup set-taxons-select-dropdown" } }}
                    />
                </Form.Item>

                <Form.Item label="Notes">
                    <Input
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                        className="set-taxons-input"
                    />
                </Form.Item>
            </Form>

            <div className="set-taxons-toolbar">
                <Button type="primary" onClick={handleAdd} className="set-taxons-btn-add">
                    Add
                </Button>
            </div>

            <Divider className="set-taxons-divider" />

            <div className="set-taxons-tags-container">
                {selectedList.map((item) => (
                    <div
                        className="set-taxons-tag-pill"
                        key={item.rowId ?? `new-${item.col_taxon_id}`}
                    >
                        <Popover
                            trigger={["hover"]}
                            placement="bottom"
                            mouseEnterDelay={0.15}
                            mouseLeaveDelay={0.1}
                            overlayClassName="set-taxons-tag-popover"
                            content={<TaxonTagPopoverBody item={item} />}
                        >
                            <span className="set-taxons-tag-name">{item.cached_name}</span>
                        </Popover>
                        <Popconfirm
                            title="Remove this taxon?"
                            description="It will be removed from the list. Save to persist changes."
                            okText="Remove"
                            cancelText="Cancel"
                            okButtonProps={{ danger: true }}
                            onConfirm={() => handleRemove(item.col_taxon_id)}
                        >
                            <ESButton appearance="unstyled"
                                type="button"
                                className="set-taxons-tag-remove"
                                aria-label="Remove taxon"
                            >
                                <X size={14} />
                            </ESButton>
                        </Popconfirm>
                    </div>
                ))}
                {selectedList.length === 0 && !loading && (
                    <EmptyState className="set-taxons-empty" title="No taxa added yet" />
                )}
                {loading && (
                    <LoadingState
                        label="Loading existing taxa..."
                        variant="inline"
                        size="sm"
                        className="set-taxons-loading-text"
                    />
                )}
            </div>
        </div>
    )

    if (embedded) {
        return editorContent
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={<span className="set-taxons-title">Set Taxa</span>}
                placement="right"
                onClose={onClose}
                open={open}
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={saving}>
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            loading={saving}
                            onClick={() => void handleSave()}
                            className="set-taxons-btn-save"
                        >
                            Save
                        </Button>
                    </Space>
                }
                styles={{
                    wrapper: {
                        width: 480,
                    },
                    header: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                        borderBottomColor: isDark ? "var(--border-color)" : undefined,
                        color: "var(--text-main)",
                    },
                    body: {
                        backgroundColor: isDark ? "var(--bg-surface)" : "var(--card-bg)",
                        padding: 0,
                        overflow: "hidden",
                    },
                    footer: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                    },
                    mask: {
                        backdropFilter: "blur(4px)",
                    },
                }}
            >
                <CustomScrollArea variant="fill">{editorContent}</CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
