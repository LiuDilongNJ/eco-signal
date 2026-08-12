import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { LoginModal } from "./LoginModal"

describe("LoginModal validation", () => {
    afterEach(() => {
        document.getElementById(APP_OVERLAY_ROOT_ID)?.remove()
    })

    it("uses inline field errors instead of the browser required tooltip", () => {
        const overlay = document.createElement("div")
        overlay.id = APP_OVERLAY_ROOT_ID
        document.body.append(overlay)

        render(
            <LoginModal
                isOpen
                onClose={vi.fn()}
                onSuccess={vi.fn()}
            />,
        )

        const form = screen.getByRole("dialog", { name: "Welcome Back" }).querySelector("form")
        expect(form).toHaveAttribute("novalidate")

        fireEvent.click(screen.getByRole("button", { name: "LOGIN" }))

        expect(screen.getByText("Username is required")).toBeInTheDocument()
        expect(screen.getByText("Password is required")).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: "Username" })).toHaveClass("login-form-input--error")
    })

    it("explains when the login is required by inactivity timeout", () => {
        const overlay = document.createElement("div")
        overlay.id = APP_OVERLAY_ROOT_ID
        document.body.append(overlay)

        render(
            <LoginModal
                isOpen
                sessionExpired
                idleTimeoutSeconds={1800}
                onClose={vi.fn()}
                onSuccess={vi.fn()}
            />,
        )

        expect(screen.getByRole("status")).toHaveTextContent(
            "Your session expired after 30 minutes of inactivity. Please log in again.",
        )
    })
})
