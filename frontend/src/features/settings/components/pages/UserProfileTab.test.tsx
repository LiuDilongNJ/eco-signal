import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeAll, describe, expect, it, vi } from "vitest"

import { UserProfileTab } from "./UserProfileTab"

const { getMe } = vi.hoisted(() => ({
    getMe: vi.fn().mockResolvedValue({
        data: {
            user_id: 1,
            username: "ada",
            name: "Ada",
            email: "ada@example.com",
            orcid: null,
            color: "#83CD20",
        },
    }),
}))

vi.mock("../../../../api/endpoints/users", () => ({
    usersApi: {
        getMe,
        updateMe: vi.fn(),
        updateMyPassword: vi.fn(),
    },
}))

vi.mock("@/components/ui", async (importOriginal) => ({
    ...await importOriginal<typeof import("@/components/ui")>(),
    CustomScrollArea: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

beforeAll(() => {
    const getComputedStyle = window.getComputedStyle.bind(window)
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) => getComputedStyle(element))
    Object.defineProperty(window, "matchMedia", {
        writable: true,
        value: vi.fn().mockImplementation(() => ({
            matches: false,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        })),
    })
})

describe("UserProfileTab labels", () => {
    it("does not show required markers on profile and password labels", async () => {
        const { container } = render(<UserProfileTab />)

        await screen.findByDisplayValue("Ada")
        expect(container.querySelector('label[for="prof-name"]')).toHaveTextContent("Name")
        expect(container.querySelector('label[for="prof-name"]')).not.toHaveTextContent("Name*")
        expect(container.querySelector('label[for="prof-email"]')).toHaveTextContent("Email")
        expect(container.querySelector('label[for="prof-email"]')).not.toHaveTextContent("Email*")
        expect(container.querySelector('label[for="prof-color"]')).toHaveTextContent("Color")
        expect(container.querySelector('label[for="prof-color"]')).not.toHaveTextContent("Color*")
        expect(container.querySelector('label[for="prof-orcid"]')).toHaveTextContent("ORCID")
        expect(container.querySelector('label[for="prof-orcid"] .form-drawer-required-suffix')).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Change Password" }))

        await waitFor(() => {
            const labels = document.querySelectorAll(".settings-form-modal-field-label")
            expect(labels).toHaveLength(2)
            expect(labels[0]).toHaveTextContent("Current Password")
            expect(labels[1]).toHaveTextContent("New Password")
            expect(labels[0]).not.toHaveTextContent("Current Password*")
            expect(labels[1]).not.toHaveTextContent("New Password*")
        })
    })
})
