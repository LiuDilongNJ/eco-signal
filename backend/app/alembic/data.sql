--
-- ecoSignal PostgreSQL Initial Data
--

-- --------------------------------------------------------
-- iucn_get - IUCN Global Ecosystem Typology
-- --------------------------------------------------------
INSERT INTO iucn_get (iucn_get_id, pid, name, level)
VALUES (1, 0, 'Terrestrial', 1),
       (2, 0, 'Freshwater', 1),
       (3, 0, 'Subterranean', 1),
       (4, 0, 'Marine', 1),
       (5, 0, 'Marine-Terrestrial', 1),
       (6, 0, 'Subterranean-Freshwater', 1),
       (7, 0, 'Terrestrial-Freshwater', 1),
       (8, 0, 'Subterranean-Marine', 1),
       (9, 0, 'Marine-Freshwater-Terrestrial', 1),
       (10, 0, 'Freshwater-Marine', 1),
       (11, 1, 'Tropical-subtropical forests biome', 2),
       (12, 1, 'Temperate-boreal forests and woodlands biome', 2),
       (13, 1, 'Shrublands and shrubby woodlands biome', 2),
       (14, 1, 'Savannas and grasslands biome', 2),
       (15, 1, 'Deserts and semi-deserts biome', 2),
       (16, 1, 'Polar/alpine (cryogenic) biome', 2),
       (17, 1, 'Intensive land-use biome', 2),
       (18, 2, 'Rivers and streams biome', 2),
       (19, 2, 'Lakes biome', 2),
       (20, 2, 'Artificial wetlands biome', 2),
       (21, 3, 'Subterranean lithic biome', 2),
       (22, 3, 'Anthropogenic subterranean voids biome', 2),
       (23, 4, 'Marine shelf biome', 2),
       (24, 4, 'Pelagic ocean waters biome', 2),
       (25, 4, 'Deep sea floors biome', 2),
       (26, 4, 'Anthropogenic marine biome', 2),
       (27, 5, 'Shorelines biome', 2),
       (28, 5, 'Supralittoral coastal biome', 2),
       (29, 5, 'Anthropogenic shorelines biome', 2),
       (30, 6, 'Subterranean freshwaters biome', 2),
       (31, 6, 'Anthropogenic subterranean freshwaters biome', 2),
       (32, 7, 'Palustrine wetlands biome', 2),
       (33, 8, 'Subterranean tidal biome', 2),
       (34, 9, 'Brackish tidal biome', 2),
       (35, 10, 'Semi-confined transitional waters biome', 2),
       (36, 11, 'Tropical/Subtropical lowland rainforests', 3),
       (37, 11, 'Tropical/Subtropical dry forests and thickets', 3),
       (38, 11, 'Tropical/Subtropical montane rainforests', 3),
       (39, 11, 'Tropical heath forests', 3),
       (40, 12, 'Boreal and temperate high montane forests and woodlands', 3),
       (41, 12, 'Deciduous temperate forests', 3),
       (42, 12, 'Oceanic cool temperate rainforests', 3),
       (43, 12, 'Warm temperate laurophyll forests', 3),
       (44, 12, 'Temperate pyric humid forests', 3),
       (45, 12, 'Temperate pyric sclerophyll forests and woodlands', 3),
       (46, 13, 'Seasonally dry tropical shrublands', 3),
       (47, 13, 'Seasonally dry temperate heath and shrublands', 3),
       (48, 13, 'Cool temperate heathlands', 3),
       (49, 13, 'Young rocky pavements, lava flows and screes', 3),
       (50, 14, 'Trophic savannas', 3),
       (51, 14, 'Pyric tussock savannas', 3),
       (52, 14, 'Hummock savannas', 3),
       (53, 14, 'Temperate woodlands', 3),
       (54, 14, 'Temperate subhumid grasslands', 3),
       (55, 15, 'Semi-desert steppe', 3),
       (56, 15, 'Succulent or Thorny deserts and semi-deserts', 3),
       (57, 15, 'Sclerophyll hot deserts and semi-deserts', 3),
       (58, 15, 'Cool deserts and semi-deserts', 3),
       (59, 15, 'Hyper-arid deserts', 3),
       (60, 16, 'Ice sheets, glaciers and perennial snowfields', 3),
       (61, 16, 'Polar/alpine cliffs, screes, outcrops and lava flows', 3),
       (62, 16, 'Polar tundra and deserts', 3),
       (63, 16, 'Temperate alpine grasslands and shrublands', 3),
       (64, 16, 'Tropical alpine grasslands and herbfields', 3),
       (65, 17, 'Annual croplands', 3),
       (66, 17, 'Sown pastures and fields', 3),
       (67, 17, 'Plantations', 3),
       (68, 17, 'Urban and industrial ecosystems Realm', 3),
       (69, 17, 'Derived semi-natural pastures and old fields', 3),
       (70, 18, 'Permanent upland streams', 3),
       (71, 18, 'Permanent lowland rivers', 3),
       (72, 18, 'Freeze-thaw rivers and streams', 3),
       (73, 18, 'Seasonal upland streams', 3),
       (74, 18, 'Seasonal lowland rivers', 3),
       (75, 18, 'Episodic arid rivers', 3),
       (76, 18, 'Large lowland rivers', 3),
       (77, 19, 'Large permanent freshwater lakes', 3),
       (78, 19, 'Small permanent freshwater lakes', 3),
       (79, 19, 'Seasonal freshwater lakes', 3),
       (80, 19, 'Freeze-thaw freshwater lakes', 3),
       (81, 19, 'Ephemeral freshwater lakes', 3),
       (82, 19, 'Permanent salt and soda lakes', 3),
       (83, 19, 'Ephemeral salt lakes', 3),
       (84, 19, 'Artesian springs and oases', 3),
       (85, 19, 'Geothermal pools and wetlands', 3),
       (86, 19, 'Subglacial lakes', 3),
       (87, 20, 'Large reservoirs', 3),
       (88, 20, 'Constructed lacustrine wetlands', 3),
       (89, 20, 'Rice paddies', 3),
       (90, 20, 'Freshwater aquafarms', 3),
       (91, 20, 'Canals, ditches and drains', 3),
       (92, 21, 'Aerobic caves', 3),
       (93, 21, 'Endolithic systems', 3),
       (94, 22, 'Anthropogenic subterranean voids', 3),
       (95, 23, 'Seagrass meadows', 3),
       (96, 23, 'Kelp forests', 3),
       (97, 23, 'Photic coral reefs', 3),
       (98, 23, 'Shellfish beds and reefs', 3),
       (99, 23, 'Photo-limited marine animal forests', 3),
       (100, 23, 'Subtidal rocky reefs', 3),
       (101, 23, 'Subtidal sand beds', 3),
       (102, 23, 'Subtidal mud plains', 3),
       (103, 23, 'Upwelling zones', 3),
       (104, 24, 'Epipelagic ocean waters', 3),
       (105, 24, 'Mesopelagic ocean water', 3),
       (106, 24, 'Bathypelagic ocean waters', 3),
       (107, 24, 'Abyssopelagic ocean waters', 3),
       (108, 24, 'Sea ice', 3),
       (109, 25, 'Continental and island slopes', 3),
       (110, 25, 'Submarine canyons', 3),
       (111, 25, 'Abyssal plains', 3),
       (112, 25, 'Seamounts, ridges and plateaus', 3),
       (113, 25, 'Deepwater biogenic beds', 3),
       (114, 25, 'Hadal trenches and troughs', 3),
       (115, 25, 'Chemosynthetic-based-ecosystems (CBE)', 3),
       (116, 26, 'Submerged artificial structures', 3),
       (117, 26, 'Marine aquafarms', 3),
       (118, 27, 'Rocky Shorelines', 3),
       (119, 27, 'Muddy Shorelines', 3),
       (120, 27, 'Sandy Shorelines', 3),
       (121, 27, 'Boulder and cobble shores', 3),
       (122, 28, 'Coastal shrublands and grasslands', 3),
       (123, 29, 'Artificial shorelines', 3),
       (124, 30, 'Underground streams and pools', 3),
       (125, 30, 'Groundwater ecosystems', 3),
       (126, 31, 'Water pipes and subterranean canals', 3),
       (127, 31, 'Flooded mines and other voids', 3),
       (128, 32, 'Tropical flooded forests and peat forests', 3),
       (129, 32, 'Subtropical/temperate forested wetlands', 3),
       (130, 32, 'Permanent marshes', 3),
       (131, 32, 'Seasonal floodplain marshes', 3),
       (132, 32, 'Episodic arid floodplains', 3),
       (133, 32, 'Boreal, temperate and montane peat bogs', 3),
       (134, 32, 'Boreal and temperate fens', 3),
       (135, 33, 'Anchialine caves', 3),
       (136, 33, 'Anchialine pools', 3),
       (137, 33, 'Sea caves', 3),
       (138, 34, 'Coastal river deltas', 3),
       (139, 34, 'Intertidal forests and shrublands', 3),
       (140, 34, 'Coastal saltmarshes and reedbeds', 3),
       (141, 35, 'Deepwater coastal inlets', 3),
       (142, 35, 'Permanently open riverine estuaries and bays', 3),
       (143, 35, 'Intermittently closed and open lakes and lagoons', 3);

