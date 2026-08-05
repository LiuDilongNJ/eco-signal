import { Button as ESButton } from "@/components/ui"
import { useEffect, useRef, useState } from "react"
import { Button, InputNumber, Radio, message } from "@/components/ui"
import { ArrowLeft, ExternalLink } from "lucide-react"

import { analysisApi, type AcousticIndexSelection } from "../../../../api/endpoints/analysis"
import { CustomScrollArea } from "@/components/ui"
import { AnalysisResultModal, type AnalysisResultItem } from "../modals/AnalysisResultModal"
import { isAbortError, pollAnalysisQueues } from "../modals/utils/analysisQueuePolling"
import "../modals/styles/RunAIModelsDrawer.css"

interface AcousticAnalysisStudioPanelProps {
    mediaId: number
    projectId: number | null
    selection: AcousticIndexSelection | null
    isFullTimeWindow: boolean
    channel: "mono" | "left" | "right"
    onBack: () => void
    onSuccess?: () => void
    onProcessingChange?: (processing: boolean) => void
}

type AcousticAnalysisType = "template_matching" | "max_frequency"

interface AcousticAnalysisOption {
    type: AcousticAnalysisType
    title: string
    description: string
    documentationUrl: string
    documentationLabel: string
}

const ACOUSTIC_ANALYSIS_OPTIONS: readonly AcousticAnalysisOption[] = [
    {
        type: "template_matching",
        title: "Template Matching",
        description: "Use normalized spectrogram cross-correlation to detect the occurrence of a template sound in a target audio.",
        documentationUrl: "https://scikit-maad.github.io/generated/maad.rois.template_matching.html#",
        documentationLabel: "Template Matching documentation",
    },
    {
        type: "max_frequency",
        title: "Frequency of Maximum Energy",
        description: "Return the maximum of an array or maximum along an axis.",
        documentationUrl: "https://numpy.org/doc/stable/reference/generated/numpy.max.html",
        documentationLabel: "Frequency of Maximum Energy documentation",
    },
]

function formatContextNumber(value: number): string {
    if (!Number.isFinite(value)) return ""
    const formatted = value.toFixed(4).replace(/\.?0+$/, "")
    return formatted === "" || formatted === "-0" ? "0" : formatted
}

async function copyTextToClipboard(text: string): Promise<void> {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text)
            return
        } catch {
            // Fall through to the legacy copy path for restricted browsers.
        }
    }

    const textarea = document.createElement("textarea")
    textarea.value = text
    textarea.setAttribute("readonly", "")
    textarea.style.position = "fixed"
    textarea.style.top = "-1000px"
    textarea.style.left = "-1000px"
    textarea.style.opacity = "0"
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    textarea.setSelectionRange(0, text.length)

    try {
        const copied = document.execCommand("copy")
        if (!copied) throw new Error("Fallback copy failed")
    } finally {
        document.body.removeChild(textarea)
    }
}

function parseFrequencyCompletionMessage(completionMessage: string): AnalysisResultItem {
    const separatorIndex = completionMessage.indexOf(":")
    const label = separatorIndex > 0
        ? completionMessage.slice(0, separatorIndex).trim()
        : "Frequency of maximum energy"
    const frequency = (separatorIndex > 0
        ? completionMessage.slice(separatorIndex + 1)
        : completionMessage).trim()
    return {
        label,
        value: frequency ? `${frequency.replace(/\s*Hz$/i, "")} Hz` : "No result",
    }
}

