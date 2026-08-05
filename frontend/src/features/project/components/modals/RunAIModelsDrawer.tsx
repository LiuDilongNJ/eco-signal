import { Button as ESButton } from "@/components/ui"
import { useCallback, useEffect, useRef, useState } from "react"
import { Button, Checkbox, InputNumber, Radio, Select, message, ConfigProvider, Divider, Space, Modal } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { ArrowLeft, ExternalLink } from "lucide-react"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { analysisApi, type BirdNETLocale } from "../../../../api/endpoints/analysis"
import type { QueueDetail } from "../../../../api/endpoints/queue"
import { isAbortError, pollAnalysisQueues, type AnalysisQueuePollSummary } from "./utils/analysisQueuePolling"
import { buildRunAnalysisPayload } from "./utils/analysisPayload"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import "./styles/RunAIModelsDrawer.css"

interface AnalysisCompletionSummary extends AnalysisQueuePollSummary {
    submissionFailedCount: number
}

type CompletionTone = "success" | "warning" | "error"

const AI_MODEL_DOC_URLS = {
    birdnet: "https://github.com/kahst/BirdNET-Analyzer",
    batdetect: "https://github.com/macaodha/batdetect2",
    insects: "https://huggingface.co/AlexanderGbd/insects-base-cnn10-96k-t",
} as const

interface RunAIModelsDrawerProps {
    open: boolean
    mediaId: number | null
    mediaIds?: number[]
    projectId: number | null
    onClose: () => void
    onSuccess?: () => void
    waitForCompletion?: boolean
    completionTitle?: string
    onCompleted?: (summary: AnalysisCompletionSummary) => void
    onProcessingChange?: (processing: boolean) => void
    /** Render inside a column (e.g. audio studio right panel) instead of antd Drawer */
    embedded?: boolean
    selectionMode?: "single" | "multiple"
}

function firstQueueError(failed: QueueDetail[]): string | null {
    const failedWithMessage = failed.find((status) => status.error || status.message)
    return failedWithMessage?.error || failedWithMessage?.message || null
}

function queueCompletionText(status: QueueDetail): string {
    return status.message || "Analysis finished. Annotations have been updated."
}

function queueFailureText(status: QueueDetail): string {
    return status.error || status.message || "Analysis failed. Please check the queue for details."
}

