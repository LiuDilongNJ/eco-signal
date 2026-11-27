import { useCallback, useEffect, useRef, useState } from "react"
import type { Key } from "react"
import { annotationsApi } from "@/api/endpoints/annotations"
import { message } from "@/components/ui"

type DeleteAnnotations = (ids: number[], projectId: number) => void

export function useAnnotationDeletionConfirmation(projectId: number | null, scopeKey: Key | null) {
    const [pending, setPending] = useState(false)
    const [confirmation, setConfirmation] = useState<{
        projectId: number
        scopeKey: Key | null
        count: number
        text: string
        confirm: () => void
    } | null>(null)
    const request = useRef<AbortController | null>(null)
    const close = useCallback(() => setConfirmation(null), [])

    useEffect(() => {
        setPending(false)
        setConfirmation(null)
        return () => {
            request.current?.abort()
            request.current = null
        }
    }, [projectId, scopeKey])

    async function prepareDeletion(keys: Key[], onConfirm: DeleteAnnotations) {
        if (request.current || projectId == null) return
        const ids = [...new Set(keys.map(Number))].filter((id) => Number.isSafeInteger(id) && id > 0)
        if (ids.length === 0) return

        const controller = new AbortController()
        request.current = controller
        setPending(true)
        try {
            const { annotation_count: count, task_count: taskCount } = await annotationsApi.getDeletionPreview(ids, projectId, controller.signal)
            if (controller.signal.aborted) return
            const annotations = `${count} annotation${count === 1 ? "" : "s"}`
            const tasks = `${taskCount} associated task${taskCount === 1 ? "" : "s"}`
            setConfirmation({
                projectId,
                scopeKey,
                count,
                text: taskCount > 0
                    ? `Deleting ${annotations} will also delete ${tasks}. This action cannot be undone.`
                    : `Are you sure you want to delete ${annotations}? This action cannot be undone.`,
                confirm: () => onConfirm(ids, projectId),
            })
        } catch (error: unknown) {
            if (!controller.signal.aborted) {
                message.error(error instanceof Error ? error.message : "Could not preview annotation deletion.")
            }
        } finally {
            if (request.current === controller) {
                request.current = null
                setPending(false)
            }
        }
    }

    const open = confirmation != null && confirmation.projectId === projectId && confirmation.scopeKey === scopeKey
    return {
        pending,
        prepareDeletion,
        dialog: {
            open,
            title: confirmation?.count === 1 ? "Delete Annotation" : "Delete Annotations",
            message: confirmation?.text ?? "",
            confirmLabel: "Delete",
            variant: "danger" as const,
            onClose: close,
            onConfirm: () => { if (open) confirmation.confirm() },
        },
    }
}
