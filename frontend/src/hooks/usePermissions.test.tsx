// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
    getMyPermissions: vi.fn(),
    getToken: vi.fn(() => "token-a" as string | null),
}))

vi.mock("@/api/endpoints/users", () => ({
    usersApi: { getMyPermissions: mocks.getMyPermissions },
}))

vi.mock("@/utils/auth", () => ({
    authUtils: { getToken: mocks.getToken },
}))

import { usePermissions } from "./usePermissions"

function respondWith(permissions: string[], isAdmin = false) {
    mocks.getMyPermissions.mockResolvedValue({
        code: 0,
        message: "success",
        data: { is_admin: isAdmin, project_id: 1, collection_id: null, permissions },
    })
}

function wrapper({ children }: { children: ReactNode }) {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe("usePermissions", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mocks.getToken.mockReturnValue("token-a")
    })

    it("denies every permission while loading", () => {
        respondWith(["review:write"])

        const { result } = renderHook(() => usePermissions(1, 10), { wrapper })

        expect(result.current.isLoading).toBe(true)
        expect(result.current.can("review:write")).toBe(false)
    })

    it("grants a permission returned by the API", async () => {
        respondWith(["review:read", "review:write"])

        const { result } = renderHook(() => usePermissions(1, 10), { wrapper })

        await waitFor(() => expect(result.current.isLoading).toBe(false))
        expect(result.current.can("review:write")).toBe(true)
        expect(result.current.can("review:read")).toBe(true)
    })

    it("denies a permission the API did not return", async () => {
        respondWith(["review:read"])

        const { result } = renderHook(() => usePermissions(1, 10), { wrapper })

        await waitFor(() => expect(result.current.isLoading).toBe(false))
        expect(result.current.can("review:read")).toBe(true)
        expect(result.current.can("review:write")).toBe(false)
    })

    it("grants everything to an admin regardless of the returned list", async () => {
        respondWith([], true)

        const { result } = renderHook(() => usePermissions(1, 10), { wrapper })

        await waitFor(() => expect(result.current.isLoading).toBe(false))
        expect(result.current.isAdmin).toBe(true)
        expect(result.current.can("project:write")).toBe(true)
    })

    it("denies everything when the request fails", async () => {
        mocks.getMyPermissions.mockRejectedValue(new Error("network down"))

        const { result } = renderHook(() => usePermissions(1, 10), { wrapper })

        await waitFor(() => expect(result.current.isLoading).toBe(false))
        expect(result.current.can("review:write")).toBe(false)
    })

    it("drops the collection scope when no project is given", async () => {
        respondWith(["review:write"])

        const { result } = renderHook(() => usePermissions(null, 10), { wrapper })

        await waitFor(() => expect(result.current.isLoading).toBe(false))
        expect(mocks.getMyPermissions).toHaveBeenCalledWith({
            project_id: undefined,
            collection_id: undefined,
        })
    })

    it('treats the "all" collection view as an unscoped project query', async () => {
        respondWith(["audio:write"])

        const { result } = renderHook(() => usePermissions(1, "all"), { wrapper })

        await waitFor(() => expect(result.current.isLoading).toBe(false))
        expect(mocks.getMyPermissions).toHaveBeenCalledWith({
            project_id: 1,
            collection_id: undefined,
        })
    })
})
