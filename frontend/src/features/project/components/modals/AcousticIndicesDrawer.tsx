import { Button as ESButton } from "@/components/ui"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Button, Checkbox, ConfigProvider, Input, InputNumber, Radio, Space, message } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { ArrowLeft, ExternalLink } from "lucide-react"

import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import {
    analysisApi,
    type AcousticIndexJob,
    type AcousticIndexParameter,
    type AcousticIndexSelection,
    type IndexType,
} from "../../../../api/endpoints/analysis"
import { indexLogsApi, type IndexLogCreateRequest } from "../../../../api/endpoints/indexLogs"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { isAbortError, pollAnalysisQueues, type AnalysisQueuePollSummary } from "./utils/analysisQueuePolling"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import { AnalysisResultModal, type AnalysisResultItem } from "./AnalysisResultModal"
import "./styles/AcousticIndicesDrawer.css"
import "./styles/RunAIModelsDrawer.css"

interface AnalysisCompletionSummary extends AnalysisQueuePollSummary {
    submissionFailedCount: number
}

interface AcousticIndexPreviewState {
    title: string
    items: AnalysisResultItem[]
    payloads: IndexLogCreateRequest[]
}

interface AcousticIndicesDrawerProps {
    open: boolean
    mediaId: number | null
    mediaIds?: number[]
    projectId: number | null
    selection?: AcousticIndexSelection | null
    channel?: "mono" | "left" | "right" | null
    onClose: () => void
    onSuccess?: () => void
    waitForCompletion?: boolean
    completionTitle?: string
    onCompleted?: (summary: AnalysisCompletionSummary) => void
    onProcessingChange?: (processing: boolean) => void
    embedded?: boolean
    selectionMode?: "single" | "multiple"
}

type ParamValue = string | number | boolean | null
type ParamState = Record<number, Record<string, ParamValue>>
type DirtyParamState = Record<number, Set<string>>

function parseDefaultValue(parameter: AcousticIndexParameter): ParamValue {
    if (parameter.default == null) return null
    if (parameter.value_type === "boolean") return Boolean(parameter.default)
    if (parameter.value_type === "number") {
        const parsed = Number(parameter.default)
        return Number.isFinite(parsed) ? parsed : null
    }
    return String(parameter.default)
}

function buildDefaults(indexTypes: IndexType[]): ParamState {
    const state: ParamState = {}
    indexTypes.forEach((indexType) => {
        const defaults: Record<string, ParamValue> = {}
        indexType.parameters.forEach((parameter) => {
            defaults[parameter.key] = parseDefaultValue(parameter)
        })
        state[indexType.index_id] = defaults
    })
    return state
}

function inferNumberStep(parameter: AcousticIndexParameter): number {
    const rawDefault = parameter.default == null ? "" : String(parameter.default)
    if (rawDefault.includes(".")) return 0.01
    return 1
}