-- Reset sequence
SELECT setval('iucn_get_iucn_get_id_seq', (SELECT MAX(iucn_get_id) FROM iucn_get));

-- --------------------------------------------------------
-- role - User roles
-- --------------------------------------------------------
INSERT INTO role (role_id, name)
VALUES (1, 'Administrator'),
       (2, 'User');

SELECT setval('role_role_id_seq', (SELECT MAX(role_id) FROM role));

-- --------------------------------------------------------
-- permission - Resource-based permissions
-- --------------------------------------------------------
INSERT INTO permission (permission_id, resource_type, action, name)
VALUES (1, 'project', 'read', 'project:read'),
       (2, 'project', 'write', 'project:write'),
       (3, 'collection', 'read', 'collection:read'),
       (4, 'collection', 'write', 'collection:write'),
       (5, 'audio', 'read', 'audio:read'),
       (6, 'audio', 'write', 'audio:write'),
       (7, 'site', 'read', 'site:read'),
       (8, 'site', 'write', 'site:write'),
       (9, 'annotation', 'read', 'annotation:read'),
       (10, 'annotation', 'write', 'annotation:write'),
       (11, 'review', 'read', 'review:read'),
       (12, 'review', 'write', 'review:write');

SELECT setval('permission_permission_id_seq', (SELECT MAX(permission_id) FROM permission));

