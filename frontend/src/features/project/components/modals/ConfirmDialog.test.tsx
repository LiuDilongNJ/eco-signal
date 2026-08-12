import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { ConfirmDialog } from "./ConfirmDialog"

function addOverlayRoot() {
    const overlay = document.createElement("div")
    overlay.id = APP_OVERLAY_ROOT_ID
    document.body.append(overlay)
    return overlay
}

describe("ConfirmDialog typed confirmation", () => {
    it("requires the exact confirmation text before enabling deletion", async () => {
        const overlay = addOverlayRoot()
        const onClose = vi.fn()
        const onConfirm = vi.fn()

        render(
            <ConfirmDialog
                open
                title="Delete project"
                message="This action cannot be undone."
                confirmLabel="Delete"
                variant="danger"
                confirmationText="Forest Sounds"
                onClose={onClose}
                onConfirm={onConfirm}
            />,
        )

        const deleteButton = screen.getByRole("button", { name: "Delete" })
        const input = screen.getByRole("textbox", { name: /Type Forest Sounds to confirm/i })
        expect(input).toHaveClass("es-input")
        expect(deleteButton).toBeDisabled()

        await userEvent.type(input, "forest sounds")
        expect(deleteButton).toBeDisabled()

        await userEvent.clear(input)
        await userEvent.type(input, "Forest Sounds")
        expect(deleteButton).toBeEnabled()

        await userEvent.click(deleteButton)
        expect(onConfirm).toHaveBeenCalledOnce()
        expect(onClose).toHaveBeenCalledOnce()
        overlay.remove()
    })
})
