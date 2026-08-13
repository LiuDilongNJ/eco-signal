import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import NotFoundPage from "./NotFoundPage"

describe("NotFoundPage", () => {
    it("renders the 404 message and links back to the dashboard", () => {
        render(
            <MemoryRouter>
                <NotFoundPage />
            </MemoryRouter>,
        )

        expect(screen.getByText("404")).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Page Not Found" })).toBeInTheDocument()
        expect(screen.getByText("The page you are looking for does not exist or has been removed.")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Back to Dashboard" })).toHaveAttribute("href", "/dashboard")
        expect(screen.getByRole("link", { name: "Back to Dashboard" })).toHaveClass("es-button")
    })
})
