import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { renderRequiredLabel, renderRequiredMark } from "./formLabels"

describe("form labels", () => {
    it("renders the required marker after the label", () => {
        const { container } = render(<label>{renderRequiredLabel("Name")}</label>)

        expect(container.querySelector("label")).toHaveTextContent("Name*")
        expect(container.querySelector(".form-drawer-required-suffix")).toHaveTextContent("*")
    })

    it("does not render a marker for optional fields", () => {
        const { container } = render(<label>{renderRequiredMark("Name", { required: false })}</label>)

        expect(container.querySelector("label")).toHaveTextContent("Name")
        expect(container.querySelector(".form-drawer-required-suffix")).not.toBeInTheDocument()
    })
})
