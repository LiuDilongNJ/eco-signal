import { describe, expect, it } from "vitest"

import { formatStorageBytes, storageHealthLabel } from "./storageStatus"

describe("storage status presentation", () => {
    it("formats byte quantities for the server storage card", () => {
        expect(formatStorageBytes(0)).toBe("0.0 B")
        expect(formatStorageBytes(1024)).toBe("1.0 KB")
        expect(formatStorageBytes(1073741824)).toBe("1.0 GB")
        expect(formatStorageBytes(1099511627776)).toBe("1.0 TB")
    })

    it("uses accessible text labels for each status", () => {
        expect(storageHealthLabel("healthy")).toBe("Normal")
        expect(storageHealthLabel("warning")).toBe("Warning")
        expect(storageHealthLabel("critical")).toBe("Critical")
    })
})
