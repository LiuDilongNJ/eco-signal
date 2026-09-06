export const TASKS_CHANGED_EVENT = "eco-tasks-changed"
const TASKS_CHANGED_CHANNEL = "eco-tasks-changed-channel"
const TASKS_CHANGED_STORAGE_KEY = "eco-tasks-changed-message"

export interface TasksChangedDetail {
    projectId?: number
    eventId: string
}

type TasksChangedListener = (detail: TasksChangedDetail) => void

function createEventId(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function dispatchTasksChanged(projectId?: number | null): void {
    const detail: TasksChangedDetail = {
        eventId: createEventId(),
        ...(projectId == null ? {} : { projectId }),
    }

    window.dispatchEvent(
        new CustomEvent(TASKS_CHANGED_EVENT, {
            detail,
        }),
    )

    try {
        if (typeof BroadcastChannel !== "undefined") {
            const channel = new BroadcastChannel(TASKS_CHANGED_CHANNEL)
            channel.postMessage(detail)
            channel.close()
        }
    } catch {
        // Storage notification below is the fallback for unsupported channels.
    }

    try {
        window.localStorage.setItem(TASKS_CHANGED_STORAGE_KEY, JSON.stringify(detail))
    } catch {
        // Private browsing or blocked storage must not break task assignment.
    }
}

export function subscribeTasksChanged(listener: TasksChangedListener): () => void {
    const seenEventIds = new Set<string>()
    const notify = (detail: TasksChangedDetail) => {
        if (!detail?.eventId || seenEventIds.has(detail.eventId)) return
        seenEventIds.add(detail.eventId)
        if (seenEventIds.size > 20) {
            const oldest = seenEventIds.values().next().value
            if (oldest) seenEventIds.delete(oldest)
        }
        listener(detail)
    }

    const handleWindowEvent = (event: Event) => {
        notify((event as CustomEvent<TasksChangedDetail>).detail)
    }
    const handleStorageEvent = (event: StorageEvent) => {
        if (event.key !== TASKS_CHANGED_STORAGE_KEY || !event.newValue) return
        try {
            notify(JSON.parse(event.newValue) as TasksChangedDetail)
        } catch {
            // Ignore malformed cross-tab messages.
        }
    }

    window.addEventListener(TASKS_CHANGED_EVENT, handleWindowEvent)
    window.addEventListener("storage", handleStorageEvent)

    let channel: BroadcastChannel | null = null
    if (typeof BroadcastChannel !== "undefined") {
        try {
            channel = new BroadcastChannel(TASKS_CHANGED_CHANNEL)
            channel.addEventListener("message", (event: MessageEvent<TasksChangedDetail>) => notify(event.data))
        } catch {
            channel = null
        }
    }

    return () => {
        window.removeEventListener(TASKS_CHANGED_EVENT, handleWindowEvent)
        window.removeEventListener("storage", handleStorageEvent)
        channel?.close()
    }
}
