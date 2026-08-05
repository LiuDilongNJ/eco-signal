import { beforeEach, describe, expect, it, vi } from "vitest"

const { download } = vi.hoisted(() => ({
    download: vi.fn(),
}))

vi.mock("../client", () => ({
    apiClient: {
        download,
    },
}))

import { tasksApi } from "./tasks"

describe("tasksApi", () => {
    beforeEach(() => vi.clearAllMocks())

    it("exports tasks within the selected project and collection", () => {
        tasksApi.exportCsv({
            project_id: 12,
            collection_id: 34,
            order_by: "task_id",
            order_dir: "desc",
        })

        expect(download).toHaveBeenCalledWith("/v1/tasks/exports", {
            params: {
                project_id: 12,
                collection_id: 34,
                order_by: "task_id",
                order_dir: "desc",
            },
        })
    })
})
