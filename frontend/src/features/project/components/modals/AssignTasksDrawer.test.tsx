import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { tasksApi } from "@/api/endpoints/tasks"
import { AssignTasksDrawer } from "./AssignTasksDrawer"

vi.mock("@/api/endpoints/tasks", () => ({
    tasksApi: {
        getAssignableUsers: vi.fn(),
        getBatchAssignableUsers: vi.fn(),
        assignTasks: vi.fn(),
        assignTasksBatch: vi.fn(),
    },
}))

function addOverlayRoot() {
    let overlay = document.getElementById(APP_OVERLAY_ROOT_ID)
    if (!overlay) {
        overlay = document.createElement("div")
        overlay.id = APP_OVERLAY_ROOT_ID
        document.body.append(overlay)
    }
    return overlay
}

describe("AssignTasksDrawer", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        addOverlayRoot()
    })

    it("assigns 30 annotations across multiple media in a single batch request", async () => {
        const annotationIds = Array.from({ length: 30 }, (_, index) => index + 1)
        const mediaIds = [101, 102, 103]
        const onClose = vi.fn()
        const onSuccess = vi.fn()

        vi.mocked(tasksApi.getBatchAssignableUsers).mockResolvedValue({
            code: 0,
            message: "success",
            data: [
                { user_id: 2, name: "Alice Reviewer", username: "alice", task_count: 0 },
                { user_id: 3, name: "Bob Reviewer", username: "bob", task_count: 0 },
            ],
        })
        vi.mocked(tasksApi.assignTasksBatch).mockResolvedValue({
            code: 0,
            message: "success",
            data: { assigned_count: 30 },
        })

        render(
            <MemoryRouter>
                <AssignTasksDrawer
                    open
                    mediaId={mediaIds[0]!}
                    mediaIds={mediaIds}
                    projectId={10}
                    annotationIds={annotationIds}
                    onClose={onClose}
                    onSuccess={onSuccess}
                />
            </MemoryRouter>,
        )

        expect(screen.getByText("Assign Tasks (30 annotations)")).toBeInTheDocument()

        await waitFor(() => {
            expect(screen.getByText("Alice Reviewer")).toBeInTheDocument()
        })

        expect(tasksApi.getBatchAssignableUsers).toHaveBeenCalledTimes(1)
        expect(tasksApi.getBatchAssignableUsers).toHaveBeenCalledWith(10, [101, 102, 103])
        expect(tasksApi.getAssignableUsers).not.toHaveBeenCalled()

        const saveButton = screen.getByRole("button", { name: "Save" })
        expect(saveButton).toBeDisabled()

        fireEvent.click(screen.getByLabelText("Alice Reviewer"))
        expect(saveButton).not.toBeDisabled()

        fireEvent.change(screen.getByLabelText("Notes for Alice Reviewer"), {
            target: { value: "Verify batch detections" },
        })
        fireEvent.click(saveButton)

        await waitFor(() => {
            expect(tasksApi.assignTasksBatch).toHaveBeenCalledTimes(1)
        })

        expect(tasksApi.assignTasksBatch).toHaveBeenCalledWith(10, {
            type: "annotation",
            annotation_ids: annotationIds,
            assignments: [{ user_id: 2, comment: "Verify batch detections" }],
        })
        expect(tasksApi.assignTasks).not.toHaveBeenCalled()
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it("assigns multiple media items via the batch endpoint", async () => {
        const onClose = vi.fn()
        vi.mocked(tasksApi.getBatchAssignableUsers).mockResolvedValue({
            code: 0,
            message: "success",
            data: [
                { user_id: 5, name: "Carol Reviewer", username: "carol", task_count: 0 },
            ],
        })
        vi.mocked(tasksApi.assignTasksBatch).mockResolvedValue({
            code: 0,
            message: "success",
            data: { assigned_count: 3 },
        })

        render(
            <MemoryRouter>
                <AssignTasksDrawer
                    open
                    mediaId={10}
                    mediaIds={[10, 11, 12]}
                    projectId={7}
                    onClose={onClose}
                />
            </MemoryRouter>,
        )

        expect(screen.getByText("Assign Tasks (3 items)")).toBeInTheDocument()

        await waitFor(() => {
            expect(screen.getByText("Carol Reviewer")).toBeInTheDocument()
        })

        fireEvent.click(screen.getByLabelText("Carol Reviewer"))
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => {
            expect(tasksApi.assignTasksBatch).toHaveBeenCalledWith(7, {
                type: "media",
                media_ids: [10, 11, 12],
                assignments: [{ user_id: 5, comment: "" }],
            })
        })
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it("pre-selects users with existing tasks for single media selection", async () => {
        vi.mocked(tasksApi.getAssignableUsers).mockResolvedValue({
            code: 0,
            message: "success",
            data: [
                { user_id: 8, name: "Dave Reviewer", username: "dave", task_count: 2 },
                { user_id: 9, name: "Eve Reviewer", username: "eve", task_count: 0 },
            ],
        })

        render(
            <MemoryRouter>
                <AssignTasksDrawer
                    open
                    mediaId={42}
                    mediaIds={[42]}
                    projectId={3}
                    onClose={vi.fn()}
                />
            </MemoryRouter>,
        )

        await waitFor(() => {
            expect(screen.getByLabelText("Dave Reviewer")).toBeChecked()
        })
        expect(screen.getByLabelText("Eve Reviewer")).not.toBeChecked()
        expect(tasksApi.getAssignableUsers).toHaveBeenCalledWith(3, 42)
        expect(tasksApi.getBatchAssignableUsers).not.toHaveBeenCalled()
    })
})