function formatIndexTitle(name?: string | null): string {
    if (!name) return "Unnamed acoustic index"
    return name
        .split("_")
        .map((part) => part.toUpperCase() === part ? part : part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ")
}

function normalizeParamValue(value: ParamValue): string | number | boolean | null {
    if (typeof value === "string") {
        const trimmed = value.trim()
        return trimmed === "" ? null : trimmed
    }
    return value
}

function formatResultMessage(message?: string | null): string {
    if (!message) return "Saved"
    return message
        .split(",")
        .map((part) => {
            const separator = part.indexOf(":")
            if (separator < 0) return part.trim()
            const label = part.slice(0, separator).trim()
            const rawValue = part.slice(separator + 1).trim()
            const numericValue = Number(rawValue)
            if (!Number.isFinite(numericValue)) return part.trim()
            return `${label}: ${numericValue.toFixed(2)}`
        })
        .join(", ")
}

function formatResultValue(value: unknown): string {
    const numericValue = typeof value === "number" ? value : typeof value === "string" ? Number(value) : Number.NaN
    if (Number.isFinite(numericValue)) return numericValue.toFixed(2)
    return value == null ? "" : String(value)
}

export function AcousticIndicesDrawer({
    open,
    mediaId,
    mediaIds,
    projectId,
    selection,
    channel,
    onClose,
    onSuccess,
    waitForCompletion = false,
    completionTitle = "Analysis complete",
    onCompleted,
    onProcessingChange,
    embedded,
    selectionMode = "multiple",
}: AcousticIndicesDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const themeCfg = useAntdBrandConfig(isDark)
    const [submitting, setSubmitting] = useState(false)
    const [loading, setLoading] = useState(false)
    const [indexTypes, setIndexTypes] = useState<IndexType[]>([])
    const [selectedIds, setSelectedIds] = useState<number[]>([])
    const [paramState, setParamState] = useState<ParamState>({})
    const [dirtyParamState, setDirtyParamState] = useState<DirtyParamState>({})
    const [completionSummary, setCompletionSummary] = useState<AnalysisCompletionSummary | null>(null)
    const [previewState, setPreviewState] = useState<AcousticIndexPreviewState | null>(null)
    const [savingPreview, setSavingPreview] = useState(false)
    const pollAbortRef = useRef<AbortController | null>(null)
    const targetMediaIds = Array.from(
        new Set(
            (mediaIds?.length ? mediaIds : mediaId != null ? [mediaId] : [])
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        ),
    )
    const isBatch = targetMediaIds.length > 1
    const isDetailPreviewMode = Boolean(embedded && waitForCompletion && targetMediaIds.length === 1)

    const cancelPolling = useCallback(() => {
        pollAbortRef.current?.abort()
        pollAbortRef.current = null
        onProcessingChange?.(false)
    }, [onProcessingChange])

    const handleClose = () => {
        cancelPolling()
        onClose()
    }

    useEffect(() => {
        if (!open) {
            cancelPolling()
            setPreviewState(null)
            setSavingPreview(false)
            return
        }

        let cancelled = false
        setLoading(true)
        setSelectedIds([])

        analysisApi.getIndexTypes()
            .then((res) => {
                if (cancelled) return
                const items = Array.isArray(res.data) ? res.data : []
                setIndexTypes(items)
                setParamState(buildDefaults(items))
                setDirtyParamState({})
            })
            .catch(() => {
                if (cancelled) return
                setIndexTypes([])
                setParamState({})
                setDirtyParamState({})
                message.error("Failed to load acoustic index definitions")
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })

        return () => {
            cancelled = true
            cancelPolling()
        }
    }, [cancelPolling, open])

    const selectedJobs = useMemo<AcousticIndexJob[]>(() => {
        return selectedIds.map((indexId: number) => ({
            index_id: indexId,
            params: Object.fromEntries(
                (Object.entries(paramState[indexId] ?? {}) as Array<[string, ParamValue]>)
                    .filter(([key]) => dirtyParamState[indexId]?.has(key))
                    .map(([key, value]) => [key, normalizeParamValue(value)])
                    .filter(([, value]) => value !== null)
            ) as Record<string, string | number | boolean | null>,
        }))
    }, [dirtyParamState, paramState, selectedIds])

    const handleSelectIndex = (indexId: number) => {
        if (selectionMode === "single") {
            setSelectedIds([indexId])
            return
        }
        setSelectedIds((prev) =>
            prev.includes(indexId) ? prev.filter((id) => id !== indexId) : [...prev, indexId],
        )
    }

    const updateParam = (indexId: number, key: string, value: ParamValue) => {
        setParamState((prev: ParamState) => ({
            ...prev,
            [indexId]: {
                ...(prev[indexId] ?? {}),
                [key]: value,
            },
        }))
        setDirtyParamState((prev: DirtyParamState) => ({
            ...prev,
            [indexId]: new Set([...(prev[indexId] ?? new Set<string>()), key]),
        }))
    }

    const showCompletionModal = (summary: AnalysisCompletionSummary) => {
        setCompletionSummary(summary)
    }

    const closeCompletionModal = () => {
        if (!completionSummary) return
        const hasCompleted = completionSummary.completed.length > 0
        onCompleted?.(completionSummary)
        setCompletionSummary(null)
        if (hasCompleted) {
            onSuccess?.()
            onClose()
        }
    }

    const closePreviewModal = () => {
        if (savingPreview) return
        setPreviewState(null)
    }

    const savePreviewResults = async () => {
        if (!previewState || previewState.payloads.length === 0) return
        setSavingPreview(true)
        try {
            await Promise.all(previewState.payloads.map((payload) => indexLogsApi.create(payload)))
            message.success({
                content: "Acoustic index result saved",
                className: "acoustic-index-save-message",
            })
            setPreviewState(null)
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Failed to save acoustic index result")
        } finally {
            setSavingPreview(false)
        }
    }

    const completedIndexNames = selectedIds
        .map((indexId) => indexTypes.find((item) => item.index_id === indexId)?.name)
        .filter((name): name is string => Boolean(name))
        .map(formatIndexTitle)
    const completionItems: AnalysisResultItem[] = completionSummary
        ? [
            ...completionSummary.completed.map((status, index) => ({
                label: completedIndexNames[index] || status.type || `Index ${index + 1}`,
                value: formatResultMessage(status.message),
            })),
            ...completionSummary.failed.map((status, index) => ({
                label: completedIndexNames[completionSummary.completed.length + index] || status.type || `Index ${index + 1}`,
                value: status.error || status.message || "Failed",
            })),
        ]
        : []
    const selectionContext = selection
        ? `${channel === "right" ? "Right" : channel === "left" ? "Left" : "Mono"} · ${selection.min_time}-${selection.max_time}s · ${selection.min_frequency}-${selection.max_frequency}Hz`
        : undefined

    const handleSave = async () => {
        if (targetMediaIds.length === 0 || !projectId) return
        if (selectedJobs.length === 0) {
            message.warning("Please select at least one index to calculate")
            return
        }
        if (isDetailPreviewMode && !selection) {
            message.warning("Current spectrogram range is required")
            return
        }
        if (selection) {
            if (selection.max_time <= selection.min_time) {
                message.warning("Selection end time must be greater than start time")
                return
            }
            if (selection.max_frequency <= selection.min_frequency) {
                message.warning("Selection max frequency must be greater than min frequency")
                return
            }
        }

        setSubmitting(true)
        try {
            if (isDetailPreviewMode && selection) {
                const targetMediaId = targetMediaIds[0]
                if (targetMediaId == null) return
                onProcessingChange?.(true)
                const previewResponses = await Promise.all(
                    selectedJobs.map((job) => {
                        if (job.index_id == null) throw new Error("Invalid acoustic index selection")
                        return analysisApi.previewAcousticIndex({
                            project_id: projectId,
                            media_id: targetMediaId,
                            selection,
                            ...(channel ? { channel } : {}),
                            index_id: job.index_id,
                            params: job.params,
                        })
                    }),
                )
                const failedResponses = previewResponses.filter((res) => !isSuccessfulDrawerResponse(res.code, res.message) || !res.data)
                if (failedResponses.length > 0) {
                    message.error(failedResponses[0]?.message || "Failed to calculate acoustic index preview")
                    return
                }

                const payloads = previewResponses.map((res) => res.data.save_payload)
                const items = previewResponses.flatMap((res) =>
                    Object.entries(res.data.results ?? {}).map(([label, value]) => ({
                        label: `${formatIndexTitle(res.data.index_name)} · ${label}`,
                        value: formatResultValue(value),
                    })),
                )
                setPreviewState({
                    title: completionTitle,
                    items,
                    payloads,
                })
                return
            }

            const res = await analysisApi.runAcousticIndices({
                project_id: projectId,
                media_ids: targetMediaIds,
                ...(selection ? { selection } : {}),
                ...(channel ? { channel } : {}),
                indices: selectedJobs,
            })
            const failedResponses = !isSuccessfulDrawerResponse(res.code, res.message) ? [res] : []
            const failedJobs = Array.isArray(res.data?.failed) ? res.data.failed.length : 0
            const queueIds = Array.isArray(res.data?.queued) ? res.data.queued.map((queue) => queue.queue_id) : []

            if (failedResponses.length > 0 && queueIds.length === 0) {
                message.error(
                    isBatch
                        ? `${failedResponses.length} of ${targetMediaIds.length} items failed to submit`
                        : failedResponses[0]?.message || "Failed to submit calculation tasks",
                )
            } else if (!waitForCompletion) {
                if (failedResponses.length === 0 && failedJobs === 0) {
                    message.success("Job added to your queue - check status under corresponding tab")
                    onSuccess?.()
                    onClose()
                } else {
                    message.warning(`${failedResponses.length + failedJobs} index job(s) failed to submit`)
                }
            } else if (queueIds.length > 0) {
                cancelPolling()
                onProcessingChange?.(true)
                const controller = new AbortController()
                pollAbortRef.current = controller
                const pollSummary = await pollAnalysisQueues(queueIds, controller.signal)
                const summary: AnalysisCompletionSummary = {
                    ...pollSummary,
                    submissionFailedCount: failedResponses.length + failedJobs,
                }
                pollAbortRef.current = null
                onProcessingChange?.(false)
                showCompletionModal(summary)
            } else if (failedResponses.length > 0) {
                message.error(
                    isBatch
                        ? `${failedResponses.length} of ${targetMediaIds.length} items failed to submit`
                        : failedResponses[0]?.message || "Failed to submit calculation tasks",
                )
            } else {
                message.warning(`${failedJobs} index job(s) failed to submit`)
            }
        } catch (err) {
            if (!isAbortError(err)) {
                message.error(err instanceof Error ? err.message : "Failed to submit calculation tasks")
            }
        } finally {
            onProcessingChange?.(false)
            setSubmitting(false)
        }
    }

    const body = (
        <div className="acoustic-idx-container">
            <div className="acoustic-idx-gray-block">
                {loading ? (
                    <LoadingState label="Loading acoustic indices..." variant="inline" className="acoustic-idx-loading" />
                ) : indexTypes.length === 0 ? (
                    <EmptyState className="acoustic-idx-empty" title="No acoustic indices available." />
                ) : (
                    indexTypes.map((indexType: IndexType, index: number) => {
                        const selected = selectedIds.includes(indexType.index_id)
                        const values = paramState[indexType.index_id] ?? {}

                        return (
                            <div key={indexType.index_id}>
                                <div className="acoustic-idx-section">
                                    <div className="acoustic-idx-header">
                                        {selectionMode === "single" ? (
                                            <Radio checked={selected} onChange={() => handleSelectIndex(indexType.index_id)}>
                                                <span className="acoustic-idx-title">{formatIndexTitle(indexType.name)}</span>
                                            </Radio>
                                        ) : (
                                            <Checkbox checked={selected} onChange={() => handleSelectIndex(indexType.index_id)}>
                                                <span className="acoustic-idx-title">{formatIndexTitle(indexType.name)}</span>
                                            </Checkbox>
                                        )}
                                        {indexType.url ? (
                                            <a
                                                href={indexType.url}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="acoustic-idx-link ai-model-doc-link"
                                                title="Documentation"
                                            >
                                                <ExternalLink size={16} color="var(--brand)" />
                                            </a>
                                        ) : null}
                                    </div>

                                    {indexType.description ? (
                                        <div className="acoustic-idx-desc">{indexType.description}</div>
                                    ) : null}

                                    {selected ? (
                                        <div className="acoustic-idx-params">
                                            <div className="acoustic-idx-params-title">Parameters</div>
                                            {indexType.parameters.length === 0 ? (
                                                <div className="acoustic-idx-no-params">This index uses its backend defaults.</div>
                                            ) : (
                                                indexType.parameters.map((parameter: AcousticIndexParameter) => {
                                                    const value = values[parameter.key] ?? null
                                                    return (
                                                        <div className="acoustic-idx-param-row" key={parameter.key}>
                                                            <div className="acoustic-idx-param-meta">
                                                                <div className="acoustic-idx-param-label">{parameter.key}</div>
                                                                {parameter.default != null && parameter.default !== "" ? (
                                                                    <div className="acoustic-idx-param-sub">Default: {parameter.default}</div>
                                                                ) : null}
                                                            </div>

                                                            {parameter.value_type === "boolean" ? (
                                                                <Checkbox checked={Boolean(value)} onChange={(e: { target: { checked: boolean } }) => updateParam(indexType.index_id, parameter.key, e.target.checked)} />
                                                            ) : parameter.value_type === "number" ? (
                                                                <InputNumber
                                                                    className="acoustic-idx-param-input"
                                                                    value={typeof value === "number" ? value : null}
                                                                    step={inferNumberStep(parameter)}
                                                                    onChange={(next: string | number | null) => updateParam(indexType.index_id, parameter.key, typeof next === "number" ? next : next == null ? null : Number(next))}
                                                                />
                                                            ) : (
                                                                <Input
                                                                    className="acoustic-idx-param-text"
                                                                    value={value == null ? "" : String(value)}
                                                                    onChange={(e: { target: { value: string } }) => updateParam(indexType.index_id, parameter.key, e.target.value)}
                                                                />
                                                            )}
                                                        </div>
                                                    )
                                                })
                                            )}
                                        </div>
                                    ) : null}
                                </div>

                                {index < indexTypes.length - 1 ? <div className="acoustic-idx-divider" /> : null}
                            </div>
                        )
                    })
                )}
            </div>
        </div>
    )

    const actions = (
        <Space>
            <Button onClick={handleClose} className="acoustic-idx-btn-cancel">
                Cancel
            </Button>
            <Button
                type="primary"
                loading={submitting}
                onClick={handleSave}
                className="acoustic-idx-btn-save"
                style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
            >
                Run
            </Button>
        </Space>
    )
    const completionModal = (
        <AnalysisResultModal
            open={completionSummary !== null}
            title={completionTitle}
            context={selectionContext}
            items={completionItems}
            onClose={closeCompletionModal}
        />
    )
    const previewModal = (
        <AnalysisResultModal
            open={previewState !== null}
            title={previewState?.title ?? completionTitle}
            context={selectionContext}
            items={previewState?.items ?? []}
            onClose={closePreviewModal}
            onSave={savePreviewResults}
            saveLoading={savingPreview}
        />
    )

    if (embedded) {
        if (!open) return null
        return (
            <>
                <div className="studio-analysis-embed">
                    <div className="studio-analysis-embed-top">
                        <ESButton appearance="unstyled" type="button" className="header-back" title="Back" onClick={handleClose}>
                            <ArrowLeft size={18} strokeWidth={2.25} />
                        </ESButton>
                        <span className="header-title studio-analysis-embed-heading">{isBatch ? `Calculate Acoustic Indices (${targetMediaIds.length})` : "Calculate Acoustic Indices"}</span>
                    </div>
                    <div className="studio-analysis-embed-body">
                        <CustomScrollArea variant="fill" style={{ padding: "12px 14px" }}>
                            {body}
                        </CustomScrollArea>
                    </div>
                    <div className="studio-analysis-embed-foot">{actions}</div>
                </div>
                {completionModal}
                {previewModal}
            </>
        )
    }

    return (
        <ConfigProvider theme={themeCfg}>
            <>
                <FormDrawer
                    maskClosable={false}
                    closable={false}
                    title={<div style={{ fontWeight: 600, fontSize: 18, color: "var(--text-main)" }}>{isBatch ? `Calculate Acoustic Indices for ${targetMediaIds.length} Items` : "Calculate Acoustic Indices"}</div>}
                    placement="right"
                    open={open}
                    onClose={handleClose}
                    extra={actions}
                    styles={{
                        wrapper: { width: 480 },
                        body: { padding: 0, overflow: "hidden" },
                        header: { borderBottom: "none", padding: "24px 24px 0" },
                    }}
                >
                    <CustomScrollArea variant="fill" style={{ padding: "24px" }}>
                        {body}
                    </CustomScrollArea>
                </FormDrawer>
                {completionModal}
                {previewModal}
            </>
        </ConfigProvider>
    )
}
