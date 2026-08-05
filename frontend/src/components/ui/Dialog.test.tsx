import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { Dialog } from "./Dialog"

function addOverlayRoot() {
    const overlay = document.createElement("div")
    overlay.id = APP_OVERLAY_ROOT_ID
    document.body.append(overlay)
    return overlay
}

describe("Dialog", () => {
    it("has dialog semantics and closes from its named close action", async () => {
        const overlay = addOverlayRoot()
        const onClose = vi.fn()
        render(<Dialog open title="Edit record" onClose={onClose}>Content</Dialog>)

        expect(screen.getByRole("dialog", { name: "Edit record" })).toBeInTheDocument()
        const close = screen.getByRole("button", { name: "Close" })
        expect(close).toHaveFocus()
        await userEvent.click(close)
        expect(onClose).toHaveBeenCalledOnce()
        overlay.remove()
    })

    it("closes on Escape", async () => {
        const overlay = addOverlayRoot()
        const onClose = vi.fn()
        render(<Dialog open onClose={onClose}>Content</Dialog>)

        expect(screen.getByRole("dialog", { name: "Dialog" })).toBeInTheDocument()
        await userEvent.keyboard("{Escape}")
        expect(onClose).toHaveBeenCalledOnce()
        overlay.remove()
    })
})
