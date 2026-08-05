/**
 * ConfirmDialog - 确认对话框
 *
 * 用于删除、批量操作等需要二次确认的场景
 */

import { Modal } from "./Modal"
import { AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui"

interface ConfirmDialogProps {
    open: boolean
    onClose: () => void
    title?: string
    message: string
    confirmLabel?: string
    cancelLabel?: string
    variant?: "danger" | "warning" | "default"
    onConfirm: () => void
}

export function ConfirmDialog({
    open,
    onClose,
    title = "Confirm",
    message,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    variant = "default",
    onConfirm,
}: ConfirmDialogProps) {
    const handleConfirm = () => {
        onConfirm()
        onClose()
    }

    return (
        <Modal
            open={open}
            onClose={onClose}
            title={title}
            width="420px"
            footer={
                <div className="app-modal-footer-actions">
                    <Button className="app-modal-btn cancel" onClick={onClose}>{cancelLabel}</Button>
                    <Button
                        className={`app-modal-btn ${variant === "danger" ? "danger" : "primary"}`}
                        onClick={handleConfirm}
                    >
                        {confirmLabel}
                    </Button>
                </div>
            }
        >
            <div className="confirm-body">
                {variant === "danger" && (
                    <div className="confirm-icon danger">
                        <AlertTriangle size={24} />
                    </div>
                )}
                {variant === "warning" && (
                    <div className="confirm-icon warning">
                        <AlertTriangle size={24} />
                    </div>
                )}
                <p className="confirm-message">{message}</p>
            </div>
        </Modal>
    )
}
