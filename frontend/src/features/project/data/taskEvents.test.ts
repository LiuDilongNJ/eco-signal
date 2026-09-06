import { describe, expect, it, vi } from "vitest"
import { TASKS_CHANGED_EVENT, dispatchTasksChanged, subscribeTasksChanged } from "./taskEvents"

describe("task change events", () => {
    it("dispatches the event with the affected project context", () => {
        const listener = vi.fn()
        window.addEventListener(TASKS_CHANGED_EVENT, listener)

        dispatchTasksChanged(42)

        expect(listener).toHaveBeenCalledTimes(1)
        expect(listener.mock.calls[0]?.[0]).toMatchObject({
            type: TASKS_CHANGED_EVENT,
            detail: { projectId: 42 },
        })
        window.removeEventListener(TASKS_CHANGED_EVENT, listener)
    })

    it("notifies subscribers once for the local event", () => {
        const listener = vi.fn()
        const unsubscribe = subscribeTasksChanged(listener)

        dispatchTasksChanged(7)

        expect(listener).toHaveBeenCalledTimes(1)
        expect(listener.mock.calls[0]?.[0]).toMatchObject({ projectId: 7 })
        unsubscribe()
    })
})