export function RunAIModelsDrawer({
    open,
    mediaId,
    mediaIds,
    projectId,
    onClose,
    onSuccess,
    waitForCompletion = false,
    completionTitle = "Analysis complete",
    onCompleted,
    onProcessingChange,
    embedded,
    selectionMode = "multiple",
}: RunAIModelsDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const themeCfg = useAntdBrandConfig(isDark)
    const [submitting, setSubmitting] = useState(false)
    const [completionSummary, setCompletionSummary] = useState<AnalysisCompletionSummary | null>(null)
    const pollAbortRef = useRef<AbortController | null>(null)

    // Checkbox states
    const [enableBirdNet, setEnableBirdNet] = useState(false)
    const [enableBatDetect, setEnableBatDetect] = useState(false)
    const [enableInsects, setEnableInsects] = useState(false)
    const [enableMerge, setEnableMerge] = useState(false)

    // BirdNET params
    const [birdConf, setBirdConf] = useState<number | null>(0.1)
    const [birdOverlap, setBirdOverlap] = useState<number | null>(0)
    const [birdSens, setBirdSens] = useState<number | null>(1)
    const [birdSfThresh, setBirdSfThresh] = useState<number | null>(0.03)
    const [birdLocale, setBirdLocale] = useState<BirdNETLocale>("en_us")
    const [birdTopN, setBirdTopN] = useState<number | null>(null)

    // BatDetect params
    const [batThresh, setBatThresh] = useState<number | null>(0.3)
    const [batChunk, setBatChunk] = useState<number | null>(2)

    // Insects params
    const [insectsWindow, setInsectsWindow] = useState<number | null>(4)
    const [insectsStrideLength, setInsectsStrideLength] = useState<number | null>(4)

    // Merge params
    const [mergeDuration, setMergeDuration] = useState<number | null>(0)
    const [mergeKeepOnly, setMergeKeepOnly] = useState(false)
    const targetMediaIds = Array.from(
        new Set(
            (mediaIds?.length ? mediaIds : mediaId != null ? [mediaId] : [])
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        ),
    )
    const isBatch = targetMediaIds.length > 1

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
        if (open) {
            // Reset to defaults when opened
            setEnableBirdNet(false)
            setEnableBatDetect(false)
            setEnableInsects(false)
            setEnableMerge(false)
            setBirdConf(0.1)
            setBirdOverlap(0)
            setBirdSens(1)
            setBirdSfThresh(0.03)
            setBirdLocale("en_us")
            setBirdTopN(null)
            setBatThresh(0.3)
            setBatChunk(2)
            setInsectsWindow(4)
            setInsectsStrideLength(4)
            setMergeDuration(0)
            setMergeKeepOnly(false)
        } else {
            cancelPolling()
        }
        return () => {
            cancelPolling()
        }
    }, [cancelPolling, open])

    const showCompletionModal = (summary: AnalysisCompletionSummary) => {
        setCompletionSummary(summary)
    }

    const completionCounts = completionSummary
        ? {
            completed: completionSummary.completed.length,
            failed: completionSummary.failed.length + completionSummary.submissionFailedCount,
        }
        : { completed: 0, failed: 0 }

    const completionTone: CompletionTone =
        completionCounts.failed === 0 ? "success" : completionCounts.completed > 0 ? "warning" : "error"

    const completionModalTitle =
        completionTone === "success"
            ? completionTitle
            : completionTone === "warning"
                ? "Analysis finished with errors"
                : "Analysis failed"

    const handleCompletionModalOk = () => {
        if (!completionSummary) return

        const hasCompleted = completionSummary.completed.length > 0
        onCompleted?.(completionSummary)
        setCompletionSummary(null)

        if (hasCompleted) {
            onSuccess?.()
            onClose()
        }
    }

    const selectAiModel = (model: "birdnet" | "batdetect" | "insects") => {
        if (selectionMode === "single") {
            setEnableBirdNet(model === "birdnet")
            setEnableBatDetect(model === "batdetect")
            setEnableInsects(model === "insects")
            return
        }
        if (model === "birdnet") setEnableBirdNet((enabled) => !enabled)
        if (model === "batdetect") setEnableBatDetect((enabled) => !enabled)
        if (model === "insects") setEnableInsects((enabled) => !enabled)
    }

    const handleSave = async () => {
        if (targetMediaIds.length === 0 || !projectId) return

        if (!enableBirdNet && !enableBatDetect && !enableInsects) {
            message.warning("Please select at least one AI model to run")
            return
        }

        setSubmitting(true)
        try {
            const payload = buildRunAnalysisPayload({
                projectId,
                mediaIds: targetMediaIds,
                birdnet: {
                    enabled: enableBirdNet,
                    minConf: birdConf,
                    overlap: birdOverlap,
                    sensitivity: birdSens,
                    sfThresh: birdSfThresh,
                    locale: birdLocale,
                    topN: birdTopN,
                },
                batdetect: {
                    enabled: enableBatDetect,
                    threshold: batThresh,
                    chunkSize: batChunk,
                },
                insects: {
                    enabled: enableInsects,
                    windowSize: insectsWindow,
                    strideLength: insectsStrideLength,
                },
                merge: {
                    enabled: enableMerge,
                    maxGap: mergeDuration,
                    keepMerged: mergeKeepOnly,
                },
            })

            const res = await analysisApi.runAnalysis(payload)
            const failedResponses = !isSuccessfulDrawerResponse(res.code, res.message) ? [res] : []
            const failedJobs = Array.isArray(res.data?.failed) ? res.data.failed.length : 0
            const queueIds = Array.isArray(res.data?.queued) ? res.data.queued.map((queue) => queue.queue_id) : []

            if (failedResponses.length > 0 && queueIds.length === 0) {
                message.error(
                    isBatch
                        ? `${failedResponses.length} of ${targetMediaIds.length} items failed to submit`
                        : failedResponses[0]?.message || "Failed to submit analysis tasks",
                )
            } else if (!waitForCompletion) {
                if (failedResponses.length === 0 && failedJobs === 0) {
                    message.success("Job added to your queue - check status under corresponding tab")
                    onSuccess?.()
                    onClose()
                } else {
                    message.warning(`${failedResponses.length + failedJobs} analysis job(s) failed to submit`)
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
            } else {
                message.error("Failed to submit analysis tasks")
            }
        } catch (err) {
            if (!isAbortError(err)) {
                message.error(err instanceof Error ? err.message : "Failed to submit analysis tasks")
            }
        } finally {
            onProcessingChange?.(false)
            setSubmitting(false)
        }
    }

    const birdLocales: BirdNETLocale[] = [
        "af", "ar", "cs", "da", "de", "en_uk", "en_us", "es", "fi", "fr", "hu", "it", "ja", "ko", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "th", "tr", "uk", "zh"
    ]
    const birdLocaleOptions = birdLocales.map(value => ({ value, label: value }))

    const body = (
        <div className="ai-models-container">
            <div className="ai-models-gray-block">
                {/* BirdNET Section */}
                <div className="ai-model-section">
                    <div className="ai-model-header">
                        {selectionMode === "single" ? (
                            <Radio checked={enableBirdNet} onChange={() => selectAiModel("birdnet")}>
                                <span className="ai-model-title">BirdNET</span>
                            </Radio>
                        ) : (
                            <Checkbox checked={enableBirdNet} onChange={() => selectAiModel("birdnet")}>
                                <span className="ai-model-title">BirdNET</span>
                            </Checkbox>
                        )}
                        <a
                            href={AI_MODEL_DOC_URLS.birdnet}
                            target="_blank"
                            rel="noreferrer"
                            className="ai-model-doc-link"
                            title="BirdNET documentation"
                        >
                            <ExternalLink size={16} color="var(--brand)" />
                        </a>
                    </div>
                    <div className="ai-model-desc">
                        Automated scientific audio data processing and bird ID.
                    </div>

                    {enableBirdNet && (
                        <div className="ai-model-params">
                            <div className="ai-model-params-title">Parameters:</div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    sensitivity <span className="ai-model-param-sub">(Values in [0.5, 1.5]. Defaults to 1.0.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0.5} max={1.5} step={0.1} value={birdSens} onChange={setBirdSens} />
                            </div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    min_conf <span className="ai-model-param-sub">(Values in [0.01, 0.99]. Defaults to 0.1.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0.01} max={0.99} step={0.01} value={birdConf} onChange={setBirdConf} />
                            </div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    overlap <span className="ai-model-param-sub">(Values in [0.0, 2.9]. Defaults to 0.0.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0} max={2.9} step={0.1} value={birdOverlap} onChange={setBirdOverlap} />
                            </div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    sf_thresh <span className="ai-model-param-sub">(values in [0.01, 0.99]. Defaults to 0.03.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0.01} max={0.99} step={0.01} value={birdSfThresh} onChange={setBirdSfThresh} />
                            </div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    locale <span className="ai-model-param-sub">(Common names)</span>
                                </div>
                                <Select
                                    value={birdLocale}
                                    onChange={setBirdLocale}
                                    className="ai-model-param-select"
                                    options={birdLocaleOptions}
                                />
                            </div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    top_n <span className="ai-model-param-sub">(Ignores confidence)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={1} max={10000} value={birdTopN} onChange={setBirdTopN} />
                            </div>
                        </div>
                    )}
                </div>

                <div className="ai-model-divider" />

                {/* BatDetect Section */}
                <div className="ai-model-section">
                    <div className="ai-model-header">
                        {selectionMode === "single" ? (
                            <Radio checked={enableBatDetect} onChange={() => selectAiModel("batdetect")}>
                                <span className="ai-model-title">BatDetect</span>
                            </Radio>
                        ) : (
                            <Checkbox checked={enableBatDetect} onChange={() => selectAiModel("batdetect")}>
                                <span className="ai-model-title">BatDetect</span>
                            </Checkbox>
                        )}
                        <a
                            href={AI_MODEL_DOC_URLS.batdetect}
                            target="_blank"
                            rel="noreferrer"
                            className="ai-model-doc-link"
                            title="BatDetect2 documentation"
                        >
                            <ExternalLink size={16} color="var(--brand)" />
                        </a>
                    </div>
                    <div className="ai-model-desc">
                        Code for detecting and classifying bat echolocation calls in high frequency audio recordings.
                    </div>

                    {enableBatDetect && (
                        <div className="ai-model-params">
                            <div className="ai-model-params-title">Parameters:</div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    detection_threshold <span className="ai-model-param-sub">(Values in [0, 1.0]. Defaults to 0.3.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0} max={1} step={0.1} value={batThresh} onChange={setBatThresh} />
                            </div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    chunk_size <span className="ai-model-param-sub">(Defaults to 2.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0.1} step={0.1} value={batChunk} onChange={setBatChunk} />
                            </div>

                        </div>
                    )}
                </div>

                <div className="ai-model-divider" />

                {/* Insects Section */}
                <div className="ai-model-section">
                    <div className="ai-model-header">
                        {selectionMode === "single" ? (
                            <Radio checked={enableInsects} onChange={() => selectAiModel("insects")}>
                                <span className="ai-model-title">Insects</span>
                            </Radio>
                        ) : (
                            <Checkbox checked={enableInsects} onChange={() => selectAiModel("insects")}>
                                <span className="ai-model-title">Insects</span>
                            </Checkbox>
                        )}
                        <a
                            href={AI_MODEL_DOC_URLS.insects}
                            target="_blank"
                            rel="noreferrer"
                            className="ai-model-doc-link"
                            title="Insects model documentation"
                        >
                            <ExternalLink size={16} color="var(--brand)" />
                        </a>
                    </div>
                    <div className="ai-model-desc">
                        This baseline model, utilized in the ECOSoundSet paper, was trained to tag audio files with one or more of 86 species from the Orthoptera and Hemiptera insect orders.
                    </div>

                    {enableInsects && (
                        <div className="ai-model-params">
                            <div className="ai-model-params-title">Parameters:</div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    window_size <span className="ai-model-param-sub">(Defaults to 4.0.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0.5} max={30} step={0.1} value={insectsWindow} onChange={setInsectsWindow} />
                            </div>

                            <div className="ai-model-param-row">
                                <div className="ai-model-param-label">
                                    stride_length <span className="ai-model-param-sub">(Defaults to 4.0.)</span>
                                </div>
                                <InputNumber className="ai-model-param-input" min={0.5} max={30} step={0.1} value={insectsStrideLength} onChange={setInsectsStrideLength} />
                            </div>
                        </div>
                    )}
                </div>
            </div>

            <Divider style={{ margin: "8px 0" }} />

            {/* Merge Section */}
            <div className="ai-models-merge-block">
                <div className="ai-models-merge-header">
                    <Checkbox checked={enableMerge} onChange={e => setEnableMerge(e.target.checked)}>
                        <span>Merge resulting conspecific annotations</span>
                    </Checkbox>
                </div>

                {enableMerge && (
                    <div className="ai-models-merge-inner">
                        <div className="ai-model-param-row" style={{ justifyContent: 'flex-start', gap: 16 }}>
                            <div className="ai-model-param-label" style={{ fontWeight: 400 }}>
                                Duration between separate annotations, in seconds (default: 0)
                            </div>
                            <InputNumber className="ai-model-param-input" min={0} value={mergeDuration} onChange={setMergeDuration} />
                        </div>
                        <div>
                            <Checkbox checked={mergeKeepOnly} onChange={e => setMergeKeepOnly(e.target.checked)}>
                                <span>Keep only merged and separate annotations</span>
                            </Checkbox>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )

    const actions = (
        <Space>
            <Button onClick={handleClose} className="ai-models-btn-cancel">
                Cancel
            </Button>
            <Button
                type="primary"
                loading={submitting}
                onClick={handleSave}
                className="ai-models-btn-save"
                style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
            >
                Save
            </Button>
        </Space>
    )

    const completionModal = (
        <Modal
            open={completionSummary !== null}
            title={completionModalTitle}
            className={`ai-completion-modal ai-completion-modal-${completionTone}`}
            okText="OK"
            cancelButtonProps={{ style: { display: "none" } }}
            onOk={handleCompletionModalOk}
            onCancel={handleCompletionModalOk}
            centered
        >
            {completionSummary && (
                <div className="ai-completion-body">
                    {completionCounts.completed > 0 && (
                        <div className="ai-completion-section">
                            <div className="ai-completion-section-title">
                                <span className="ai-completion-status-dot" />
                                <span>{completionCounts.completed} completed</span>
                            </div>
                            <div className="ai-completion-message-list">
                                {completionSummary.completed.map((status) => (
                                    <div key={status.queue_id} className="ai-completion-message">
                                        {queueCompletionText(status)}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {completionCounts.failed > 0 && (
                        <div className="ai-completion-section">
                            <div className="ai-completion-section-title ai-completion-section-title-error">
                                <span className="ai-completion-status-dot" />
                                <span>{completionCounts.failed} failed</span>
                            </div>
                            <div className="ai-completion-message-list">
                                {completionSummary.failed.map((status) => (
                                    <div key={status.queue_id} className="ai-completion-message ai-completion-message-error">
                                        {queueFailureText(status)}
                                    </div>
                                ))}
                                {completionSummary.submissionFailedCount > 0 && (
                                    <div className="ai-completion-message ai-completion-message-error">
                                        {completionSummary.submissionFailedCount} analysis job(s) failed to submit.
                                    </div>
                                )}
                                {completionCounts.completed === 0 && completionSummary.failed.length === 0 && completionSummary.submissionFailedCount === 0 && (
                                    <div className="ai-completion-message ai-completion-message-error">
                                        {firstQueueError(completionSummary.failed) || "Analysis failed. Please check the queue for details."}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </Modal>
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
                        <span className="header-title studio-analysis-embed-heading">{isBatch ? `Run AI Models (${targetMediaIds.length})` : "Run AI Models"}</span>
                    </div>
                    <div className="studio-analysis-embed-body">
                        <CustomScrollArea variant="fill" style={{ padding: "12px 14px" }}>
                            {body}
                        </CustomScrollArea>
                    </div>
                    <div className="studio-analysis-embed-foot">{actions}</div>
                </div>
                {completionModal}
            </>
        )
    }

    return (
        <ConfigProvider theme={themeCfg}>
            <>
                <FormDrawer
                    maskClosable={false}
                    closable={false}
                    title={<div style={{ fontWeight: 600, fontSize: 18, color: 'var(--text-main)' }}>Run AI Models</div>}
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
                    <CustomScrollArea variant="fill">
                        <div style={{ padding: "24px" }}>
                            {body}
                        </div>
                    </CustomScrollArea>
                </FormDrawer>
                {completionModal}
            </>
        </ConfigProvider>
    )
}
