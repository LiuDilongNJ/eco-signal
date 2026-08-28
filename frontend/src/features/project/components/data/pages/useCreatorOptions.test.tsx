// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const api = vi.hoisted(() => ({
    getMe: vi.fn(),
    getCreatorOptions: vi.fn(),
}))

vi.mock("../../../../../api/endpoints/users", () => ({
    usersApi: api,
}))

import { useCreatorOptions } from "./useCreatorOptions"

const currentUser = {
    user_id: 9,
    name: "Creator User",
    username: "creator-user",
}

describe("useCreatorOptions", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("does not load Creator candidates for a read-only project scope", async () => {
        api.getMe.mockResolvedValue({
            data: { ...currentUser, can_write_audio: false },
        })

        const { result } = renderHook(() => useCreatorOptions(122, 1514))

        await waitFor(() => expect(result.current.currentUserId).toBe(currentUser.user_id))
        expect(api.getMe).toHaveBeenCalledWith({ project_id: 122, collection_id: 1514 })
        expect(api.getCreatorOptions).not.toHaveBeenCalled()
        expect(result.current.creatorOptions).toEqual([])
    })

    it("loads Creator candidates only when the scope allows audio writes", async () => {
        api.getMe.mockResolvedValue({
            data: { ...currentUser, can_write_audio: true },
        })
        api.getCreatorOptions.mockResolvedValue({
            data: [{ user_id: 10, name: "Another User", username: "another-user" }],
        })

        const { result } = renderHook(() => useCreatorOptions(122, ""))

        await waitFor(() => expect(api.getCreatorOptions).toHaveBeenCalledWith({ project_id: 122 }))
        expect(api.getMe).toHaveBeenCalledWith({ project_id: 122 })
        expect(result.current.creatorOptions).toEqual([
            currentUser,
            { user_id: 10, name: "Another User", username: "another-user" },
        ])
    })
})
