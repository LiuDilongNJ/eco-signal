import { render } from "@testing-library/react"
import type { ReactNode } from "react"
import { vi, describe, expect, it } from "vitest"

const { tooltipProps } = vi.hoisted(() => ({
    tooltipProps: vi.fn(),
}))

vi.mock("antd", () => ({
    Tooltip: (props: Record<string, unknown>) => {
        tooltipProps(props)
        return <div>{props.children as ReactNode}</div>
    },
    Popover: (props: Record<string, unknown>) => <div>{props.children as ReactNode}</div>,
}))

import { Tooltip } from "./Floating"

describe("Tooltip", () => {
    it("waits briefly before showing by default", () => {
        render(
            <Tooltip title="Open details">
                <button type="button">Details</button>
            </Tooltip>,
        )

        expect(tooltipProps).toHaveBeenCalledWith(expect.objectContaining({ mouseEnterDelay: 0.5 }))
    })
})