-- --------------------------------------------------------
-- "user" - System users
-- --------------------------------------------------------
INSERT INTO "user" (user_id, role_id, username, password, name, orcid, email, active)
VALUES (1, 1, 'admin', 'JDJ5JDEwJHguRG9TQmZ5dmtiRTRPUEkxRlRKR3VRMTFXUmVNZWVDZkRDcy5QTDRSdENiMWpMNVF6TlMu', 'Administrator', NULL, 'admin@ecosignal.local', TRUE);

SELECT setval('user_user_id_seq', (SELECT MAX(user_id) FROM "user"));

-- --------------------------------------------------------
-- user_preference - User preferences
-- --------------------------------------------------------
INSERT INTO user_preference (user_id, fft, theme, language, timezone, notifications_enabled)
VALUES (1, 512, 'light', 'en', 'America/New_York', TRUE);

-- --------------------------------------------------------
-- license - Content licenses
-- --------------------------------------------------------
INSERT INTO license (license_id, name, link)
VALUES (1, 'Copyright', ''),
       (2, 'CC0', 'https://creativecommons.org/publicdomain/zero/1.0/'),
       (3, 'CC-BY', 'https://creativecommons.org/licenses/by/4.0'),
       (4, 'CC-BY-SA', 'https://creativecommons.org/licenses/by-sa/4.0/'),
       (5, 'CC-BY-NC', 'https://creativecommons.org/licenses/by-nc/4.0'),
       (6, 'CC-BY-NC-SA', 'https://creativecommons.org/licenses/by-nc-sa/4.0'),
       (7, 'CC-BY-ND', 'https://creativecommons.org/licenses/by-nd/4.0/'),
       (8, 'CC-BY-NC-ND', 'https://creativecommons.org/licenses/by-nc-nd/4.0');

SELECT setval('license_license_id_seq', (SELECT MAX(license_id) FROM license));

