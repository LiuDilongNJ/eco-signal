import { useEffect, type ReactNode } from "react"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { annotationsApi } from "@/api/endpoints/annotations"
import { AnnotationsPage } from "./AnnotationsPage"

const mockDrawerSpy = vi.fn()

vi.mock("@/api/endpoints/annotations", () => ({
    annotationsApi: {
        getList: vi.fn(),
        getById: vi.fn(),
        update: vi.fn(),
        deleteBatch: vi.fn(),
        exportCsv: vi.fn(),
    },
}))

vi.mock("@/hooks/usePermissions", () => ({
    usePermissions: () => ({
        can: () => true,
    }),
}))

vi.mock("../../../stores/useProjectStore", () => ({
    useProjectStore: (selector: (state: { currentProjectId: number; currentCollectionId: string }) => unknown) =>
        selector({ currentProjectId: 10, currentCollectionId: "all" }),
}))

vi.mock("../../modals/AssignTasksDrawer", () => ({
    AssignTasksDrawer: (props: Record<string, unknown>) => {
        mockDrawerSpy(props)
        return props.open ? <div data-testid="assign-tasks-drawer">drawer-open</div> : null
    },
}))

vi.mock("../../modals/AnnotationFormDrawer", () => ({
    AnnotationFormDrawer: () => null,
}))

vi.mock("../DataPageLayout", () => ({
    DataPageLayout: ({
        rows,
        onTableStateChange,
        renderCustomActions,
    }: {
        rows: Array<Record<string, unknown>>
        onTableStateChange: (state: {
            page: number
            pageSize: number
            sortKey: string | null
            sortDir: "asc" | "desc" | null
            filters: Record<string, string>
        }) => void
        renderCustomActions?: (selectedRows: Set<number>) => ReactNode
    }) => {
        useEffect(() => {
            onTableStateChange({ page: 1, pageSize: 50, sortKey: "annotation_id", sortDir: "asc", filters: {} })
        }, [onTableStateChange])
        const allKeys = new Set(rows.map((row) => Number(row.annotation_id)))
        return (
            <div>
                <div data-testid="row-count">{rows.length}</div>
                {renderCustomActions?.(allKeys)}
            </div>
        )
    },
}))

describe("AnnotationsPage batch assignment", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("enables Assignment and passes all mediaIds and annotationIds when selecting 30 annotations across multiple media", async () => {
        const items = Array.from({ length: 30 }, (_, idx) => ({
            annotation_id: idx + 1,
            uuid: `00000000-0000-0000-0000-${String(idx + 1).padStart(12, "0")}`,
            media_id: idx < 12 ? 101 : idx < 24 ? 102 : 103,
            media_name: `audio_${idx < 12 ? 1 : idx < 24 ? 2 : 3}.wav`,
            media_type: "audio",
            min_x: 0,
            max_x: 1,
            min_y: 100,
            max_y: 500,
            reference: false,
            capabilities: { edit: true, delete: true, assign: true, create_review: true },
        }))

        vi.mocked(annotationsApi.getList).mockResolvedValue({
            code: 0,
            message: "success",
            data: items as never,
            page_info: { page: 1, page_size: 50, total: 30, total_pages: 1 },
        })

        render(
            <MemoryRouter>
                <AnnotationsPage />
            </MemoryRouter>,
        )

        await waitFor(() => {
            expect(screen.getByTestId("row-count")).toHaveTextContent("30")
        })

        const assignBtn = screen.getByRole("button", { name: /Assignment/i })
        expect(assignBtn).not.toBeDisabled()

        fireEvent.click(assignBtn)

        await waitFor(() => {
            expect(screen.getByTestId("assign-tasks-drawer")).toBeInTheDocument()
        })

        const lastCallProps = mockDrawerSpy.mock.calls.at(-1)?.[0] as Record<string, unknown>
        expect(lastCallProps.open).toBe(true)
        expect(lastCallProps.projectId).toBe(10)
        expect(lastCallProps.mediaIds).toEqual([101, 102, 103])
        expect(lastCallProps.annotationIds).toHaveLength(30)
    })

    it("disables Assignment with permission tooltip when any selected annotation cannot be assigned", async () => {
        const items = [
            {
                annotation_id: 1,
                uuid: "00000000-0000-0000-0000-000000000001",
                media_id: 101,
                media_name: "a.wav",
                media_type: "audio",
                min_x: 0,
                max_x: 1,
                min_y: 100,
                max_y: 500,
                reference: false,
                capabilities: { edit: true, delete: true, assign: true, create_review: true },
            },
            {
                annotation_id: 2,
                uuid: "00000000-0000-0000-0000-000000000002",
                media_id: 102,
                media_name: "b.wav",
                media_type: "audio",
                min_x: 0,
                max_x: 1,
                min_y: 100,
                max_y: 500,
                reference: false,
                capabilities: { edit: true, delete: true, assign: false, create_review: true },
            },
        ]

        vi.mocked(annotationsApi.getList).mockResolvedValue({
            code: 0,
            message: "success",
            data: items as never,
            page_info: { page: 1, page_size: 50, total: 2, total_pages: 1 },
        })

        render(
            <MemoryRouter>
                <AnnotationsPage />
            </MemoryRouter>,
        )

        await waitFor(() => {
            expect(screen.getByTestId("row-count")).toHaveTextContent("2")
        })

        const assignBtn = screen.getByRole("button", { name: /Assignment/i })
        expect(assignBtn).toBeDisabled()
        expect(assignBtn).toHaveAttribute("title", "You do not have permission to assign tasks")
    })
})
