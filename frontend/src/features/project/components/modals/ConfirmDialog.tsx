/**
 * ConfirmDialog - 确认对话框
 *
 * 用于删除、批量操作等需要二次确认的场景
 */

import { Modal } from "./Modal"
import { useEffect, useId, useState } from "react"
import { AlertTriangle } from "lucide-react"
import { Button, Input, Label } from "@/components/ui"

interface ConfirmDialogProps {
    open: boolean
    onClose: () => void
    title?: string
    message: string
    confirmLabel?: string
    cancelLabel?: string
    variant?: "danger" | "warning" | "default"
    confirmationText?: string
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
    confirmationText,
    onConfirm,
}: ConfirmDialogProps) {
    const [typedConfirmation, setTypedConfirmation] = useState("")
    const confirmationInputId = useId()
    const requiresTypedConfirmation = Boolean(confirmationText)
    const confirmationMatches = !requiresTypedConfirmation || typedConfirmation === confirmationText

    useEffect(() => {
        if (!open) setTypedConfirmation("")
    }, [open])

    useEffect(() => {
        setTypedConfirmation("")
    }, [confirmationText])

    const handleConfirm = () => {
        if (!confirmationMatches) return
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
                        disabled={!confirmationMatches}
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
                {confirmationText ? (
                    <div className="confirm-text-verification">
                        <Label htmlFor={confirmationInputId}>
                            Type <strong>{confirmationText}</strong> to confirm
                        </Label>
                        <Input
                            id={confirmationInputId}
                            value={typedConfirmation}
                            onChange={(event) => setTypedConfirmation(event.target.value)}
                            autoComplete="off"
                            spellCheck={false}
                        />
                    </div>
                ) : null}
            </div>
        </Modal>
    )
}
