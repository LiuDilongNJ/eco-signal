import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { AssociationRequestHelp } from "./AssociationRequestHelp"

describe("AssociationRequestHelp", () => {
    it("links requests for compatible combinations to GitHub Issues", () => {
        render(<AssociationRequestHelp subject="recorders, microphones" />)

        expect(screen.getByRole("link", { name: "If you want to add new, valid recorders, microphones, or their combinations to the ecoSignal database, please file an issue here: https://github.com/LiuDilongNJ/eco-signal/issues" })).toHaveAttribute(
            "href",
            "https://github.com/LiuDilongNJ/eco-signal/issues",
        )
        expect(screen.getByRole("link")).toHaveAccessibleName(
            "If you want to add new, valid recorders, microphones, or their combinations to the ecoSignal database, please file an issue here: https://github.com/LiuDilongNJ/eco-signal/issues",
        )
        expect(screen.getByRole("link")).toHaveAttribute("target", "_blank")
        expect(screen.getByRole("link")).toHaveAttribute("rel", "noreferrer")
    })
})
