import { Button as ESButton, Input as ESInput, Label } from "@/components/ui"
/**
 * AIModelsPanel - AI 模型运行面板
 *
 * 选择模型 → 配置参数 → 选择音频范围 → 运行分析
 */

import { useState } from "react"
import { Modal } from "./Modal"
import { CustomScrollArea } from "@/components/ui"
import { Brain, ChevronRight, Play, Loader2, CheckCircle2, Settings2 } from "lucide-react"
import { AI_MODELS } from "../../data/constants"

interface AIModelsPanelProps {
    open: boolean
    onClose: () => void
    audioCount: number
}

export function AIModelsPanel({ open, onClose, audioCount }: AIModelsPanelProps) {
    const [selectedModel, setSelectedModel] = useState<string | null>(null)
    const [params, setParams] = useState<Record<string, number>>({})
    const [running, setRunning] = useState(false)
    const [progress, setProgress] = useState(0)
    const [done, setDone] = useState(false)

    const model = AI_MODELS.find((m) => m.id === selectedModel)

    const handleSelectModel = (id: string) => {
        setSelectedModel(id)
        setDone(false)
        setRunning(false)
        setProgress(0)
        const m = AI_MODELS.find((a) => a.id === id)
        if (m) {
            const defaults: Record<string, number> = {}
            m.params.forEach((p) => { defaults[p.key] = p.default })
            setParams(defaults)
        }
    }

    const handleRun = () => {
        setRunning(true)
        setProgress(0)
        setDone(false)
        const interval = setInterval(() => {
            setProgress((p) => {
                if (p >= 100) {
                    clearInterval(interval)
                    setRunning(false)
                    setDone(true)
                    return 100
                }
                return p + 3 + Math.random() * 5
            })
        }, 200)
    }

    const handleClose = () => {
        setSelectedModel(null)
        setRunning(false)
        setProgress(0)
        setDone(false)
        onClose()
    }

    return (
        <Modal open={open} onClose={handleClose} title="AI Models" width="560px">
            <CustomScrollArea variant="fill">
                <div style={{ padding: "20px 24px" }}>
                    {/* Model Selection */}
                    {!selectedModel && (
                        <div className="ai-model-list">
                            {AI_MODELS.map((m) => (
                                <ESButton appearance="unstyled"
                                    key={m.id}
                                    className="ai-model-card"
                                    onClick={() => handleSelectModel(m.id)}
                                >
                                    <div className="ai-model-icon">
                                        <Brain size={22} />
                                    </div>
                                    <div className="ai-model-info">
                                        <span className="ai-model-name">{m.name}</span>
                                        <span className="ai-model-desc">{m.desc}</span>
                                    </div>
                                    <ChevronRight size={16} className="ai-model-arrow" />
                                </ESButton>
                            ))}
                        </div>
                    )}

                    {/* Model Config */}
                    {selectedModel && model && (
                        <div className="ai-config">
                            <ESButton appearance="unstyled" className="ai-back-btn" onClick={() => setSelectedModel(null)}>
                                ← Back to models
                            </ESButton>

                            <div className="ai-config-header">
                                <Brain size={20} />
                                <h4>{model.name}</h4>
                            </div>
                            <p className="ai-config-desc">{model.desc}</p>

                            <div className="ai-params-section">
                                <h5 className="ai-params-title">
                                    <Settings2 size={14} /> Parameters
                                </h5>
                                {model.params.map((p) => (
                                    <div className="ai-param-row" key={p.key}>
                                        <Label className="ai-param-label">{p.label}</Label>
                                        <ESInput appearance="unstyled"
                                            type="number"
                                            className="ai-param-input"
                                            value={params[p.key] ?? p.default}
                                            onChange={(e) => setParams((prev) => ({ ...prev, [p.key]: Number(e.target.value) }))}
                                            step={p.default < 1 ? 0.05 : 1}
                                        />
                                    </div>
                                ))}
                            </div>

                            <div className="ai-scope-info">
                                <span>Scope: <strong>{audioCount.toLocaleString()} audio files</strong></span>
                            </div>

                            {/* Progress */}
                            {(running || done) && (
                                <div className="ai-progress-section">
                                    <div className="ai-progress-bar">
                                        <div
                                            className={`ai-progress-fill ${done ? "done" : ""}`}
                                            style={{ width: `${Math.min(progress, 100)}%` }}
                                        />
                                    </div>
                                    <span className="ai-progress-text">
                                        {done
                                            ? "✓ Analysis complete"
                                            : `Processing... ${Math.round(Math.min(progress, 100))}%`
                                        }
                                    </span>
                                </div>
                            )}

                            <div className="ai-run-section">
                                <ESButton appearance="unstyled"
                                    className="ai-run-btn"
                                    onClick={handleRun}
                                    disabled={running || audioCount === 0}
                                >
                                    {running ? (
                                        <><Loader2 size={16} className="ui-state__spinner" /> Running...</>
                                    ) : done ? (
                                        <><CheckCircle2 size={16} /> Run Again</>
                                    ) : (
                                        <><Play size={16} /> Run Analysis</>
                                    )}
                                </ESButton>
                            </div>
                        </div>
                    )}
                </div>
            </CustomScrollArea>
        </Modal>
    )
}
