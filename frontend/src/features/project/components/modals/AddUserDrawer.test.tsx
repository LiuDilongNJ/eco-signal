import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AddUserDrawer } from "./AddUserDrawer"

const { getUser } = vi.hoisted(() => ({ getUser: vi.fn() }))

vi.mock("../../../../api/endpoints/users", () => ({ usersApi: { getUser } }))
vi.mock("@/components/ui", async (importOriginal) => ({
    ...await importOriginal<typeof import("@/components/ui")>(),
    CustomScrollArea: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

afterEach(cleanup)
beforeEach(() => {
    getUser.mockResolvedValue({
        code: 0,
        data: { name: "Color User", email: "color@example.com", color: "#FFFFFF", active: true },
    })
})

describe("AddUserDrawer color submission", () => {
    it.each([false, true])("submits picker color with edit mode %s", async (edit) => {
        const onSubmit = vi.fn()
        render(<MemoryRouter><AddUserDrawer open editId={edit ? 42 : null} onClose={vi.fn()} onSubmit={onSubmit} /></MemoryRouter>)
        if (edit) {
            await screen.findByDisplayValue("Color User")
        } else {
            fireEvent.focus(screen.getByLabelText(/^Username/))
            fireEvent.change(screen.getByLabelText(/^Username/), { target: { value: "coloruser" } })
            fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "ColorPass123!" } })
            fireEvent.change(screen.getByLabelText(/^Confirm Password/), { target: { value: "ColorPass123!" } })
            fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "Color User" } })
            fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: "color@example.com" } })
        }
        fireEvent.change(screen.getByLabelText("User color"), { target: { value: "#11aa33" } })
        await waitFor(() => expect(screen.getByLabelText("Color")).toHaveValue("#11AA33"))
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ color: "#11AA33" })))
    })

    it("submits typed color and updates the picker", async () => {
        const onSubmit = vi.fn()
        render(<MemoryRouter><AddUserDrawer open editId={42} onClose={vi.fn()} onSubmit={onSubmit} /></MemoryRouter>)
        await screen.findByDisplayValue("Color User")
        fireEvent.change(screen.getByLabelText("Color"), { target: { value: "#abcdef" } })
        await waitFor(() => expect(screen.getByLabelText("User color")).toHaveValue("#abcdef"))
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ color: "#abcdef" })))
    })
})
