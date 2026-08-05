import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Settings } from "lucide-react"
import { describe, expect, it, vi } from "vitest"
import { IconButton } from "./Button"

describe("IconButton", () => {
    it("exposes its label and forwards interaction", async () => {
        const onClick = vi.fn()
        render(<IconButton icon={<Settings />} label="Settings" onClick={onClick} />)

        const button = screen.getByRole("button", { name: "Settings" })
        expect(button).toHaveAttribute("title", "Settings")
        await userEvent.click(button)
        expect(onClick).toHaveBeenCalledOnce()
    })

    it("exposes pressed state", () => {
        render(<IconButton icon={<Settings />} label="Settings" pressed />)
        expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("aria-pressed", "true")
    })
})
