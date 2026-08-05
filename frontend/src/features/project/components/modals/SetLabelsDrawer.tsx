import { useCallback, useEffect, useState } from "react"
import { Button, Input, message, ConfigProvider, Divider, Popconfirm, Space } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { X } from "lucide-react"
import { CustomScrollArea } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { labelsApi, fetchLabelsCatalog, type LabelPublic } from "../../../../api/endpoints/labels"
import { mediaApi } from "../../../../api/endpoints/media"
import "./styles/SetLabelsDrawer.css"

interface SetLabelsDrawerProps {
    open: boolean
    mediaId: number | null
    mediaIds?: number[]
    projectId: number | null
    onClose: () => void
    onSuccess?: () => void
}

export function SetLabelsDrawer({ open, mediaId, mediaIds, projectId, onClose, onSuccess }: SetLabelsDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const themeCfg = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [allLabels, setAllLabels] = useState<LabelPublic[]>([])
    const [selectedId, setSelectedId] = useState<number | null>(null)
    const [newLabelName, setNewLabelName] = useState("")
    const [addingLabel, setAddingLabel] = useState(false)
    const [deletingId, setDeletingId] = useState<number | null>(null)
    const targetMediaIds = Array.from(
        new Set(
            (mediaIds?.length ? mediaIds : mediaId != null ? [mediaId] : [])
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        ),
    )
    const primaryMediaId = targetMediaIds[0] ?? null
    const isBatch = targetMediaIds.length > 1

    const loadCatalogAndSelection = useCallback(async () => {
        if (!primaryMediaId || !projectId) return
        const all = await fetchLabelsCatalog()
        setAllLabels(all)
        const mediaRes = await mediaApi.getMediaDetail(primaryMediaId, projectId)
        const rawNames = mediaRes.data?.labels
        const mediaLabelsNames = Array.isArray(rawNames)
            ? rawNames.filter((n): n is string => typeof n === "string" && n.trim() !== "")
            : []
        const firstMatched = mediaLabelsNames
            .map((name) => all.find((label) => label.name === name))
            .find(Boolean)
        setSelectedId(firstMatched?.label_id ?? null)
    }, [primaryMediaId, projectId])

    useEffect(() => {
        if (!open || !primaryMediaId) return
        let cancelled = false
        ;(async () => {
            setLoading(true)
            try {
                await loadCatalogAndSelection()
            } catch (error) {
                console.error(error)
                if (!cancelled) message.error("Failed to fetch labels data")
            } finally {
                if (!cancelled) setLoading(false)
            }
        })()
        return () => {
            cancelled = true
        }
    }, [open, primaryMediaId, loadCatalogAndSelection])

    const handleAdd = async () => {
        const name = newLabelName.trim()
        if (!name) return
        
        const exists = allLabels.find((l) => l.name.toLowerCase() === name.toLowerCase())
        if (exists) {
            setSelectedId(exists.label_id)
            setNewLabelName("")
            return
        }

        setAddingLabel(true)
        try {
            const res = await labelsApi.createLabel(name)
            if (res.code === 0 || res.code === 200) {
                /** 后端创建成功常返回 data: null，需重新 GET 列表再选中新建项 */
                try {
                    const all = await fetchLabelsCatalog()
                    setAllLabels(all)
                    const key = name.toLowerCase()
                    const match = all.find((l) => l.name.toLowerCase() === key)
                    setNewLabelName("")
                    if (match) {
                        setSelectedId(match.label_id)
                        message.success("Label added")
                    } else {
                        message.success("Label created")
                    }
                } catch (refreshErr) {
                    console.error(refreshErr)
                    message.error("Label created but failed to refresh the list")
                }
            } else {
                message.error(res.message || "Failed to create label")
            }
        } catch (err: any) {
            console.error("Failed to create label API error", err)
            message.error("Failed to create label")
        } finally {
            setAddingLabel(false)
        }
    }

    const handleSave = async () => {
        if (targetMediaIds.length === 0 || !projectId) return
        setSaving(true)
        try {
            const res = await labelsApi.setMediaLabels(targetMediaIds, projectId, selectedId)
            const failed = Array.isArray(res.data?.failed) ? res.data.failed : []
            if (failed.length === 0) {
                message.success(
                    isBatch
                        ? `Labels updated for ${targetMediaIds.length} items`
                        : "Labels updated successfully",
                )
                if (onSuccess) onSuccess()
                onClose()
            } else {
                message.error(
                    isBatch
                        ? `${failed.length} of ${targetMediaIds.length} items failed to update`
                        : failed[0]?.message || "Failed to update labels",
                )
            }
        } catch (err) {
            message.error("Failed to update labels")
        } finally {
            setSaving(false)
        }
    }

    const toggleLabel = (id: number) => {
        setSelectedId((prev) => (prev === id ? null : id))
    }

    const handleDeleteLabel = async (labelId: number) => {
        if (deletingId != null || !primaryMediaId) return
        setDeletingId(labelId)
        try {
            const res = await labelsApi.deleteLabel(labelId)
            if (res.code != null && res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to delete label")
                return
            }
            message.success("Label deleted")
            await loadCatalogAndSelection()
            onSuccess?.()
        } catch (e: unknown) {
            console.error(e)
            message.error("Failed to delete label")
        } finally {
            setDeletingId(null)
        }
    }

    // System labels have IDs 1, 2, 3 OR no creator_id
    const isSystemLabel = (l: LabelPublic) =>
        typeof l.label_id === "number" && (l.label_id <= 3 || l.creator_id == null)

    const tagActionBusy = saving || addingLabel || deletingId != null

    return (
        <ConfigProvider theme={themeCfg}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={<div style={{ fontWeight: 600, fontSize: 18, color: "var(--text-main)" }}>{isBatch ? `Set Labels for ${targetMediaIds.length} Items` : "Set Labels"}</div>}
                placement="right"
                open={open}
                onClose={onClose}
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={saving}>
                            Cancel
                        </Button>
                        <Button 
                            type="primary" 
                            loading={saving} 
                            onClick={handleSave}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            Save
                        </Button>
                    </Space>
                }
                styles={{
                    wrapper: { width: 480 },
                    body: { padding: 0, overflow: "hidden" },
                    header: { borderBottom: "none", padding: "24px 24px 0" },
                }}
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: "24px" }}>
                        {loading ? (
                            <LoadingState label="Loading labels..." variant="inline" />
                        ) : (
                            <div className="set-labels-content">
                                <div className="set-labels-form">
                                    <div className="set-labels-label">New Label</div>
                                    <Input 
                                        value={newLabelName}
                                        onChange={e => setNewLabelName(e.target.value)}
                                        onPressEnter={() => void handleAdd()}
                                        className="set-labels-input"
                                    />
                                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
                                        <Button
                                            type="primary"
                                            loading={addingLabel}
                                            onClick={() => void handleAdd()}
                                            className="set-labels-btn-add"
                                        >
                                            Add
                                        </Button>
                                    </div>
                                </div>

                                <Divider style={{ margin: "24px 0", borderColor: "var(--border-color)" }} />

                                <div className="set-labels-tags">
                                    {allLabels.map((l) => {
                                        const selected = selectedId === l.label_id
                                        const system = isSystemLabel(l)
                                        return (
                                            <div 
                                                key={l.label_id} 
                                                className={`set-labels-tag ${selected ? 'selected' : ''}`}
                                                onClick={() => toggleLabel(l.label_id)}
                                            >
                                                <span>{l.name}</span>
                                                {!system && (
                                                    <Popconfirm
                                                        title="Delete this label?"
                                                        description="Recordings that used it may no longer show this tag."
                                                        okText="Delete"
                                                        cancelText="Cancel"
                                                        okButtonProps={{
                                                            danger: true,
                                                            loading: deletingId === l.label_id,
                                                        }}
                                                        disabled={tagActionBusy}
                                                        onConfirm={() => void handleDeleteLabel(l.label_id)}
                                                    >
                                                        <span
                                                            className="set-labels-tag-close"
                                                            role="button"
                                                            tabIndex={0}
                                                            aria-label={`Delete ${l.name}`}
                                                            onClick={(e) => e.stopPropagation()}
                                                            onKeyDown={(e) => {
                                                                if (e.key !== "Enter" && e.key !== " ") return
                                                                e.preventDefault()
                                                                e.stopPropagation()
                                                            }}
                                                        >
                                                            <X size={14} />
                                                        </span>
                                                    </Popconfirm>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