-- --------------------------------------------------------
-- taxon_sound_type - Taxon sound types
-- --------------------------------------------------------
INSERT INTO taxon_sound_type (taxon_sound_type_id, name, taxon_class, taxon_order)
VALUES (1, '(Bird) Call - unspecific', 'AVES', ''),
       (2, '(Bird) Song', 'AVES', ''),
       (3, '(Bird) Non-vocal', 'AVES', ''),
       (4, '(Bat) Searching', 'MAMMALIA', 'CHIROPTERA'),
       (5, '(Bat) Feeding', 'MAMMALIA', 'CHIROPTERA'),
       (6, '(Bat) Social', 'MAMMALIA', 'CHIROPTERA'),
       (7, 'Unknown', '', ''),
       (8, '(Bird) Call - contact', 'AVES', ''),
       (9, '(Bird) Call - flight', 'AVES', ''),
       (10, '(Bird) Call - begging', 'AVES', ''),
       (11, '(Amphibia) Courtship', 'AMPHIBIA', ''),
       (12, '(Amphibia) Advertisement towards males', 'AMPHIBIA', ''),
       (13, '(Amphibia) Acquisition/defense of reproductive territories', 'AMPHIBIA', ''),
       (14, '(Amphibia) Discouraging takeover attempts by other males during amplexus', 'AMPHIBIA', ''),
       (15, '(Amphibia) defense of diurnal retreats not used for reproduction', 'AMPHIBIA', ''),
       (16, '(Primate) Agonistic', 'MAMMALIA', 'PRIMATA'),
       (17, '(Primate) Affiliative', 'MAMMALIA', 'PRIMATA'),
       (18, '(Primate) Contact', 'MAMMALIA', 'PRIMATA'),
       (19, '(Primate) Song', 'MAMMALIA', 'PRIMATA'),
       (20, '(Primate) Advertisement - territory', 'MAMMALIA', 'PRIMATA'),
       (21, '(Primate) Advertisement - mating', 'MAMMALIA', 'PRIMATA'),
       (22, '(Primate) Foraging', 'MAMMALIA', 'PRIMATA'),
       (23, '(Primate) Alarm', 'MAMMALIA', 'PRIMATA'),
       (24, '(Primate) Begging', 'MAMMALIA', 'PRIMATA'),
       (25, '(Primate) Adult - offspring', 'MAMMALIA', 'PRIMATA');

SELECT setval('taxon_sound_type_taxon_sound_type_id_seq', (SELECT MAX(taxon_sound_type_id) FROM taxon_sound_type));

-- --------------------------------------------------------
-- sound_classification - Soundscape classification
-- --------------------------------------------------------
INSERT INTO sound_classification (sound_id, soundscape_component, sound_type)
VALUES (1, 'biophony', 'fish chorus'),
       (2, 'biophony', 'bat swarm'),
       (3, 'biophony', 'insect broadband noise'),
       (4, 'biophony', 'reptile'),
       (5, 'biophony', 'bird chorus'),
       (6, 'biophony', NULL),
       (7, 'anthropophony', 'human voices'),
       (8, 'anthropophony', 'transportation'),
       (9, 'anthropophony', 'mining'),
       (10, 'anthropophony', NULL),
       (11, 'geophony', 'wind'),
       (12, 'geophony', 'wave'),
       (13, 'geophony', 'earthquake'),
       (14, 'geophony', 'rain'),
       (15, 'geophony', NULL),
       (16, 'other', 'template matching result'),
       (17, 'other', 'equipment self-noise'),
       (18, 'other', 'ambient sound (background)'),
       (19, 'other', 'thermal bat detection'),
       (20, 'other', 'unknown'),
       (21, 'other', 'TEST'),
       (22, 'other', NULL);

SELECT setval('sound_classification_sound_id_seq', (SELECT MAX(sound_id) FROM sound_classification));

-- --------------------------------------------------------
-- taxon - Taxonomy (sample data)
-- --------------------------------------------------------
INSERT INTO taxon (taxon_id, cached_scientific_name, cached_common_name, taxonomy_source)
VALUES (1, 'Unknown', 'Unknown', 'CatalogueOfLife'),
       (2, 'Test bird', 'common bird name', 'CatalogueOfLife'),
       (3, 'Test amphibian', 'common amphibian name', 'CatalogueOfLife'),
       (4, 'Test primate', 'common primate name', 'CatalogueOfLife');

SELECT setval('taxon_taxon_id_seq', (SELECT MAX(taxon_id) FROM taxon));

-- --------------------------------------------------------
-- annotation_review_status - Annotation review status
-- --------------------------------------------------------
INSERT INTO annotation_review_status (annotation_review_status_id, name)
VALUES (1, 'Accepted'),
       (2, 'Corrected'),
       (3, 'Rejected'),
       (4, 'Uncertain');

SELECT setval('annotation_review_status_annotation_review_status_id_seq', (SELECT MAX(annotation_review_status_id) FROM annotation_review_status));

