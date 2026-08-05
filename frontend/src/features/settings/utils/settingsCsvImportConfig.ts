export interface CsvImportFieldInstruction {
    name: string
    rules: string
    description: string
}

export interface SettingsCsvImportConfig {
    subject: string
    templateFileName: string
    template: string
    fields: CsvImportFieldInstruction[]
}

export const SETTINGS_CSV_IMPORT_CONFIG = {
    sounds: {
        subject: "Sound",
        templateFileName: "sounds_template.csv",
        template: "soundscape_component,sound_type\nbiophony,snapping shrimps\n",
        fields: [
            { name: "soundscape_component", rules: "required, max 200 characters", description: "Main soundscape category: biophony, anthropophony, or geophony" },
            { name: "sound_type", rules: "optional, max 30 characters", description: "Specific sound type or description" },
        ],
    },
    taxons: {
        subject: "Taxon",
        templateFileName: "taxons_template.csv",
        template: "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\nCorvus cornix,Hooded Crow,Corvus,Corvidae,Passeriformes,Aves,CatalogueOfLife-XR\n",
        fields: [
            { name: "cached_scientific_name", rules: "required, max 100 characters", description: 'Scientific name in format "Genus species"' },
            { name: "cached_common_name", rules: "required, max 200 characters", description: "Common name of the taxon" },
            { name: "col_genus_name", rules: "optional, max 100 characters", description: "Genus name" },
            { name: "col_family_name", rules: "optional, max 100 characters", description: "Family name" },
            { name: "col_order_name", rules: "optional, max 100 characters", description: "Taxonomic order" },
            { name: "col_class_name", rules: "optional, max 100 characters", description: "Taxonomic class" },
            { name: "taxonomy_source", rules: "required, max 50 characters", description: "Data source identifier" },
        ],
    },
    cameras: {
        subject: "Camera",
        templateFileName: "cameras_template.csv",
        template: "name,version,brand\nEOS R5,Mark II,Canon\n",
        fields: [
            { name: "name", rules: "required, max 100 characters", description: "Camera model name" },
            { name: "version", rules: "optional, max 100 characters", description: "Version or model number" },
            { name: "brand", rules: "optional, max 100 characters", description: "Manufacturer or brand name" },
        ],
    },
    lenses: {
        subject: "Lens",
        templateFileName: "lenses_template.csv",
        template: "name,focal_length,max_aperture,brand\nRF 24-70mm,24-70mm,f/2.8,Canon\n",
        fields: [
            { name: "name", rules: "required, max 100 characters", description: "Lens model name" },
            { name: "focal_length", rules: "optional, max 50 characters", description: "Focal length or focal range" },
            { name: "max_aperture", rules: "optional, max 20 characters", description: "Maximum aperture" },
            { name: "brand", rules: "optional, max 100 characters", description: "Manufacturer or brand name" },
        ],
    },
    microphones: {
        subject: "Microphone",
        templateFileName: "microphones_template.csv",
        template: "name,microphone_element,sensitivity,signal_to_noise_ratio\nMAARU (built-in microphone),MSM321A3729H9CP,-32,80\n",
        fields: [
            { name: "name", rules: "required, max 100 characters", description: "Microphone name/model" },
            { name: "microphone_element", rules: "optional, max 100 characters", description: "Type of microphone element" },
            { name: "sensitivity", rules: "optional, integer", description: "Sensitivity in dBV" },
            { name: "signal_to_noise_ratio", rules: "optional, integer", description: "Signal-to-noise ratio in dB" },
        ],
    },
    recorders: {
        subject: "Recorder",
        templateFileName: "recorders_template.csv",
        template: "name,version,brand\nSong Meter SM4,4.0,Wildlife Acoustics\n",
        fields: [
            { name: "name", rules: "required, max 100 characters", description: "Recorder model name" },
            { name: "version", rules: "optional, max 100 characters", description: "Version or model number" },
            { name: "brand", rules: "optional, max 100 characters", description: "Manufacturer/brand name" },
        ],
    },
} satisfies Record<string, SettingsCsvImportConfig>
