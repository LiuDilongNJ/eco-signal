/**
 * Tip shown when opening a tasked annotation from the Tasks dashboard.
 */

import { useEffect, useId, useState } from "react"
import { ListChecks } from "lucide-react"
import { Button } from "@/components/ui"
import { Modal } from "./Modal"
import {
    AnnotationNextIcon,
    AnnotationPrevIcon,
} from "../media/annotationToolbarIcons"
import {
    isTaskModeTipDismissed,
    setTaskModeTipDismissed,
} from "./taskModeTipPreference"
import "./styles/TaskModeTipModal.css"

type TaskModeTipModalProps = {
    open: boolean
    onClose: () => void
}

export function TaskModeTipModal({ open, onClose }: TaskModeTipModalProps) {
    const [dontShowAgain, setDontShowAgain] = useState(false)
    const dontShowAgainId = useId()

    useEffect(() => {
        if (!open) setDontShowAgain(false)
    }, [open])

    const handleClose = () => {
        if (dontShowAgain) setTaskModeTipDismissed(true)
        onClose()
    }

    return (
        <Modal
            open={open}
            onClose={handleClose}
            title="Task mode"
            width="520px"
            footer={
                <div className="app-modal-footer-actions task-mode-tip-footer">
                    <label className="task-mode-tip-dont-show" htmlFor={dontShowAgainId}>
                        <input
                            id={dontShowAgainId}
                            type="checkbox"
                            className="task-mode-tip-checkbox"
                            checked={dontShowAgain}
                            onChange={(e) => setDontShowAgain(e.target.checked)}
                        />
                        <span>Don&apos;t show this tip again</span>
                    </label>
                    <Button className="app-modal-btn primary" onClick={handleClose}>
                        Got it
                    </Button>
                </div>
            }
        >
            <div className="task-mode-tip-body">
                <p>
                    You have opened an annotation you are tasked to review.
                </p>
                <p>
                    The task mode is on:
                </p>
                <div className="task-mode-tip-preview" aria-hidden="true">
                    <span className="task-mode-tip-chip is-active" title="Task mode">
                        <ListChecks size={18} strokeWidth={2} />
                    </span>
                </div>
                <p>
                    Now you can navigate to tasked annotations using these arrows,
                    even when they are in other media files:
                </p>
                <div className="task-mode-tip-preview" aria-hidden="true">
                    <span className="task-mode-tip-chip">
                        <AnnotationPrevIcon size={18} strokeWidth={2} />
                    </span>
                    <span className="task-mode-tip-chip">
                        <AnnotationNextIcon size={18} strokeWidth={2} />
                    </span>
                </div>
                <p>
                    After reviewing a tasked annotation, the task will be cleared from your tasks list.
                </p>
            </div>
        </Modal>
    )
}

export function shouldOpenTaskModeTip(): boolean {
    return !isTaskModeTipDismissed()
}
