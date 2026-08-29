export interface ImportFieldInstruction {
    name: string
    rules: string
    description: string
}

export interface ImportResourceConfig {
    subject: string
    templateFileName: string
    template: string
    example: Record<string, string | number | boolean | object | null>
    additionalExample: Record<string, string | number | boolean | object | null>
    fields: ImportFieldInstruction[]
}

export type ImportResourceKey = keyof typeof IMPORT_RESOURCE_CONFIGS

const field = (name: string, rules: string, description: string): ImportFieldInstruction => ({ name, rules, description })

export const IMPORT_RESOURCE_CONFIGS = {
    projects: {
        subject: "Project",
        templateFileName: "projects_template.csv",
        template: "name,url,description,description_short,doi,public,active\nForest Monitoring,https://example.org/forest,Long-term forest monitoring,Forest sounds,10.0000/example,true,true\nRiver Monitoring,https://example.org/river,Long-term river monitoring,River sounds,10.0000/river,true,true\n",
        example: { name: "Forest Monitoring", url: "https://example.org/forest", description: "Long-term forest monitoring", description_short: "Forest sounds", doi: "10.0000/example", public: true, active: true },
        additionalExample: { name: "River Monitoring", url: "https://example.org/river", description: "Long-term river monitoring", description_short: "River sounds", doi: "10.0000/river", public: true, active: true },
        fields: [
            field("name", "required, max 100 characters", "Project name"),
            field("url", "optional, max 255 characters, HTTP/HTTPS URL", "Project website"),
            field("description", "optional", "Full project description"),
            field("description_short", "optional", "Short project description"),
            field("doi", "optional, max 255 characters", "Digital Object Identifier"),
            field("public", "optional boolean, default true", "Whether the project is public"),
            field("active", "optional boolean, default true", "Whether the project is active"),
        ],
    },
    collections: {
        subject: "Collection",
        templateFileName: "collections_template.csv",
        template: "name,doi,description,sphere,external_media_url,project_url,public_access,public_tags\nForest 2026,10.0000/collection,Forest recordings,biosphere,https://media.example.org,https://example.org/forest,false,false\nRiver 2026,10.0000/river-collection,River recordings,hydrosphere,https://media.example.org,https://example.org/river,false,false\n",
        example: { name: "Forest 2026", doi: "10.0000/collection", description: "Forest recordings", sphere: "biosphere", external_media_url: "https://media.example.org", project_url: "https://example.org/forest", public_access: false, public_tags: false },
        additionalExample: { name: "River 2026", doi: "10.0000/river-collection", description: "River recordings", sphere: "hydrosphere", external_media_url: "https://media.example.org", project_url: "https://example.org/river", public_access: false, public_tags: false },
        fields: [
            field("name", "required, max 100 characters", "Collection name"),
            field("doi", "optional, max 255 characters", "Digital Object Identifier"),
            field("description", "optional", "Collection description"),
            field("sphere", "optional: hydrosphere, cryosphere, lithosphere, pedosphere, atmosphere, biosphere, or anthroposphere", "Environmental sphere"),
            field("external_media_url", "optional, HTTP/HTTPS URL", "External media location"),
            field("project_url", "optional, HTTP/HTTPS URL", "Related project page"),
            field("public_access", "optional boolean, default false", "Whether collection media is public"),
            field("public_tags", "optional boolean, default false", "Whether annotations are public"),
        ],
    },
    sites: {
        subject: "Site",
        templateFileName: "sites_template.csv",
        template: "name,longitude,latitude,topography_m,freshwater_depth_m,realm_id,biome_id,functional_type_id,iho_id,gadm0_gid,gadm1_gid,gadm2_gid\nForest Site,118.778,32.043,120,,,,,,,,\nRiver Site,118.900,32.100,,5,,,,,,,\n",
        example: { name: "Forest Site", longitude: 118.778, latitude: 32.043, topography_m: 120, freshwater_depth_m: null, realm_id: null, biome_id: null, functional_type_id: null, iho_id: null, gadm0_gid: null, gadm1_gid: null, gadm2_gid: null },
        additionalExample: { name: "River Site", longitude: 118.9, latitude: 32.1, topography_m: null, freshwater_depth_m: 5, realm_id: null, biome_id: null, functional_type_id: null, iho_id: null, gadm0_gid: null, gadm1_gid: null, gadm2_gid: null },
        fields: [
            field("name", "required", "Site name"),
            field("longitude", "required with latitude, -180 to 180", "WGS84 longitude"),
            field("latitude", "required with longitude, -90 to 90", "WGS84 latitude"),
            field("topography_m", "optional number", "Elevation or underwater depth in metres"),
            field("freshwater_depth_m", "optional number", "Freshwater depth in metres"),
            field("realm_id", "optional integer", "IUCN realm identifier"),
            field("biome_id", "optional integer", "IUCN biome identifier"),
            field("functional_type_id", "optional integer", "IUCN functional type identifier"),
            field("iho_id", "optional integer", "IHO sea area identifier; may replace coordinates"),
            field("gadm0_gid", "optional string", "GADM country identifier; may replace coordinates"),
            field("gadm1_gid", "optional string; requires gadm0_gid", "GADM level 1 identifier"),
            field("gadm2_gid", "optional string; requires gadm0_gid", "GADM level 2 identifier"),
        ],
    },
    audioMetadata: {
        subject: "Recording meta-data",
        templateFileName: "audio_metadata_template.csv",
        template: "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n2026-01-15 06:30:00,60,48000,Forest dawn,24,2,60,300\n2026-01-15 07:30:00,120,48000,Forest morning,24,2,120,600\n",
        example: { date_time: "2026-01-15 06:30:00", duration_s: 60, sampling_rate_hz: 48000, name: "Forest dawn", bit_depth: 24, channel_num: 2, duty_cycle_recording: 60, duty_cycle_period: 300 },
        additionalExample: { date_time: "2026-01-15 07:30:00", duration_s: 120, sampling_rate_hz: 48000, name: "Forest morning", bit_depth: 24, channel_num: 2, duty_cycle_recording: 120, duty_cycle_period: 600 },
        fields: [
            field("date_time", "required, YYYY-MM-DD HH:mm:ss", "Recording date and local time"),
            field("duration_s", "required number", "Recording duration in seconds"),
            field("sampling_rate_hz", "required number", "Sampling rate in Hz"),
            field("name", "optional, max 250 characters", "Recording name"),
            field("bit_depth", "optional integer", "Bit depth"),
            field("channel_num", "optional integer", "Number of channels"),
            field("duty_cycle_recording", "optional integer", "Recording portion of the duty cycle in seconds"),
            field("duty_cycle_period", "optional integer", "Complete duty-cycle period in seconds"),
        ],
    },
    photoMetadata: {
        subject: "Photo meta-data",
        templateFileName: "photo_metadata_template.csv",
        template: "date_time,name,exposure_ms,aperture,iso\n2026-01-15 06:30:00,Forest camera,10,2.8,400\n2026-01-15 07:30:00,River camera,8,4,200\n",
        example: { date_time: "2026-01-15 06:30:00", name: "Forest camera", exposure_ms: 10, aperture: 2.8, iso: 400 },
        additionalExample: { date_time: "2026-01-15 07:30:00", name: "River camera", exposure_ms: 8, aperture: 4, iso: 200 },
        fields: [
            field("date_time", "required, YYYY-MM-DD HH:mm:ss", "Photo date and local time"),
            field("name", "optional, max 250 characters", "Photo name"),
            field("exposure_ms", "optional number", "Exposure time in milliseconds"),
            field("aperture", "optional number", "Aperture F value"),
            field("iso", "optional integer", "ISO sensitivity"),
        ],
    },
    annotations: {
        subject: "Annotation",
        templateFileName: "annotations_template.csv",
        template: "media_id,min_x,max_x,min_y,max_y,sound_id,object_type,reference,comments,taxon_id,uncertain,sound_distance_m,distance_not_estimable,individual_num,creator_type,confidence,animal_sound_type\n101,1.5,3.2,1000,5000,1,,false,Bird call,,false,20,false,1,user,,song\n102,4,6,800,3000,1,,false,Second bird call,,false,15,false,1,user,,call\n",
        example: { media_id: 101, min_x: 1.5, max_x: 3.2, min_y: 1000, max_y: 5000, sound_id: 1, object_type: null, reference: false, comments: "Bird call", taxon_id: null, uncertain: false, sound_distance_m: 20, distance_not_estimable: false, individual_num: 1, creator_type: "user", confidence: null, animal_sound_type: "song" },
        additionalExample: { media_id: 102, min_x: 4, max_x: 6, min_y: 800, max_y: 3000, sound_id: 1, object_type: null, reference: false, comments: "Second bird call", taxon_id: null, uncertain: false, sound_distance_m: 15, distance_not_estimable: false, individual_num: 1, creator_type: "user", confidence: null, animal_sound_type: "call" },
        fields: [
            field("media_id", "required positive integer", "Media in the selected collection"),
            field("min_x", "required number", "Start time in seconds"), field("max_x", "required number", "End time in seconds"),
            field("min_y", "required number", "Minimum frequency in Hz"), field("max_y", "required number", "Maximum frequency in Hz"),
            field("sound_id", "optional positive integer", "Sound classification identifier"), field("object_type", "optional: organism or other", "Annotated object type"),
            field("reference", "optional boolean, default false", "Reference annotation"), field("comments", "optional, max 500 characters", "Annotation comments"),
            field("taxon_id", "optional integer", "Taxon identifier"), field("uncertain", "optional boolean", "Uncertainty flag"),
            field("sound_distance_m", "optional integer", "Estimated distance in metres"), field("distance_not_estimable", "optional boolean", "Distance cannot be estimated"),
            field("individual_num", "optional integer, minimum 1", "Number of individuals"), field("creator_type", "optional, default user", "Creator category"),
            field("confidence", "optional number; ignored for user creator", "Model confidence"), field("animal_sound_type", "optional, max 128 characters", "Animal sound type"),
        ],
    },
    reviews: {
        subject: "Review",
        templateFileName: "reviews_template.csv",
        template: "annotation_id,annotation_review_status_id,taxon_id,note\n501,1,,Accepted after review\n502,2,,Corrected after review\n",
        example: { annotation_id: 501, annotation_review_status_id: 1, taxon_id: null, note: "Accepted after review" },
        additionalExample: { annotation_id: 502, annotation_review_status_id: 2, taxon_id: null, note: "Corrected after review" },
        fields: [field("annotation_id", "required positive integer", "Annotation in the selected collection"), field("annotation_review_status_id", "required positive integer", "Review status identifier"), field("taxon_id", "optional positive integer", "Corrected taxon identifier"), field("note", "optional, max 200 characters", "Review note")],
    },
    indexLogs: {
        subject: "Index log",
        templateFileName: "index_logs_template.csv",
        template: 'media_id,index_id,version,min_time,max_time,min_frequency,max_frequency,params,results\n101,1,1.0,0,60,0,24000,"{""channel"":""left""}","{""value"":0.42}"\n102,2,1.0,0,60,0,24000,"{""channel"":""right""}","{""value"":0.58}"\n',
        example: { media_id: 101, index_id: 1, version: "1.0", min_time: "0", max_time: "60", min_frequency: "0", max_frequency: "24000", params: { channel: "left" }, results: { value: 0.42 } },
        additionalExample: { media_id: 102, index_id: 2, version: "1.0", min_time: "0", max_time: "60", min_frequency: "0", max_frequency: "24000", params: { channel: "right" }, results: { value: 0.58 } },
        fields: [field("media_id", "required positive integer", "Media in the selected collection"), field("index_id", "required positive integer", "Acoustic index identifier"), field("version", "required string", "Index implementation version"), field("min_time", "optional string", "Analysis start time"), field("max_time", "optional string", "Analysis end time"), field("min_frequency", "optional string", "Minimum frequency"), field("max_frequency", "optional string", "Maximum frequency"), field("params", "optional JSON object", "Analysis parameters"), field("results", "optional JSON object", "Calculated index values")],
    },
    tasks: {
        subject: "Task",
        templateFileName: "tasks_template.csv",
        template: "media_id,type,annotation_id,assignee_id,comment\n101,media,,7,Review this recording\n102,media,,8,Review this recording too\n",
        example: { media_id: 101, type: "media", annotation_id: null, assignee_id: 7, comment: "Review this recording" },
        additionalExample: { media_id: 102, type: "media", annotation_id: null, assignee_id: 8, comment: "Review this recording too" },
        fields: [field("media_id", "required positive integer", "Media in the selected collection"), field("type", "required: media or annotation", "Task type"), field("annotation_id", "required for annotation tasks", "Annotation identifier"), field("assignee_id", "required positive integer", "Assigned user identifier"), field("comment", "optional, max 1000 characters", "Assignment comment")],
    },
    users: {
        subject: "User",
        templateFileName: "users_template.csv",
        template: "username,name,email,password,orcid,color,active\nfielduser,Field User,fielduser@example.org,ChangeMe123!,0000-0000-0000-0000,#FFFFFF,true\nfielduser2,Field User Two,fielduser2@example.org,ChangeMe123!,0000-0000-0000-0001,#F0F0F0,true\n",
        example: { username: "fielduser", name: "Field User", email: "fielduser@example.org", password: "ChangeMe123!", orcid: "0000-0000-0000-0000", color: "#FFFFFF", active: true },
        additionalExample: { username: "fielduser2", name: "Field User Two", email: "fielduser2@example.org", password: "ChangeMe123!", orcid: "0000-0000-0000-0001", color: "#F0F0F0", active: true },
        fields: [field("username", "required, 3-20 characters", "Login username"), field("name", "required, max 100 characters", "Display name"), field("email", "required valid email, max 100 characters", "Email address"), field("password", "required, 8-128 characters", "Initial password; never returned in reports"), field("orcid", "optional, max 100 characters", "ORCID identifier"), field("color", "optional #RRGGBB, default #FFFFFF", "User display colour"), field("active", "optional boolean, default true", "Whether the account is active")],
    },
    sounds: {
        subject: "Sound",
        templateFileName: "sounds_template.csv",
        template: "soundscape_component,sound_type\nbiophony,snapping shrimps\ngeophony,rainfall\n",
        example: { soundscape_component: "biophony", sound_type: "snapping shrimps" },
        additionalExample: { soundscape_component: "geophony", sound_type: "rainfall" },
        fields: [field("soundscape_component", "required, max 200 characters", "Main soundscape category"), field("sound_type", "optional, max 30 characters", "Specific sound type")],
    },
    taxons: {
        subject: "Taxon",
        templateFileName: "taxa_template.csv",
        template: "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\nCorvus cornix,Hooded Crow,Corvus,Corvidae,Passeriformes,Aves,CatalogueOfLife-XR\nCorvus corone,Carrion Crow,Corvus,Corvidae,Passeriformes,Aves,CatalogueOfLife-XR\n",
        example: { cached_scientific_name: "Corvus cornix", cached_common_name: "Hooded Crow", col_genus_name: "Corvus", col_family_name: "Corvidae", col_order_name: "Passeriformes", col_class_name: "Aves", taxonomy_source: "CatalogueOfLife-XR" },
        additionalExample: { cached_scientific_name: "Corvus corone", cached_common_name: "Carrion Crow", col_genus_name: "Corvus", col_family_name: "Corvidae", col_order_name: "Passeriformes", col_class_name: "Aves", taxonomy_source: "CatalogueOfLife-XR" },
        fields: [field("cached_scientific_name", "required, max 100 characters", "Scientific name"), field("cached_common_name", "required, max 200 characters", "Common name"), field("col_genus_name", "optional, max 100 characters", "Genus"), field("col_family_name", "optional, max 100 characters", "Family"), field("col_order_name", "optional, max 100 characters", "Taxonomic order"), field("col_class_name", "optional, max 100 characters", "Taxonomic class"), field("taxonomy_source", "required, max 50 characters", "Taxonomy source")],
    },
    cameras: {
        subject: "Camera", templateFileName: "cameras_template.csv", template: "name,version,brand\nEOS R5,Mark II,Canon\nEOS R6,Mark II,Canon\n", example: { name: "EOS R5", version: "Mark II", brand: "Canon" }, additionalExample: { name: "EOS R6", version: "Mark II", brand: "Canon" },
        fields: [field("name", "required, max 100 characters", "Camera model name"), field("version", "optional, max 100 characters", "Version or model number"), field("brand", "optional, max 100 characters", "Manufacturer or brand")],
    },
    lenses: {
        subject: "Lens", templateFileName: "lenses_template.csv", template: "name,focal_length,max_aperture,brand\nRF 24-70mm,24-70mm,f/2.8,Canon\nRF 100-500mm,100-500mm,f/4.5-7.1,Canon\n", example: { name: "RF 24-70mm", focal_length: "24-70mm", max_aperture: "f/2.8", brand: "Canon" }, additionalExample: { name: "RF 100-500mm", focal_length: "100-500mm", max_aperture: "f/4.5-7.1", brand: "Canon" },
        fields: [field("name", "required, max 100 characters", "Lens model name"), field("focal_length", "optional, max 50 characters", "Focal length or range"), field("max_aperture", "optional, max 20 characters", "Maximum aperture"), field("brand", "optional, max 100 characters", "Manufacturer or brand")],
    },
    microphones: {
        subject: "Microphone", templateFileName: "microphones_template.csv", template: "name,microphone_element,sensitivity,signal_to_noise_ratio\nMAARU (built-in microphone),MSM321A3729H9CP,-32,80\nHydrophone H2,HTI-96-MIN,-165,55\n", example: { name: "MAARU (built-in microphone)", microphone_element: "MSM321A3729H9CP", sensitivity: -32, signal_to_noise_ratio: 80 }, additionalExample: { name: "Hydrophone H2", microphone_element: "HTI-96-MIN", sensitivity: -165, signal_to_noise_ratio: 55 },
        fields: [field("name", "required, max 100 characters", "Microphone name or model"), field("microphone_element", "optional, max 100 characters", "Microphone element type"), field("sensitivity", "optional integer", "Sensitivity in dBV"), field("signal_to_noise_ratio", "optional integer", "Signal-to-noise ratio in dB")],
    },
    recorders: {
        subject: "Recorder", templateFileName: "recorders_template.csv", template: "name,version,brand\nSong Meter SM4,4.0,Wildlife Acoustics\nSong Meter Mini,2.0,Wildlife Acoustics\n", example: { name: "Song Meter SM4", version: "4.0", brand: "Wildlife Acoustics" }, additionalExample: { name: "Song Meter Mini", version: "2.0", brand: "Wildlife Acoustics" },
        fields: [field("name", "required, max 100 characters", "Recorder model name"), field("version", "optional, max 100 characters", "Version or model number"), field("brand", "optional, max 100 characters", "Manufacturer or brand")],
    },
} satisfies Record<string, ImportResourceConfig>
