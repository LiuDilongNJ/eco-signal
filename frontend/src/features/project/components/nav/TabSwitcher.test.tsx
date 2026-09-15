// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { TabSwitcher } from "./TabSwitcher"
import { useTabStore } from "../../stores/useTabStore"
import { useProjectStore } from "../../stores/useProjectStore"

const mocks = vi.hoisted(() => ({
    usePermissions: vi.fn(),
    getToken: vi.fn(() => "mock-token" as string | null),
}))

vi.mock("@/hooks/usePermissions", () => ({
    usePermissions: (...args: unknown[]) => mocks.usePermissions(...args),
}))

vi.mock("@/utils/auth", () => ({
    authUtils: { getToken: mocks.getToken },
}))

describe("TabSwitcher", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useTabStore.setState({ activeTab: "desc" })
        useProjectStore.setState({ currentProjectId: 1, currentCollectionId: 10 })
    })

    it("renders all tabs when user has media:read and site:read permissions", () => {
        mocks.usePermissions.mockReturnValue({
            can: (perm: string) => perm === "media:read" || perm === "site:read",
            isAdmin: false,
            isLoading: false,
            permissions: ["media:read", "site:read"],
        })

        render(<TabSwitcher />)

        expect(screen.getByText("Description")).toBeInTheDocument()
        expect(screen.getByText("Summary")).toBeInTheDocument()
        expect(screen.getByText("Media")).toBeInTheDocument()
        expect(screen.getByText("Map")).toBeInTheDocument()
        expect(screen.getByText("Timeline")).toBeInTheDocument()
        expect(screen.getByText("Data")).toBeInTheDocument()
    })

    it("hides Media and Timeline tabs when user lacks media:read permission", () => {
        mocks.usePermissions.mockReturnValue({
            can: (perm: string) => perm === "site:read" || perm === "annotation:read",
            isAdmin: false,
            isLoading: false,
            permissions: ["site:read", "annotation:read"],
        })

        render(<TabSwitcher />)

        expect(screen.getByText("Description")).toBeInTheDocument()
        expect(screen.getByText("Summary")).toBeInTheDocument()
        expect(screen.queryByText("Media")).not.toBeInTheDocument()
        expect(screen.getByText("Map")).toBeInTheDocument()
        expect(screen.queryByText("Timeline")).not.toBeInTheDocument()
        expect(screen.getByText("Data")).toBeInTheDocument()
    })

    it("hides Map tab when user lacks site:read permission", () => {
        mocks.usePermissions.mockReturnValue({
            can: (perm: string) => perm === "media:read",
            isAdmin: false,
            isLoading: false,
            permissions: ["media:read"],
        })

        render(<TabSwitcher />)

        expect(screen.getByText("Description")).toBeInTheDocument()
        expect(screen.getByText("Summary")).toBeInTheDocument()
        expect(screen.getByText("Media")).toBeInTheDocument()
        expect(screen.queryByText("Map")).not.toBeInTheDocument()
        expect(screen.getByText("Timeline")).toBeInTheDocument()
        expect(screen.getByText("Data")).toBeInTheDocument()
    })

    it("redirects activeTab to desc if current activeTab becomes hidden", async () => {
        useTabStore.setState({ activeTab: "media" })

        mocks.usePermissions.mockReturnValue({
            can: () => false,
            isAdmin: false,
            isLoading: false,
            permissions: [],
        })

        render(<TabSwitcher />)

        await waitFor(() => {
            expect(useTabStore.getState().activeTab).toBe("desc")
        })
        expect(screen.queryByText("Media")).not.toBeInTheDocument()
    })

    it("renders all tabs while permissions are loading to avoid flash of missing tabs", () => {
        mocks.usePermissions.mockReturnValue({
            can: () => false,
            isAdmin: false,
            isLoading: true,
            permissions: [],
        })

        render(<TabSwitcher />)

        expect(screen.getByText("Description")).toBeInTheDocument()
        expect(screen.getByText("Media")).toBeInTheDocument()
        expect(screen.getByText("Timeline")).toBeInTheDocument()
        expect(screen.getByText("Map")).toBeInTheDocument()
    })
})