-- --------------------------------------------------------
-- index_type - Acoustic index types
-- --------------------------------------------------------
INSERT INTO index_type (index_id, name, param, description, url)
VALUES (1, 'acoustic_complexity_index', '[]', 'Compute the Acoustic Complexity Index (ACI) from a spectrogram.', 'https://scikit-maad.github.io/generated/maad.features.acoustic_complexity_index.html'),
       (2, 'soundscape_index', '[{"key":"flim_bioPh","default":"1000,10000","value_type":"string"},{"key":"flim_antroPh","default":"0,1000","value_type":"string"},{"key":"R_compatible","default":"soundecology","value_type":"string"}]', 'Compute the Normalized Difference Soundscape Index from a power spectrogram.', 'https://scikit-maad.github.io/generated/maad.features.soundscape_index.html'),
       (3, 'temporal_median', '[{"key":"mode","default":"fast","value_type":"string"},{"key":"Nt","default":512,"value_type":"number"}]', 'Computes the median of the envelope of an audio signal.', 'https://scikit-maad.github.io/generated/maad.features.temporal_median.html'),
       (4, 'temporal_entropy', '[{"key":"mode","default":"fast","value_type":"string"},{"key":"Nt","default":512,"value_type":"number"}]', 'Computes the entropy of the envelope of an audio signal.', 'https://scikit-maad.github.io/generated/maad.features.temporal_entropy.html'),
       (5, 'temporal_activity', '[{"key":"dB_threshold","default":3,"value_type":"number"},{"key":"mode","default":"fast","value_type":"string"},{"key":"Nt","default":512,"value_type":"number"}]', 'Compute the acoustic activity index in temporal domain.', 'https://scikit-maad.github.io/generated/maad.features.temporal_activity.html'),
       (6, 'temporal_events', '[{"key":"dB_threshold","default":3,"value_type":"number"},{"key":"rejectDuration","default":null,"value_type":"string"},{"key":"mode","default":"fast","value_type":"string"},{"key":"Nt","default":512,"value_type":"number"},{"key":"display","default":false,"value_type":"boolean"}]', 'Compute the acoustic event index from an audio signal', 'https://scikit-maad.github.io/generated/maad.features.temporal_events.html'),
       (7, 'frequency_entropy', '[{"key":"compatibility","default":"QUT","value_type":"string"}]', 'Computes the spectral entropy of a power spectral density (1d) or power spectrogram density (2d).', 'https://scikit-maad.github.io/generated/maad.features.frequency_entropy.html'),
       (8, 'number_of_peaks', '[{"key":"mode","default":"dB","value_type":"string"},{"key":"min_peak_val","default":null,"value_type":"string"},{"key":"min_freq_dist","default":200,"value_type":"number"},{"key":"slopes","default":"1,1","value_type":"string"},{"key":"prominence","default":null,"value_type":"string"},{"key":"display","default":false,"value_type":"boolean"}]', 'Count the number of frequency peaks on a mean spectrum.', 'https://scikit-maad.github.io/generated/maad.features.number_of_peaks.html'),
       (9, 'spectral_entropy', '[{"key":"flim","default":null,"value_type":"string"},{"key":"display","default":false,"value_type":"boolean"}]', 'Compute different entropies based on the average spectrum, its variance, and its maxima', 'https://scikit-maad.github.io/generated/maad.features.spectral_entropy.html'),
       (10, 'spectral_activity', '[{"key":"dB_threshold","default":6,"value_type":"number"}]', 'Compute the acoustic activity on a spectrogram.', 'https://scikit-maad.github.io/generated/maad.features.spectral_activity.html'),
       (11, 'spectral_cover', '[{"key":"flim_LF","default":"0,1000","value_type":"string"},{"key":"flim_MF","default":"1000,10000","value_type":"string"},{"key":"flim_HF","default":"10000,20000","value_type":"string"}]', 'Compute the proportion (cover) of the spectrogram above a threshold for three bandwidths.', 'https://scikit-maad.github.io/generated/maad.features.spectral_cover.html'),
       (12, 'bioacoustics_index', '[{"key":"flim","default":"2000,15000","value_type":"string"},{"key":"R_compatible","default":"soundecology","value_type":"string"}]', 'Compute the Bioacoustics Index from a spectrogram', 'https://scikit-maad.github.io/generated/maad.features.bioacoustics_index.html'),
       (13, 'acoustic_diversity_index', '[{"key":"fmin","default":0,"value_type":"number"},{"key":"fmax","default":20000,"value_type":"number"},{"key":"bin_step","default":500,"value_type":"number"},{"key":"dB_threshold","default":-50,"value_type":"number"},{"key":"index","default":"shannon","value_type":"string"}]', 'Compute the Acoustic Diversity Index (ADI) from a spectrogram', 'https://scikit-maad.github.io/generated/maad.features.acoustic_diversity_index.html'),
       (14, 'acoustic_eveness_index', '[{"key":"fmin","default":0,"value_type":"number"},{"key":"fmax","default":20000,"value_type":"number"},{"key":"bin_step","default":500,"value_type":"number"},{"key":"dB_threshold","default":-50,"value_type":"number"}]', 'Compute the Acoustic Eveness Index (AEI) from a spectrogram', 'https://scikit-maad.github.io/generated/maad.features.acoustic_eveness_index.html'),
       (15, 'temporal_leq', '[{"key":"gain","default":42,"value_type":"number"},{"key":"Vadc","default":2,"value_type":"number"},{"key":"sensitivity","default":-35,"value_type":"number"},{"key":"dBref","default":94,"value_type":"number"},{"key":"dt","default":1,"value_type":"number"}]', 'Computes the Equivalent Continuous Sound level (Leq) of an audio signal in the time domain.', 'https://scikit-maad.github.io/generated/maad.features.temporal_leq.html'),
       (16, 'spectral_leq', '[{"key":"gain","default":42,"value_type":"number"},{"key":"Vadc","default":2,"value_type":"number"},{"key":"sensitivity","default":-35,"value_type":"number"},{"key":"dBref","default":94,"value_type":"number"},{"key":"pRef","default":0.00002,"value_type":"number"}]', 'Computes the Equivalent Continuous Sound level (Leq) from a power spectrum (1d) or power spectrogram (2d).', 'https://scikit-maad.github.io/generated/maad.features.spectral_leq.html'),
       (17, 'tfsd', '[{"key":"flim","default":"2000,8000","value_type":"string"},{"key":"mode","default":"thirdOctave","value_type":"string"},{"key":"display","default":false,"value_type":"boolean"}]', 'Compute the Time frequency derivation index (tfsd) from a spectrogram.', 'https://scikit-maad.github.io/generated/maad.features.tfsd.html'),
       (18, 'more_entropy_time', '[{"key":"order","default":3,"value_type":"number"},{"key":"axis","default":0,"value_type":"number"}]', 'Compute the entropy of an audio signal using multiple methods.', 'https://scikit-maad.github.io/generated/maad.features.more_entropy.html'),
       (19, 'acoustic_gradient_index', '[{"key":"norm","default":"per_bin","value_type":"string"}]', 'Compute the Acoustic Gradient Index (AGI) from a raw spectrogram.', 'https://scikit-maad.github.io/generated/maad.features.acoustic_gradient_index.html'),
       (20, 'frequency_raoq', '[{"key":"bin_step","default":1000,"value_type":"number"}]', 'Compute Rao''s quadratic entropy on a power spectrum (1d).', 'https://scikit-maad.github.io/generated/maad.features.frequency_raoq.html'),
       (21, 'more_entropy_spectral', '[{"key":"order","default":3,"value_type":"number"},{"key":"axis","default":0,"value_type":"number"}]', 'Compute the entropy of an audio signal using multiple methods.', 'https://scikit-maad.github.io/generated/maad.features.more_entropy.html');

