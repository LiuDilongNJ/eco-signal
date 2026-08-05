import { Modal } from "@/components/ui"

import { useStageOverlayRoot } from "@/providers/StageOverlayContext"
import "./styles/AnalysisResultModal.css"

export interface AnalysisResultItem {
    label: string
    value: string
}

interface AnalysisResultModalProps {
    open: boolean
    title: string
    context?: string
    items: AnalysisResultItem[]
    onClose: () => void
    onSave?: () => void
    saveLoading?: boolean
    saveText?: string
}

export function AnalysisResultModal({
    open,
    title,
    context,
    items,
    onClose,
    onSave,
    saveLoading,
    saveText = "Save",
}: AnalysisResultModalProps) {
    const overlayRoot = useStageOverlayRoot()

    return (
        <Modal
            open={open}
            title={title}
            className="ai-completion-modal analysis-result-modal"
            rootClassName="analysis-result-modal-root"
            getContainer={() => overlayRoot ?? document.body}
            zIndex={10020}
            mask={{ closable: false }}
            okText={onSave ? saveText : "OK"}
            cancelText="Close"
            confirmLoading={saveLoading}
            cancelButtonProps={onSave ? undefined : { style: { display: "none" } }}
            onOk={onSave ?? onClose}
            onCancel={onClose}
            centered
        >
            <div className="ai-completion-body">
                {context ? <div className="analysis-result-context">{context}</div> : null}
                <div className="ai-completion-section">
                    <div className="ai-completion-section-title">
                        <span className="ai-completion-status-dot" />
                        <span>Results</span>
                    </div>
                    {items.length > 0 ? (
                        <div className="ai-completion-message-list">
                            {items.map((item, index) => (
                                <div key={`${item.label}-${index}`} className="ai-completion-message analysis-result-row">
                                    <span>{item.label}</span>
                                    <strong>{item.value}</strong>
                                </div>
                            ))}
                        </div>
                    ) : null}
                </div>
            </div>
        </Modal>
    )
}
