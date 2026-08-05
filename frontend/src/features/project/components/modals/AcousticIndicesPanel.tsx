import { Button as ESButton, Input as ESInput, Label } from "@/components/ui"
/**
 * AcousticIndicesPanel - 声学指数计算面板
 *
 * 选择指数 → 配置参数 → 运行计算
 */

import { useState } from "react"
import { Modal } from "./Modal"
import { CustomScrollArea } from "@/components/ui"
import { Activity, ChevronRight, Play, Loader2, CheckCircle2, Settings2 } from "lucide-react"
import { ACOUSTIC_INDICES } from "../../data/constants"

interface AcousticIndicesPanelProps {
    open: boolean
    onClose: () => void
    audioCount: number
}

export function AcousticIndicesPanel({ open, onClose, audioCount }: AcousticIndicesPanelProps) {
    const [selectedIndex, setSelectedIndex] = useState<string | null>(null)
    const [params, setParams] = useState<Record<string, number>>({})
    const [running, setRunning] = useState(false)
    const [progress, setProgress] = useState(0)
    const [done, setDone] = useState(false)

    const idx = ACOUSTIC_INDICES.find((a) => a.id === selectedIndex)

    const handleSelect = (id: string) => {
        setSelectedIndex(id)
        setDone(false)
        setRunning(false)
        setProgress(0)
        const a = ACOUSTIC_INDICES.find((x) => x.id === id)
        if (a) {
            const defaults: Record<string, number> = {}
            a.params.forEach((p) => { defaults[p.key] = p.default })
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
                return p + 4 + Math.random() * 6
            })
        }, 200)
    }

    const handleClose = () => {
        setSelectedIndex(null)
        setRunning(false)
        setProgress(0)
        setDone(false)
        onClose()
    }

    return (
        <Modal open={open} onClose={handleClose} title="Acoustic Indices" width="560px">
            <CustomScrollArea variant="fill">
                <div style={{ padding: "20px 24px" }}>
                    {!selectedIndex && (
                        <div className="ai-model-list">
                            {ACOUSTIC_INDICES.map((a) => (
                                <ESButton appearance="unstyled"
                                    key={a.id}
                                    className="ai-model-card"
                                    onClick={() => handleSelect(a.id)}
                                >
                                    <div className="ai-model-icon index-icon">
                                        <Activity size={22} />
                                    </div>
                                    <div className="ai-model-info">
                                        <span className="ai-model-name">{a.name}</span>
                                        <span className="ai-model-desc">{a.desc}</span>
                                    </div>
                                    <ChevronRight size={16} className="ai-model-arrow" />
                                </ESButton>
                            ))}
                        </div>
                    )}

                    {selectedIndex && idx && (
                        <div className="ai-config">
                            <ESButton appearance="unstyled" className="ai-back-btn" onClick={() => setSelectedIndex(null)}>
                                ← Back to indices
                            </ESButton>

                            <div className="ai-config-header">
                                <Activity size={20} />
                                <h4>{idx.name}</h4>
                            </div>
                            <p className="ai-config-desc">{idx.desc}</p>

                            <div className="ai-params-section">
                                <h5 className="ai-params-title">
                                    <Settings2 size={14} /> Parameters
                                </h5>
                                {idx.params.map((p) => (
                                    <div className="ai-param-row" key={p.key}>
                                        <Label className="ai-param-label">{p.label}</Label>
                                        <ESInput appearance="unstyled"
                                            type="number"
                                            className="ai-param-input"
                                            value={params[p.key] ?? p.default}
                                            onChange={(e) => setParams((prev) => ({ ...prev, [p.key]: Number(e.target.value) }))}
                                            step={Math.abs(p.default) >= 100 ? 100 : 1}
                                        />
                                    </div>
                                ))}
                            </div>

                            <div className="ai-scope-info">
                                <span>Scope: <strong>{audioCount.toLocaleString()} audio files</strong></span>
                            </div>

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
                                            ? "✓ Computation complete"
                                            : `Computing... ${Math.round(Math.min(progress, 100))}%`
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
                                        <><Loader2 size={16} className="ui-state__spinner" /> Computing...</>
                                    ) : done ? (
                                        <><CheckCircle2 size={16} /> Compute Again</>
                                    ) : (
                                        <><Play size={16} /> Compute Indices</>
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