SELECT setval('index_type_index_id_seq', (SELECT MAX(index_id) FROM index_type));

-- --------------------------------------------------------
-- model - Machine learning models
-- --------------------------------------------------------
INSERT INTO model (model_id, name, model_path, labels_path, source_url, description, parameter)
VALUES (1, 'BirdNET-Analyzer', '/BirdNET-Analyzer', '/BirdNET-Analyzer', 'https://github.com/kahst/BirdNET-Analyzer', 'Automated scientific audio data processing and bird ID.', '{"sensitivity": {"min": 0.5, "max": 1.5, "default": 1.0}, "min_conf": {"min": 0.01, "max": 0.99, "default": 0.1}, "overlap": {"min": 0.0, "max": 2.9, "default": 0.0}, "sf_thresh": {"min": 0.01, "max": 0.99, "default": 0.03}}'),
       (2, 'batdetect2', '/batdetect2', '/batdetect2', 'https://github.com/macaodha/batdetect2.git', 'Code for detecting and classifying bat echolocation calls in high frequency audio recordings.', '{"detection_threshold": {"min": 0, "max": 1.0, "default": 0.3}}');

SELECT setval('model_model_id_seq', (SELECT MAX(model_id) FROM model));

-- --------------------------------------------------------
-- recorder - Recording devices
-- --------------------------------------------------------
INSERT INTO recorder (recorder_id, name, version, brand)
VALUES (1, 'µRUDAR-mk2', NULL, 'Cetacean Research Technology'),
       (2, 'AAD Moored Acoustic Recorder', NULL, NULL),
       (3, 'Audiomoth 1.0.0', '1.0.0', 'Open Acoustic Devices'),
       (4, 'AudioMoth 1.1.0', '1.1.0', 'Open Acoustic Devices'),
       (5, 'Audiomoth 1.2.0', '1.2.0', 'Open Acoustic Devices'),
       (6, 'BAR-LT', NULL, 'Frontier Labs'),
       (7, 'COLMEIA', NULL, 'Laboratoire Géosciences Océan'),
       (8, 'Curtin Underwater Sound Recorder', NULL, NULL),
       (9, 'DR-05', NULL, 'Tascam'),
       (10, 'DR-07', NULL, 'Tascam'),
       (11, 'DR-44WL', NULL, 'Tascam'),
       (12, 'DS-850', NULL, 'Olympus'),
       (13, 'DSG-ST', NULL, 'Loggerhead'),
       (14, 'F6', NULL, 'Zoom'),
       (15, 'H4n', NULL, 'Zoom'),
       (16, 'H5', NULL, 'Zoom'),
       (17, 'HYDROMOMAR', NULL, 'Laboratoire Géosciences Océan'),
       (18, 'LG L70', NULL, 'LG'),
       (19, 'LS-P4', NULL, 'Olympus'),
       (20, 'Nomad Jukebox', NULL, 'Creative'),
       (21, 'PMD 661', NULL, 'Marantz Professional'),
       (22, 'PMEL AUH/Haruphone', NULL, NULL),
       (23, 'Recoti recorder', NULL, NULL),
       (24, 'SOLO recorder', NULL, 'Self-built'),
       (25, 'Song Meter Mini', NULL, 'Wildlife Acoustics'),
       (26, 'Song Meter SM1', NULL, 'Wildlife Acoustics'),
       (27, 'Song Meter SM2', NULL, 'Wildlife Acoustics'),
       (28, 'Song Meter SM2+', NULL, 'Wildlife Acoustics'),
       (29, 'Song Meter SM2Bat+', NULL, 'Wildlife Acoustics'),
       (30, 'Song Meter SM3', NULL, 'Wildlife Acoustics'),
       (31, 'Song Meter SM3 Bat', NULL, 'Wildlife Acoustics'),
       (32, 'Song Meter SM4', NULL, 'Wildlife Acoustics'),
       (33, 'Song Meter SM4 Bat FS', NULL, 'Wildlife Acoustics'),
       (34, 'Soundscape Explorer', NULL, 'Lunilettronik'),
       (35, 'SoundTrap ST300 HF', NULL, 'OceanInstruments'),
       (36, 'SoundTrap ST300 STD', NULL, 'OceanInstruments'),
       (37, 'SoundTrap ST600 STD', NULL, 'OceanInstruments'),
       (38, 'SWIFT', NULL, 'The Cornell lab of Ornithology'),
       (39, 'SwiftOne', NULL, 'The Cornell lab of Ornithology');

