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
        expect(screen.getByRole("heading", { name: "页面不存在" })).toBeInTheDocument()
        expect(screen.getByText("您访问的页面不存在或已被移除")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "返回首页" })).toHaveAttribute("href", "/dashboard")
    })
})
