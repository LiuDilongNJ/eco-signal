import { describe, expect, it } from "vitest"
import { formatAuditTimestamp, pendingTaxonAudit } from "./SetTaxonsDrawer"

describe("pending taxon audit metadata", () => {
    it("formats the local Add timestamp in the collection display format", () => {
        const date = new Date(2026, 7, 21, 7, 43, 17)

        expect(formatAuditTimestamp(date)).toBe("2026-08-21 07:43:17")
    })

    it("uses the current user immediately and falls back clearly when unavailable", () => {
        const date = new Date(2026, 7, 21, 7, 43, 17)

        expect(pendingTaxonAudit(" Administrator ", date)).toEqual({
            asserted_by: null,
            asserted_by_name: "Administrator",
            asserted_at: "2026-08-21 07:43:17",
        })
        expect(pendingTaxonAudit("", date).asserted_by_name).toBe("Current user")
    })
})