SELECT setval('recorder_recorder_id_seq', (SELECT MAX(recorder_id) FROM recorder));

-- --------------------------------------------------------
-- microphone - Microphones
-- --------------------------------------------------------
INSERT INTO microphone (microphone_id, name, microphone_element, sensitivity, signal_to_noise_ratio)
VALUES (1, 'AED-2010', NULL, NULL, NULL),
       (2, 'AquaSound AQH-020D', NULL, NULL, NULL),
       (3, 'Audio H2a', NULL, NULL, NULL),
       (4, 'Audiomoth 1.0.0 built-in', NULL, NULL, NULL),
       (5, 'Audiomoth 1.1.0 built-in', NULL, NULL, NULL),
       (6, 'Audiomoth 1.2.0 built-in', NULL, NULL, NULL),
       (7, 'DR-05', NULL, NULL, NULL),
       (8, 'DR-07 MKII', NULL, NULL, NULL),
       (9, 'EM172', NULL, NULL, NULL),
       (10, 'EM-2800A', NULL, NULL, NULL),
       (11, 'EMY-63M/P', NULL, NULL, NULL),
       (12, 'FrontierLabs Standard Black Microphone', NULL, NULL, NULL),
       (13, 'HTI-90-U', NULL, NULL, NULL),
       (14, 'HTI-94-SSQ', NULL, NULL, NULL),
       (15, 'HTI-96-MIN', NULL, NULL, NULL),
       (16, 'ITC-1032', NULL, NULL, NULL),
       (17, 'JRF', NULL, NULL, NULL),
       (18, 'Model 600200', NULL, NULL, NULL),
       (19, 'Pavo', NULL, NULL, NULL),
       (20, 'Recoti Microphone', NULL, NULL, NULL),
       (21, 'Sennheiser ME62', NULL, NULL, NULL),
       (22, 'Sensor Technology SQ26-08', NULL, NULL, NULL),
       (23, 'SM1 standard microphone', NULL, NULL, NULL),
       (24, 'SM3 stub microphone (built-in)', NULL, NULL, NULL),
       (25, 'SM4 stub microphone (built-in)', NULL, NULL, NULL),
       (26, 'SMM-A1', NULL, NULL, NULL),
       (27, 'SMM-U1', NULL, NULL, NULL),
       (28, 'SMM-U2', NULL, NULL, NULL),
       (29, 'SMO', NULL, NULL, NULL),
       (30, 'SMX-II (after 2014)', NULL, NULL, NULL),
       (31, 'SMX-II (before 2014)', NULL, NULL, NULL),
       (32, 'SMX-U1', NULL, NULL, NULL),
       (33, 'Song Meter Mini built-in', NULL, NULL, NULL),
       (34, 'SoundTrap', NULL, NULL, NULL),
       (35, 'SWIFT', NULL, NULL, NULL);