export function AcousticAnalysisStudioPanel({
    mediaId,
    projectId,
    selection,
    isFullTimeWindow,
    channel,
    onBack,
    onSuccess,
    onProcessingChange,
}: AcousticAnalysisStudioPanelProps) {
    const [running, setRunning] = useState(false)
    const [analysisType, setAnalysisType] = useState<AcousticAnalysisType>("template_matching")
    const [peakThreshold, setPeakThreshold] = useState<number | null>(0.5)
    const [peakDistance, setPeakDistance] = useState<number | null>(null)
    const [resultItems, setResultItems] = useState<AnalysisResultItem[]>([])
    const [resultTitle, setResultTitle] = useState("Template Matching")
    const [resultContext, setResultContext] = useState("")
    const [resultOpen, setResultOpen] = useState(false)
    const [refreshOnResultClose, setRefreshOnResultClose] = useState(false)
    const pollControllerRef = useRef<AbortController | null>(null)
    const mountedRef = useRef(true)
    const processingChangeRef = useRef(onProcessingChange)

    useEffect(() => {
        processingChangeRef.current = onProcessingChange
    }, [onProcessingChange])

    useEffect(() => {
        setAnalysisType("template_matching")
        setPeakThreshold(0.5)
        setPeakDistance(null)
    }, [])

    useEffect(() => {
        mountedRef.current = true
        return () => {
            mountedRef.current = false
            pollControllerRef.current?.abort()
            processingChangeRef.current?.(false)
        }
    }, [])

    const handleRun = async () => {
        if (!selection) {
            message.warning("Please select a valid time and frequency range")
            return
        }
        if (!projectId) {
            message.warning("Project context is missing")
            return
        }
        if (analysisType === "template_matching" && isFullTimeWindow) {
            message.warning("Please zoom in before executing.")
            return
        }
        const submittedAnalysis = ACOUSTIC_ANALYSIS_OPTIONS.find((option) => option.type === analysisType)!
        const submittedContext = context
        pollControllerRef.current?.abort()
        const pollController = new AbortController()
        pollControllerRef.current = pollController
        setResultTitle(submittedAnalysis.title)
        setResultContext(submittedContext)
        setResultItems([])
        setRunning(true)
        processingChangeRef.current?.(true)
        try {
            const response = await analysisApi.runAcousticIndices({
                project_id: projectId,
                media_ids: [mediaId],
                selection,
                channel,
                indices: [{
                    analysis_type: submittedAnalysis.type,
                    params: submittedAnalysis.type === "template_matching"
                        ? { peak_th: peakThreshold ?? 0.5, peak_distance: peakDistance }
                        : {},
                }],
            })
            if (!mountedRef.current || pollController.signal.aborted) return
            const queueIds = response.data?.queued?.map((item) => item.queue_id) ?? []
            if (queueIds.length === 0) {
                message.error(response.data?.failed?.[0]?.reason || "Failed to submit acoustic analysis")
                return
            }
            const summary = await pollAnalysisQueues(queueIds, pollController.signal)
            if (!mountedRef.current || pollController.signal.aborted) return
            const completed = summary.completed[0]
            if (!completed) {
                message.error(summary.failed[0]?.error || "Acoustic analysis failed")
                return
            }
            if (submittedAnalysis.type === "template_matching") {
                const completionMessage = completed.message || "No valid data matched."
                setRefreshOnResultClose(completionMessage !== "No valid data matched." && completed.completed > 0)
                setResultItems([{
                    label: "Template Matching",
                    value: completionMessage,
                }])
                setResultOpen(true)
                return
            }
            const resultItem = parseFrequencyCompletionMessage(
                completed.message || "Frequency of maximum energy:",
            )
            const frequency = resultItem.value.match(/[-+]?(?:\d+\.?\d*|\.\d+)/)?.[0]
            if (frequency) {
                void copyTextToClipboard(frequency).catch(() => {
                    if (mountedRef.current && pollControllerRef.current === pollController && !pollController.signal.aborted) {
                        message.warning("Failed to copy frequency result.")
                    }
                })
            }
            setResultItems([resultItem])
            setRefreshOnResultClose(false)
            setResultOpen(true)
        } catch (error) {
            if (isAbortError(error) || pollController.signal.aborted) return
            message.error(error instanceof Error ? error.message : "Acoustic analysis failed")
        } finally {
            if (pollControllerRef.current === pollController) {
                pollControllerRef.current = null
                processingChangeRef.current?.(false)
                if (mountedRef.current) {
                    setRunning(false)
                }
            }
        }
    }

    const channelLabel = channel === "mono" ? "Mono" : channel === "right" ? "Right" : "Left"
    const context = selection
        ? `${channelLabel} · ${formatContextNumber(selection.min_time)}-${formatContextNumber(selection.max_time)}s · ${formatContextNumber(selection.min_frequency)}-${formatContextNumber(selection.max_frequency)}Hz`
        : channelLabel
    const handleResultClose = () => {
        setResultOpen(false)
        if (refreshOnResultClose) {
            onSuccess?.()
        }
        setRefreshOnResultClose(false)
    }
    return (
        <>
            <div className="studio-analysis-embed">
                <div className="studio-analysis-embed-top">
                    <ESButton appearance="unstyled" type="button" className="header-back" title="Back" onClick={onBack} disabled={running}>
                        <ArrowLeft size={18} strokeWidth={2.25} />
                    </ESButton>
                    <span className="header-title studio-analysis-embed-heading">Acoustic Analysis</span>
                </div>
                <div className="studio-analysis-embed-body">
                    <CustomScrollArea variant="fill" style={{ padding: "12px 14px" }}>
                        <div className="ai-models-container">
                            <div className="ai-models-gray-block">
                                {ACOUSTIC_ANALYSIS_OPTIONS.map((option, index) => (
                                    <div key={option.type}>
                                        {index > 0 ? <div className="ai-model-divider" /> : null}
                                        <div className="ai-model-section">
                                            <div className="ai-model-header">
                                                <Radio disabled={running} checked={analysisType === option.type} onChange={() => setAnalysisType(option.type)}>
                                                    <span className="ai-model-title">{option.title}</span>
                                                </Radio>
                                                <a
                                                    href={option.documentationUrl}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    className="ai-model-doc-link"
                                                    title={option.documentationLabel}
                                                    aria-label={option.documentationLabel}
                                                >
                                                    <ExternalLink size={16} color="var(--brand)" />
                                                </a>
                                            </div>
                                            <div className="ai-model-desc">{option.description}</div>
                                            {option.type === "template_matching" && analysisType === option.type ? (
                                                <div className="ai-model-params">
                                                    <div className="ai-model-param-row">
                                                        <div className="ai-model-param-label">peak_th<span className="ai-model-param-sub">Default: 0.5</span></div>
                                                        <InputNumber disabled={running} className="ai-model-param-input" min={0} max={1} step={0.01} value={peakThreshold} onChange={setPeakThreshold} />
                                                    </div>
                                                    <div className="ai-model-param-row">
                                                        <div className="ai-model-param-label">peak_distance<span className="ai-model-param-sub">Default: None</span></div>
                                                        <InputNumber disabled={running} className="ai-model-param-input" min={0} value={peakDistance} onChange={setPeakDistance} />
                                                    </div>
                                                </div>
                                            ) : null}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </CustomScrollArea>
                </div>
                <div className="studio-analysis-embed-foot">
                    <div className="ai-models-footer">
                        <Button onClick={onBack} className="ai-models-btn-cancel" disabled={running}>Cancel</Button>
                        <Button type="primary" onClick={() => void handleRun()} loading={running} disabled={!selection} className="ai-models-btn-save">Run</Button>
                    </div>
                </div>
            </div>
            <AnalysisResultModal
                open={resultOpen}
                title={resultTitle}
                context={resultContext}
                items={resultItems}
                onClose={handleResultClose}
            />
        </>
    )
}
