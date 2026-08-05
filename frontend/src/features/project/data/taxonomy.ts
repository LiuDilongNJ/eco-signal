/**
 * 生态分类体系
 */

export const TAXONOMY: Record<string, Record<string, string[]>> = {
    Terrestrial: {
        "Tropical Forests": ["Lowland Rainforest", "Montane Rainforest"],
        Savannas: ["Shrubland", "Grassland"],
    },
    Marine: {
        Coastal: ["Coral Reefs", "Seagrass"],
        Pelagic: ["Epipelagic", "Mesopelagic"],
    },
    Freshwater: {
        Riverine: ["Headwater", "Floodplain"],
        Lacustrine: ["Littoral Zone", "Pelagic Zone"],
    },
    Subterranean: {
        "Cave Systems": ["Limestone Caves", "Lava Tubes"],
        Groundwater: ["Aquifers", "Karst"],
    },
}

export const ALL_REALMS = Object.keys(TAXONOMY)

export const ALL_FUNCTIONAL_TYPES = Array.from(
    new Set(Object.values(TAXONOMY).flatMap((r) => Object.values(r).flat()))
).sort()
