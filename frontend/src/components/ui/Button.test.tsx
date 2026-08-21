import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Settings } from "lucide-react"
import { describe, expect, it, vi } from "vitest"
import { Button, IconButton } from "./Button"

describe("IconButton", () => {
    it("exposes its label and forwards interaction", async () => {
        const onClick = vi.fn()
        render(<IconButton icon={<Settings />} label="Settings" onClick={onClick} />)

        const button = screen.getByRole("button", { name: "Settings" })
        expect(button).toHaveAttribute("title", "Settings")
        await userEvent.click(button)
        expect(onClick).toHaveBeenCalledOnce()
    })

    it("uses an actionable tooltip without changing the accessible name", () => {
        render(<IconButton icon={<Settings />} label="Switch Theme" />)

        const button = screen.getByRole("button", { name: "Switch Theme" })
        expect(button).toHaveAttribute("title", "Switch between light, dark, and automatic themes")
    })

    it("allows a context-specific tooltip", () => {
        render(<IconButton icon={<Settings />} label="Settings" tooltip="Open account settings" />)

        expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("title", "Open account settings")
    })

    it("expands shared action hints for unstyled buttons", () => {
        render(<Button appearance="unstyled" title="Delete">Delete</Button>)

        expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute("title", "Delete the selected records")
    })

    it("exposes pressed state", () => {
        render(<IconButton icon={<Settings />} label="Settings" pressed />)
        expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("aria-pressed", "true")
    })
})
