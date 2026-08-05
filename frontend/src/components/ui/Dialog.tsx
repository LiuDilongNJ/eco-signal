import { useEffect, useId, useRef, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import { Modal as AntModal, type ModalFuncProps, type ModalProps } from "antd"
import { useStageOverlayRoot } from "@/providers/StageOverlayContext"
import { cn } from "@/lib/utils"
import { IconButton } from "./Button"

export interface DialogProps {
    open: boolean
    onClose: () => void
    rootClassName?: string
    title?: string
    width?: string | number
    footer?: ReactNode
    children: ReactNode
    closeOnMask?: boolean
}

export function Dialog({
    open,
    onClose,
    rootClassName,
    title,
    width = 480,
    footer,
    children,
    closeOnMask = false,
}: DialogProps) {
    const overlayRoot = useStageOverlayRoot()
    const titleId = useId()
    const panelRef = useRef<HTMLDivElement>(null)
    const previousFocusRef = useRef<HTMLElement | null>(null)

    useEffect(() => {
        if (!open) return
        previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
        const focusTarget = panelRef.current?.querySelector<HTMLElement>(
            "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
        )
        ;(focusTarget ?? panelRef.current)?.focus()

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                event.stopImmediatePropagation()
                onClose()
            }
        }
        window.addEventListener("keydown", handleKeyDown, true)
        return () => {
            window.removeEventListener("keydown", handleKeyDown, true)
            previousFocusRef.current?.focus()
        }
    }, [open, onClose])

    if (!open || !overlayRoot) return null
    const settingsRouteClassName =
        typeof window !== "undefined" && window.location.pathname.startsWith("/settings")
            ? "settings-stage-modal"
            : undefined

    return createPortal(
        <div
            className={cn("app-modal-overlay", "es-dialog-overlay", settingsRouteClassName, rootClassName)}
            onMouseDown={closeOnMask ? onClose : undefined}
        >
            <div
                ref={panelRef}
                className="app-modal-panel es-dialog"
                style={{ width, maxWidth: "calc(100% - 48px)" }}
                role="dialog"
                aria-modal="true"
                aria-labelledby={title ? titleId : undefined}
                aria-label={title ? undefined : "Dialog"}
                tabIndex={-1}
                onMouseDown={(event) => event.stopPropagation()}
            >
                {title ? (
                    <div className="app-modal-header es-dialog__header">
                        <h3 id={titleId} className="app-modal-title es-dialog__title">{title}</h3>
                        <IconButton
                            className="app-modal-close-btn es-dialog__close"
                            icon={<X size={18} />}
                            label="Close"
                            onClick={onClose}
                        />
                    </div>
                ) : null}
                <div className="app-modal-body es-dialog__body">{children}</div>
                {footer ? <div className="app-modal-footer es-dialog__footer">{footer}</div> : null}
            </div>
        </div>,
        overlayRoot,
    )
}

function ModalAdapter({ className, rootClassName, ...props }: ModalProps) {
    return (
        <AntModal
            className={cn("es-dialog-modal", className)}
            rootClassName={cn("es-dialog-modal-root", rootClassName)}
            {...props}
        />
    )
}

function withDialogContract(config: ModalFuncProps): ModalFuncProps {
    return {
        ...config,
        className: cn("es-dialog-modal", config.className),
        rootClassName: cn("es-dialog-modal-root", config.rootClassName),
    }
}

export const Modal = Object.assign(ModalAdapter, {
    confirm: (config: ModalFuncProps) => AntModal.confirm(withDialogContract(config)),
    info: (config: ModalFuncProps) => AntModal.info(withDialogContract(config)),
    success: (config: ModalFuncProps) => AntModal.success(withDialogContract(config)),
    error: (config: ModalFuncProps) => AntModal.error(withDialogContract(config)),
    warning: (config: ModalFuncProps) => AntModal.warning(withDialogContract(config)),
    warn: (config: ModalFuncProps) => AntModal.warning(withDialogContract(config)),
    destroyAll: AntModal.destroyAll,
    useModal: AntModal.useModal,
}) as typeof AntModal
