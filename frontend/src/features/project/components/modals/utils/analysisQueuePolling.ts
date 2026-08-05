import { queueApi, type QueueDetail } from "../../../../../api/endpoints/queue"

const DEFAULT_POLL_INTERVAL_MS = 2000
const TERMINAL_STATUSES = new Set(["completed", "error", "warning"])

export interface AnalysisQueuePollSummary {
    statuses: QueueDetail[]
    completed: QueueDetail[]
    failed: QueueDetail[]
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        if (signal.aborted) {
            reject(new DOMException("Polling cancelled", "AbortError"))
            return
        }

        const timeoutId = window.setTimeout(resolve, ms)
        signal.addEventListener(
            "abort",
            () => {
                window.clearTimeout(timeoutId)
                reject(new DOMException("Polling cancelled", "AbortError"))
            },
            { once: true },
        )
    })
}

export function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError"
}

export async function pollAnalysisQueues(
    queueIds: number[],
    signal: AbortSignal,
    intervalMs = DEFAULT_POLL_INTERVAL_MS,
): Promise<AnalysisQueuePollSummary> {
    const uniqueQueueIds = Array.from(
        new Set(queueIds.map((id) => Number(id)).filter((id) => Number.isFinite(id) && id > 0)),
    )
    const statusesById = new Map<number, QueueDetail>()

    while (uniqueQueueIds.length > 0) {
        const statuses = await Promise.all(
            uniqueQueueIds.map(async (queueId) => {
                const response = await queueApi.getDetail(queueId, signal)
                return response.data
            }),
        )

        statuses.forEach((status) => {
            statusesById.set(status.queue_id, status)
        })

        const latestStatuses = uniqueQueueIds
            .map((queueId) => statusesById.get(queueId))
            .filter((status): status is QueueDetail => Boolean(status))

        if (latestStatuses.every((status) => TERMINAL_STATUSES.has(status.status))) {
            return {
                statuses: latestStatuses,
                completed: latestStatuses.filter((status) => status.status === "completed"),
                failed: latestStatuses.filter((status) => status.status === "error" || status.status === "warning"),
            }
        }

        await wait(intervalMs, signal)
    }

    return { statuses: [], completed: [], failed: [] }
}
