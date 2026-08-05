import { render, within } from "@testing-library/react"
import { beforeAll, describe, expect, it, vi } from "vitest"

import { AnalysisResultModal } from "./AnalysisResultModal"

beforeAll(() => {
    const getComputedStyle = window.getComputedStyle.bind(window)
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) => getComputedStyle(element))
})

describe("AnalysisResultModal actions", () => {
    it("uses OK for a read-only result", () => {
        render(
            <AnalysisResultModal
                open
                title="Analysis complete"
                items={[{ label: "Result", value: "Complete" }]}
                onClose={vi.fn()}
            />,
        )

        const footer = document.querySelector(".ant-modal-footer")
        expect(footer).not.toBeNull()
        expect(within(footer as HTMLElement).getByRole("button", { name: "OK" })).toBeInTheDocument()
    })

    it("keeps Save and Close for a saveable preview", () => {
        render(
            <AnalysisResultModal
                open
                title="Analysis preview"
                items={[{ label: "Result", value: "Preview" }]}
                onClose={vi.fn()}
                onSave={vi.fn()}
            />,
        )

        const footers = document.querySelectorAll(".ant-modal-footer")
        const footer = footers[footers.length - 1]
        expect(footer).toBeDefined()
        expect(within(footer as HTMLElement).getByRole("button", { name: "Save" })).toBeInTheDocument()
        expect(within(footer as HTMLElement).getByRole("button", { name: "Close" })).toBeInTheDocument()
    })
})