SELECT setval('microphone_microphone_id_seq', (SELECT MAX(microphone_id) FROM microphone));

-- --------------------------------------------------------
-- project - Projects
-- --------------------------------------------------------
INSERT INTO project (project_id, name, creator_id, url, description, description_short, public, active)
VALUES (1, 'Demo Project', 1, '', 'This is a demo project. You can set this up via the administration page.', 'Demo project for testing', TRUE, TRUE);

SELECT setval('project_project_id_seq', (SELECT MAX(project_id) FROM project));

-- --------------------------------------------------------
-- collection - Collections
-- --------------------------------------------------------
INSERT INTO collection (collection_id, name, creator_id, doi, description, public_access, public_tags)
VALUES (1, 'Demo collection', 1, NULL, 'Open access demo collection', TRUE, TRUE);

SELECT setval('collection_collection_id_seq', (SELECT MAX(collection_id) FROM collection));

-- --------------------------------------------------------
-- project_collection - Project-Collection association
-- --------------------------------------------------------
INSERT INTO project_collection (project_id, collection_id)
VALUES (1, 1);

-- --------------------------------------------------------
-- site - Sites
-- --------------------------------------------------------
INSERT INTO site (site_id, creator_id, name, location, topography_m, freshwater_depth_m, realm_id, biome_id, functional_type_id)
VALUES (1, 1, 'Demo site', ST_SetSRID(ST_MakePoint(0, 0), 4326), 0, 0, NULL, NULL, NULL);

SELECT setval('site_site_id_seq', (SELECT MAX(site_id) FROM site));

-- --------------------------------------------------------
-- site_collection - Site-Collection association
-- --------------------------------------------------------
INSERT INTO site_collection (site_id, collection_id)
VALUES (1, 1);

-- --------------------------------------------------------
-- label - Labels
-- --------------------------------------------------------
INSERT INTO label (label_id, name, type, creator_id)
VALUES (1, 'not analysed', 'public', 1),
       (2, 'tagged', 'public', 1),
       (3, 'reviewed', 'public', 1);

SELECT setval('label_label_id_seq', (SELECT MAX(label_id) FROM label));

-- --------------------------------------------------------
-- setting - Application settings
-- --------------------------------------------------------
INSERT INTO setting (name, value)
VALUES ('fft_window_size', '512'),
       ('preview_width_px', '800'),
       ('preview_height_px', '200'),
       ('max_upload_file_size_mb', '500'),
       ('max_batch_size', '100'),
       ('supported_audio_formats', 'wav,flac,mp3,ogg'),
       ('supported_photo_formats', 'jpg,jpeg,png,tiff'),
       ('supported_video_formats', 'mp4,avi,mov'),
       ('enable_batch_upload', 'true'),
       ('enable_api', 'true'),
       ('enable_ml_inference', 'true'),
       ('default_preview_format', 'spectrogram'),
       ('spectrogram_colormap', 'viridis'),
       ('default_license_id', '1'),
       ('session_timeout_minutes', '60'),
       ('password_min_length', '8'),
       ('enable_user_registration', 'true'),
       ('site_title', 'ecoSignal'),
       ('site_description', 'Ecological Media Management Platform'),
       ('enable_public_projects', 'true'),
       ('enable_annotations', 'true'),
       ('default_language', 'en'),
       ('timezone', 'UTC'),
       ('pagination_size', '20'),
       ('max_search_results', '100');
