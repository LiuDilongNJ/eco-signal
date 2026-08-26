import { beforeEach, describe, expect, it, vi } from "vitest"

const { get, post, deleteRequest } = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    deleteRequest: vi.fn(),
}))

vi.mock("../client", () => ({
    apiClient: {
        get,
        post,
        delete: deleteRequest,
    },
}))

import { recordersApi } from "./recorders"

describe("recordersApi microphone associations", () => {
    beforeEach(() => vi.clearAllMocks())

    it("maps add and remove requests to the recorder microphone endpoints", () => {
        const body = { microphone_id: 8, is_default: true, notes: "primary" }

        recordersApi.addMicrophone(4, body)
        recordersApi.removeMicrophone(4, 8)

        expect(post).toHaveBeenCalledWith("/v1/recorders/4/microphones", body)
        expect(deleteRequest).toHaveBeenCalledWith("/v1/recorders/4/microphones/8")
    })
})
