-- PostgreSQL database schema for ecoSignal
--
-- 架构：通过API进行数据共享的多实例部署
-- UUID：用于分布式实体（项目、合集、媒体、标注）
-- SERIAL：用于集中管理的参考数据（物种、用户）

-- 为分布式多实例架构启用UUID扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 为地理数据和空间查询启用PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- --------------------------------------------------------
-- 地理数据：通过外部API获取
-- 注意：GADM（adm_0, adm_1, adm_2）和 world_seas 数据
-- 通过外部API访问，而非本地存储。
-- 站点位置使用PostGIS几何图形进行空间操作。
-- --------------------------------------------------------

-- --------------------------------------------------------
-- 生态系统参考数据
-- --------------------------------------------------------

CREATE TABLE iucn_get (
  iucn_get_id SERIAL PRIMARY KEY,
  pid INTEGER NOT NULL,
  name VARCHAR(100) NOT NULL,
  level INTEGER NOT NULL
);

COMMENT ON TABLE iucn_get IS 'IUCN 全球生态系统类型学 (GET) - 生态系统类型的分层分类 (https://global-ecosystems.org/)。用户基于专业知识为站点分配领域/生物群系/功能类型。';
COMMENT ON COLUMN iucn_get.pid IS '用于生态系统分层分类的父级ID';
COMMENT ON COLUMN iucn_get.level IS '层级：1=领域, 2=生物群系, 3=功能组, 4=生态系统类型';

-- --------------------------------------------------------
-- 角色与权限
-- --------------------------------------------------------

CREATE TABLE role (
  role_id SERIAL PRIMARY KEY,
  name VARCHAR(128) NOT NULL UNIQUE
);

COMMENT ON TABLE role IS '用于访问控制的用户角色';

-- --------------------------------------------------------

CREATE TABLE permission (
  permission_id SERIAL PRIMARY KEY,
  resource_type VARCHAR(50) NOT NULL,
  action VARCHAR(20) NOT NULL CHECK (action IN ('read', 'write')),
  name VARCHAR(128) NOT NULL UNIQUE,
  UNIQUE (resource_type, action)
);

CREATE INDEX idx_permission_resource_action ON permission(resource_type, action);

COMMENT ON TABLE permission IS '基于资源的读写操作权限。权限可组合以定义用户角色（访客、审核者、合集管理者等）。未来增强：考虑为控制函数执行（AI模型、声学指数、批量操作）添加 execute 操作。';
COMMENT ON COLUMN permission.resource_type IS '数据库资源/实体类型：project, collection, media, annotation, annotation_review, site 等。随着系统演进可添加新资源。';
COMMENT ON COLUMN permission.action IS '操作类型：read（查看/访问）或 write（创建/编辑/删除）。project:write 和 collection:write 同时具备管理者语义，可管理下级资源。';
COMMENT ON COLUMN permission.name IS '唯一的权限标识符，通常为 resource_type:action 格式（例如，collection:read, annotation:write）';

-- --------------------------------------------------------
-- 用户
-- --------------------------------------------------------

CREATE TABLE "user" (
  user_id SERIAL PRIMARY KEY,
  role_id INTEGER NOT NULL REFERENCES role(role_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  username VARCHAR(20) NOT NULL UNIQUE,
  password VARCHAR(150) NOT NULL,
  name VARCHAR(100) NOT NULL,
  orcid VARCHAR(100),
  email VARCHAR(100) NOT NULL,
  color VARCHAR(7) NOT NULL DEFAULT '#FFFFFF',
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_user_role ON "user"(role_id);
CREATE INDEX idx_user_email ON "user"(email);

COMMENT ON TABLE "user" IS '系统用户（研究员、协作者）。用户首选项存储在 user_preference 表中。';
COMMENT ON COLUMN "user".orcid IS '用于研究者归属的ORCID标识符';

-- --------------------------------------------------------

CREATE TABLE user_preference (
  user_id INTEGER PRIMARY KEY REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  fft INTEGER NOT NULL DEFAULT 512,
  theme VARCHAR(20) DEFAULT 'light' CHECK (theme IN ('light', 'dark', 'auto')),
  language VARCHAR(10) DEFAULT 'en',
  timezone VARCHAR(50) DEFAULT 'UTC',
  notifications_enabled BOOLEAN DEFAULT TRUE,
  updated_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE user_preference IS '用户特定首选项和设置。可为未来首选项扩展。';
COMMENT ON COLUMN user_preference.fft IS '频谱图的默认FFT窗口大小（例如，512, 1024, 2048）';
COMMENT ON COLUMN user_preference.theme IS 'UI主题偏好';
COMMENT ON COLUMN user_preference.language IS '首选语言代码（ISO 639-1）';
COMMENT ON COLUMN user_preference.timezone IS '用于显示的时区（IANA时区）';
COMMENT ON COLUMN user_preference.notifications_enabled IS '启用/禁用系统通知';
COMMENT ON COLUMN user_preference.updated_date IS '首选项的最后更新时间戳';

-- --------------------------------------------------------
-- 项目
-- --------------------------------------------------------

CREATE TABLE project (
  project_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  name VARCHAR(100) NOT NULL,
  creator_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  url VARCHAR(255) NOT NULL,
  picture_id VARCHAR(255),
  description TEXT,
  description_short TEXT,
  doi VARCHAR(255),
  public BOOLEAN NOT NULL DEFAULT TRUE,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_project_uuid ON project(uuid);

COMMENT ON TABLE project IS '包含多个合集的研究项目';
COMMENT ON COLUMN project.uuid IS '用于通过API进行多实例数据共享的全局标识符';
COMMENT ON COLUMN project.creator_id IS '创建项目的用户（主要所有者）。查看 project_contributor 了解其他贡献者。';
COMMENT ON COLUMN project.doi IS '用于引用的数字对象标识符';

-- --------------------------------------------------------

CREATE TABLE project_contributor (
  project_id INTEGER NOT NULL REFERENCES project(project_id) ON DELETE CASCADE ON UPDATE CASCADE,
  user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  contribution_role VARCHAR(100),
  added_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (project_id, user_id)
);

CREATE INDEX idx_project_contributor_user ON project_contributor(user_id);
CREATE INDEX idx_project_contributor_project ON project_contributor(project_id);

COMMENT ON TABLE project_contributor IS '项目贡献者，用于正确归属。创建者在 project.creator_id 中单独追踪。';
COMMENT ON COLUMN project_contributor.contribution_role IS '可选角色描述：PI、研究员、现场技术员、数据分析师等。';
COMMENT ON COLUMN project_contributor.added_date IS '贡献者被添加到项目的时间';

-- --------------------------------------------------------
-- 合集
-- --------------------------------------------------------

CREATE TABLE collection (
  collection_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  name VARCHAR(100) NOT NULL,
  creator_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  doi VARCHAR(255),
  description TEXT,
  sphere VARCHAR(100),
  external_media_url VARCHAR(255),
  project_url VARCHAR(255),
  public_access BOOLEAN NOT NULL DEFAULT FALSE,
  public_tags BOOLEAN NOT NULL DEFAULT FALSE,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_collection_creator ON collection(creator_id);
CREATE INDEX idx_collection_uuid ON collection(uuid);

COMMENT ON TABLE collection IS '具有共享元数据的相关媒体（音频/照片）组。可通过 project_collection 连接表属于多个项目。';
COMMENT ON COLUMN collection.uuid IS '用于通过API进行多实例数据共享的全局标识符';
COMMENT ON COLUMN collection.creator_id IS '创建合集的用户（主要所有者）。查看 collection_contributor 了解其他贡献者。';
COMMENT ON COLUMN collection.doi IS '用于引用的数字对象标识符';
COMMENT ON COLUMN collection.description IS '合集备注和描述';
COMMENT ON COLUMN collection.public_access IS '合集是否公开可访问。仅当其所有项目都公开时，合集才能公开（通过触发器强制实施）。';
COMMENT ON COLUMN collection.public_tags IS '公共用户是否可以添加标注';

-- --------------------------------------------------------

CREATE TABLE collection_contributor (
  collection_id INTEGER NOT NULL REFERENCES collection(collection_id) ON DELETE CASCADE ON UPDATE CASCADE,
  user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  contribution_role VARCHAR(100),
  added_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (collection_id, user_id)
);

CREATE INDEX idx_collection_contributor_user ON collection_contributor(user_id);
CREATE INDEX idx_collection_contributor_collection ON collection_contributor(collection_id);

COMMENT ON TABLE collection_contributor IS '合集贡献者，用于正确归属。创建者在 collection.creator_id 中单独追踪。';
COMMENT ON COLUMN collection_contributor.contribution_role IS '可选角色描述：现场记录员、标注员、审核者、数据管理员等。';
COMMENT ON COLUMN collection_contributor.added_date IS '贡献者被添加到合集的时间';

-- --------------------------------------------------------

CREATE TABLE project_collection (
  project_id INTEGER NOT NULL REFERENCES project(project_id) ON DELETE CASCADE ON UPDATE CASCADE,
  collection_id INTEGER NOT NULL REFERENCES collection(collection_id) ON DELETE CASCADE ON UPDATE CASCADE,
  added_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (project_id, collection_id)
);

CREATE INDEX idx_project_collection_project ON project_collection(project_id);
CREATE INDEX idx_project_collection_collection ON project_collection(collection_id);

COMMENT ON TABLE project_collection IS '多对多关系：合集可以属于多个项目';
COMMENT ON COLUMN project_collection.added_date IS '合集被添加到项目的时间';

-- --------------------------------------------------------
-- 合集 ↔ 物种名录（Catalogue-of-Life）分类单元映射
-- --------------------------------------------------------
-- 将合集映射到任何分类等级的生命目录分类单元。合集可以关联零个、一个或多个CoL分类单元，以表明合集涵盖的分类单元。
-- 我们将外部CoL分类单元ID存储为`col_taxon_id`，并可选择缓存显示名称和等级以便快速过滤。此表设计为轻量级，存储外部标识符而非尝试完全的分类学规范化。
-- 未来，当媒体标注能说明合集涉及哪些分类单元时，我们可能会省略此表。
CREATE TABLE collection_taxon (
  id BIGSERIAL PRIMARY KEY,
  collection_id INTEGER NOT NULL REFERENCES collection(collection_id) ON DELETE CASCADE ON UPDATE CASCADE,
  col_taxon_id VARCHAR(128) NOT NULL,
  col_rank VARCHAR(32) NOT NULL DEFAULT 'species',
  cached_name VARCHAR(255),
  asserted_by INTEGER REFERENCES "user"(user_id) ON DELETE SET NULL,
  asserted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  notes TEXT,
  UNIQUE (collection_id, col_taxon_id)
);

CREATE INDEX idx_collection_taxon_collection_id ON collection_taxon(collection_id);
CREATE INDEX idx_collection_taxon_col_id ON collection_taxon(col_taxon_id);
CREATE INDEX idx_collection_taxon_rank ON collection_taxon(col_rank);

COMMENT ON TABLE collection_taxon IS '为合集分配生命目录（Catalogue-of-Life）分类单元（任何等级）。存储外部CoL分类单元ID、可选的缓存名称、等级以及谁断言的映射。';
COMMENT ON COLUMN collection_taxon.col_taxon_id IS '生命目录分类单元标识符（外部）。可表示任何分类等级。';
COMMENT ON COLUMN collection_taxon.col_rank IS '引用的CoL ID的分类等级（例如 species, genus, family）。仅为了方便和过滤。';
COMMENT ON COLUMN collection_taxon.cached_name IS '可选的缓存科学名称或常用名称，用于无需外部查找的快速显示。';

-- --------------------------------------------------------
-- 用户权限
-- --------------------------------------------------------

CREATE TABLE user_permission (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE RESTRICT,
  permission_id INTEGER NOT NULL REFERENCES permission(permission_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  project_id INTEGER NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
  collection_id INTEGER REFERENCES collection(collection_id) ON DELETE RESTRICT,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_user_perm_project_scope CHECK (project_id IS NOT NULL),
  CONSTRAINT fk_user_perm_project_collection_scope
    FOREIGN KEY (project_id, collection_id)
    REFERENCES project_collection(project_id, collection_id)
    ON DELETE RESTRICT
);

CREATE INDEX idx_user_perm_user ON user_permission(user_id);
CREATE INDEX idx_user_perm_project ON user_permission(project_id) WHERE project_id IS NOT NULL;
CREATE INDEX idx_user_perm_collection ON user_permission(collection_id) WHERE collection_id IS NOT NULL;
CREATE UNIQUE INDEX uq_user_perm_project_scope
  ON user_permission(user_id, permission_id, project_id)
  WHERE collection_id IS NULL;
CREATE UNIQUE INDEX uq_user_perm_project_collection_scope
  ON user_permission(user_id, permission_id, project_id, collection_id)
  WHERE collection_id IS NOT NULL;

COMMENT ON TABLE user_permission IS '用户在项目或项目内集合路径上的显式权限';

-- --------------------------------------------------------
-- 站点（记录位置）
-- --------------------------------------------------------

CREATE TABLE site (
  site_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  creator_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  name VARCHAR(100) NOT NULL,
  location GEOMETRY(Geometry, 4326),
  location_iho GEOMETRY(Geometry, 4326),
  topography_m DOUBLE PRECISION,
  freshwater_depth_m DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  latitude DOUBLE PRECISION,
  iho VARCHAR(200),
  gadm0 VARCHAR(100),
  gadm1 VARCHAR(100),
  gadm2 VARCHAR(100),
  gadm0_gid VARCHAR(100),
  gadm1_gid VARCHAR(100),
  gadm2_gid VARCHAR(100),
  realm_id INTEGER REFERENCES iucn_get(iucn_get_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  biome_id INTEGER REFERENCES iucn_get(iucn_get_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  functional_type_id INTEGER REFERENCES iucn_get(iucn_get_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_site_creator ON site(creator_id);
CREATE INDEX idx_site_name ON site(name);
CREATE INDEX idx_site_location ON site USING GIST (location);
CREATE INDEX idx_site_uuid ON site(uuid);
CREATE INDEX idx_site_realm ON site(realm_id);
CREATE INDEX idx_site_biome ON site(biome_id);
CREATE INDEX idx_site_functional_type ON site(functional_type_id);
CREATE INDEX idx_site_longitude ON site(longitude);
CREATE INDEX idx_site_latitude ON site(latitude);

COMMENT ON TABLE site IS '具有地理和生态元数据的记录位置';
COMMENT ON COLUMN site.uuid IS '用于通过API进行多实例数据共享的全局标识符';
COMMENT ON COLUMN site.creator_id IS '创建站点的用户';
COMMENT ON COLUMN site.location IS 'PostGIS几何图形（SRID 4326）- 可以是点、多边形、多多边形或其他几何类型，用于空间查询';
COMMENT ON COLUMN site.topography_m IS '海拔（米，正值）或深度（负值）';
COMMENT ON COLUMN site.freshwater_depth_m IS '水生站点的水深（米）';
COMMENT ON COLUMN site.realm_id IS 'IUCN GET 领域 - 用户基于专业知识分配的生态系统领域（第1级）';
COMMENT ON COLUMN site.biome_id IS 'IUCN GET 生物群系 - 用户基于专业知识分配的生态系统生物群系（第2级）';
COMMENT ON COLUMN site.functional_type_id IS 'IUCN GET 功能类型 - 用户基于专业知识分配的生态系统功能类型（第3级）';

-- --------------------------------------------------------

CREATE TABLE site_collection (
  site_id INTEGER NOT NULL REFERENCES site(site_id) ON DELETE CASCADE ON UPDATE CASCADE,
  collection_id INTEGER NOT NULL REFERENCES collection(collection_id) ON DELETE CASCADE ON UPDATE CASCADE,
  PRIMARY KEY (site_id, collection_id)
);

CREATE INDEX idx_site_collection_site ON site_collection(site_id);
CREATE INDEX idx_site_collection_collection ON site_collection(collection_id);

COMMENT ON TABLE site_collection IS '站点和合集之间的多对多关系';

-- --------------------------------------------------------

CREATE TABLE site_project (
  site_id INTEGER NOT NULL REFERENCES site(site_id) ON DELETE CASCADE,
  project_id INTEGER NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
  PRIMARY KEY (site_id, project_id)
);

CREATE INDEX idx_site_project_site ON site_project(site_id);
CREATE INDEX idx_site_project_project ON site_project(project_id);
CREATE INDEX idx_site_project_project_site ON site_project(project_id, site_id);

COMMENT ON TABLE site_project IS '站点和项目之间的多对多关系';

-- --------------------------------------------------------
-- 设备
-- --------------------------------------------------------

CREATE TABLE license (
  license_id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  link VARCHAR(255) NOT NULL
);

COMMENT ON TABLE license IS '内容许可证（CC-BY, CC0等）';

-- --------------------------------------------------------

CREATE TABLE recorder (
  recorder_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  name VARCHAR(100),
  version VARCHAR(100),
  brand VARCHAR(100)
);

CREATE INDEX idx_recorder_uuid ON recorder(uuid);

COMMENT ON TABLE recorder IS '音视频记录设备型号。UUID支持跨实例数据共享和中心更新。';
COMMENT ON COLUMN recorder.uuid IS '用于多实例设备数据库同步的全局标识符';

-- --------------------------------------------------------

CREATE TABLE microphone (
  microphone_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  name VARCHAR(100),
  microphone_element VARCHAR(100),
  sensitivity INTEGER,
  signal_to_noise_ratio INTEGER
);

CREATE INDEX idx_microphone_uuid ON microphone(uuid);

COMMENT ON TABLE microphone IS '麦克风规格。UUID支持跨实例数据共享和中心更新。';
COMMENT ON COLUMN microphone.uuid IS '用于多实例设备数据库同步的全局标识符';

-- --------------------------------------------------------

CREATE TABLE recorder_microphone (
  recorder_id INTEGER NOT NULL REFERENCES recorder(recorder_id) ON DELETE CASCADE ON UPDATE CASCADE,
  microphone_id INTEGER NOT NULL REFERENCES microphone(microphone_id) ON DELETE CASCADE ON UPDATE CASCADE,
  is_default BOOLEAN DEFAULT FALSE,
  notes TEXT,
  PRIMARY KEY (recorder_id, microphone_id)
);

CREATE INDEX idx_recorder_microphone_recorder ON recorder_microphone(recorder_id);
CREATE INDEX idx_recorder_microphone_microphone ON recorder_microphone(microphone_id);

COMMENT ON TABLE recorder_microphone IS '多对多关系：兼容麦克风的记录器';
COMMENT ON COLUMN recorder_microphone.is_default IS '这是否是此记录器的默认/推荐麦克风';
COMMENT ON COLUMN recorder_microphone.notes IS '兼容性说明、限制或配置详情';

-- --------------------------------------------------------

CREATE TABLE camera (
  camera_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  name VARCHAR(100),
  version VARCHAR(100),
  brand VARCHAR(100)
);

CREATE INDEX idx_camera_uuid ON camera(uuid);

COMMENT ON TABLE camera IS '用于照片/视频拍摄的相机设备型号。UUID支持跨实例数据共享和中心更新。';
COMMENT ON COLUMN camera.uuid IS '用于多实例设备数据库同步的全局标识符';

-- --------------------------------------------------------

CREATE TABLE lens (
  lens_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  name VARCHAR(100),
  focal_length VARCHAR(50),
  max_aperture VARCHAR(20),
  brand VARCHAR(100)
);

CREATE INDEX idx_lens_uuid ON lens(uuid);

COMMENT ON TABLE lens IS '相机镜头规格。UUID支持跨实例数据共享和中心更新。';
COMMENT ON COLUMN lens.uuid IS '用于多实例设备数据库同步的全局标识符';
COMMENT ON COLUMN lens.focal_length IS '焦距（例如，24mm, 70-200mm, 50mm）';
COMMENT ON COLUMN lens.max_aperture IS '最大光圈（例如，f/1.4, f/2.8）';

-- --------------------------------------------------------

CREATE TABLE camera_lens (
  camera_id INTEGER NOT NULL REFERENCES camera(camera_id) ON DELETE CASCADE ON UPDATE CASCADE,
  lens_id INTEGER NOT NULL REFERENCES lens(lens_id) ON DELETE CASCADE ON UPDATE CASCADE,
  is_default BOOLEAN DEFAULT FALSE,
  notes TEXT,
  PRIMARY KEY (camera_id, lens_id)
);

CREATE INDEX idx_camera_lens_camera ON camera_lens(camera_id);
CREATE INDEX idx_camera_lens_lens ON camera_lens(lens_id);

COMMENT ON TABLE camera_lens IS '多对多关系：兼容镜头的相机';
COMMENT ON COLUMN camera_lens.is_default IS '这是否是此相机的默认/推荐镜头';
COMMENT ON COLUMN camera_lens.notes IS '兼容性说明、卡口类型或配置详情';

-- --------------------------------------------------------
-- 传感器配置
-- --------------------------------------------------------
-- 传感器是用于捕获媒体的具体设备组合：
-- - 对于音频：记录器 + 麦克风组合
-- - 对于照片/视频：相机 + 镜头组合
-- 此表避免在每个媒体行中存储单独的 recorder_id, microphone_id, camera_id, lens_id，并简化了设备追踪。

CREATE TABLE sensor (
  sensor_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  name VARCHAR(255) NOT NULL,
  sensor_type VARCHAR(20) NOT NULL CHECK (sensor_type IN ('audio', 'photo')),
  recorder_id INTEGER REFERENCES recorder(recorder_id) ON DELETE CASCADE ON UPDATE CASCADE,
  microphone_id INTEGER REFERENCES microphone(microphone_id) ON DELETE CASCADE ON UPDATE CASCADE,
  camera_id INTEGER REFERENCES camera(camera_id) ON DELETE CASCADE ON UPDATE CASCADE,
  lens_id INTEGER REFERENCES lens(lens_id) ON DELETE CASCADE ON UPDATE CASCADE,
  description TEXT,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT audio_sensor_check CHECK (
    (sensor_type = 'audio' AND recorder_id IS NOT NULL AND microphone_id IS NOT NULL AND camera_id IS NULL AND lens_id IS NULL) OR
    (sensor_type = 'photo' AND camera_id IS NOT NULL AND lens_id IS NOT NULL AND recorder_id IS NULL AND microphone_id IS NULL)
  )
);

CREATE INDEX idx_sensor_uuid ON sensor(uuid);
CREATE INDEX idx_sensor_type ON sensor(sensor_type);
CREATE INDEX idx_sensor_recorder ON sensor(recorder_id);
CREATE INDEX idx_sensor_microphone ON sensor(microphone_id);
CREATE INDEX idx_sensor_camera ON sensor(camera_id);
CREATE INDEX idx_sensor_lens ON sensor(lens_id);

COMMENT ON TABLE sensor IS '结合设备的具体传感器配置：音频为记录器+麦克风，照片/视频为相机+镜头';
COMMENT ON COLUMN sensor.uuid IS '用于多实例设备数据库同步的全局标识符';
COMMENT ON COLUMN sensor.sensor_type IS '传感器类型：audio（记录器+麦克风）或 photo（相机+镜头）';
COMMENT ON COLUMN sensor.recorder_id IS '音频记录器（音频传感器必需）';
COMMENT ON COLUMN sensor.microphone_id IS '麦克风（音频传感器必需）';
COMMENT ON COLUMN sensor.camera_id IS '相机（照片传感器必需）';
COMMENT ON COLUMN sensor.lens_id IS '镜头（照片传感器必需）';
COMMENT ON CONSTRAINT audio_sensor_check ON sensor IS '确保音频传感器有记录器+麦克风且没有相机/镜头；照片传感器有相机+镜头且没有记录器/麦克风';

-- --------------------------------------------------------
-- 分类学
-- --------------------------------------------------------

CREATE TABLE taxon (
  taxon_id SERIAL PRIMARY KEY,
  -- 用于分层等级的生命目录标识符（存储为文本以适应数字或字符串ID）
  col_species_id VARCHAR(64),
  col_genus_id VARCHAR(64),
  col_family_id VARCHAR(64),
  col_order_id VARCHAR(64),
  col_class_id VARCHAR(64),
  -- 为避免频繁API调用的缓存标签；按需从生命目录获取
  cached_scientific_name VARCHAR(200),
  cached_common_name VARCHAR(200),
  -- 源元数据和同步信息
  taxonomy_source VARCHAR(50) DEFAULT 'CatalogueOfLife',
  last_synced TIMESTAMP WITH TIME ZONE,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_taxon_col_species_id ON taxon(col_species_id);
CREATE INDEX idx_taxon_col_genus_id ON taxon(col_genus_id);
CREATE INDEX idx_taxon_col_family_id ON taxon(col_family_id);

COMMENT ON TABLE taxon IS '最小化的分类单元表，存储生命目录（CoL）ID用于分类等级和少量缓存标签。完整的分类学信息按需从CoL API检索。';
COMMENT ON COLUMN taxon.col_species_id IS '物种级分类单元的生命目录分类单元ID';
COMMENT ON COLUMN taxon.col_genus_id IS '属级分类单元的生命目录分类单元ID';
COMMENT ON COLUMN taxon.col_family_id IS '科级分类单元的生命目录分类单元ID';
COMMENT ON COLUMN taxon.cached_scientific_name IS '为避免常见查询的API调用的缓存科学名称';
COMMENT ON COLUMN taxon.cached_common_name IS '可用时的缓存俗名/常用名';
COMMENT ON COLUMN taxon.taxonomy_source IS '规范的分类学来源（例如，CatalogueOfLife）';
COMMENT ON COLUMN taxon.last_synced IS '此记录上次与外部分类学API同步的时间戳';

-- --------------------------------------------------------

CREATE TABLE taxon_sound_type (
  taxon_sound_type_id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  taxon_class VARCHAR(20) NOT NULL,
  taxon_order VARCHAR(20) NOT NULL
);

COMMENT ON TABLE taxon_sound_type IS '与分类学纲/目相关联的动物发声类型（叫声、鸣叫、警报声等）';

-- --------------------------------------------------------

CREATE TABLE sound_classification (
  sound_id SERIAL PRIMARY KEY,
  soundscape_component VARCHAR(200),
  sound_type VARCHAR(30)
);

COMMENT ON TABLE sound_classification IS '声景组成成分（生物声、地声、人类声）';

-- --------------------------------------------------------
-- 媒体（音频记录和照片）
-- --------------------------------------------------------

CREATE TABLE audio_setting (
  audio_setting_id SERIAL PRIMARY KEY,
  recording_gain_dB INTEGER,
  sampling_rate_Hz INTEGER NOT NULL DEFAULT 44100,
  bit_depth INTEGER DEFAULT 16,
  channel_num INTEGER DEFAULT 1,
  duration_s REAL NOT NULL,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audio_setting_sampling_rate ON audio_setting(sampling_rate_Hz);
CREATE INDEX idx_audio_setting_bit_depth ON audio_setting(bit_depth);

COMMENT ON TABLE audio_setting IS '媒体记录的音频特定技术设置';
COMMENT ON COLUMN audio_setting.recording_gain_dB IS '记录增益（分贝）';
COMMENT ON COLUMN audio_setting.sampling_rate_Hz IS '采样率（赫兹）';
COMMENT ON COLUMN audio_setting.bit_depth IS '位深度（例如，16, 24, 32）';
COMMENT ON COLUMN audio_setting.channel_num IS '音频通道数';
COMMENT ON COLUMN audio_setting.duration_s IS '持续时间（秒）';

-- --------------------------------------------------------

CREATE TABLE photo_setting (
  photo_setting_id SERIAL PRIMARY KEY,
  exposure_ms REAL,
  aperture REAL,
  iso INTEGER,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE photo_setting IS '媒体的照片/视频特定技术设置';
COMMENT ON COLUMN photo_setting.exposure_ms IS '曝光时间（毫秒）';
COMMENT ON COLUMN photo_setting.aperture IS 'F值（光圈）';
COMMENT ON COLUMN photo_setting.iso IS '传感器的ISO增益';

-- --------------------------------------------------------

CREATE TABLE media (
  media_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  media_type VARCHAR(20) NOT NULL CHECK (media_type IN ('audio', 'photo', 'video')),
  is_metadata BOOLEAN NOT NULL,
  directory INTEGER,
  filename VARCHAR(250),
  name VARCHAR(250),
  uploader_id INTEGER REFERENCES "user"(user_id) ON DELETE SET NULL ON UPDATE CASCADE,
  creator_id INTEGER REFERENCES "user"(user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  site_id INTEGER REFERENCES site(site_id) ON DELETE SET NULL ON UPDATE CASCADE,
  sensor_id INTEGER REFERENCES sensor(sensor_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  license_id INTEGER REFERENCES license(license_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  audio_setting_id INTEGER REFERENCES audio_setting(audio_setting_id) ON DELETE SET NULL ON UPDATE CASCADE,
  photo_setting_id INTEGER REFERENCES photo_setting(photo_setting_id) ON DELETE SET NULL ON UPDATE CASCADE,
  medium VARCHAR(50),
  duty_cycle_recording INTEGER,
  duty_cycle_period INTEGER,
  note VARCHAR(250),
  date_time TIMESTAMP WITH TIME ZONE,
  size_B BIGINT,
  md5_hash CHAR(32),
  doi VARCHAR(255),
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT audio_photo_setting_check CHECK (
    (media_type = 'audio' AND is_metadata = FALSE AND audio_setting_id IS NOT NULL AND photo_setting_id IS NULL) OR
    (media_type IN ('photo', 'video') AND photo_setting_id IS NOT NULL AND audio_setting_id IS NULL) OR
    (media_type = 'audio' AND is_metadata = TRUE AND photo_setting_id IS NULL)
  )
);

CREATE INDEX idx_media_site ON media(site_id);
CREATE INDEX idx_media_uploader ON media(uploader_id);
CREATE INDEX idx_media_creator ON media(creator_id);
CREATE INDEX idx_media_sensor ON media(sensor_id);
CREATE INDEX idx_media_audio_setting ON media(audio_setting_id);
CREATE INDEX idx_media_photo_setting ON media(photo_setting_id);
CREATE INDEX idx_media_datetime ON media(date_time);
CREATE INDEX idx_media_md5 ON media(md5_hash);
CREATE INDEX idx_media_uuid ON media(uuid);
CREATE INDEX idx_media_type ON media(media_type);
CREATE INDEX ix_media_is_metadata ON media(is_metadata);
CREATE INDEX idx_media_type_media_id ON media(media_type, media_id);
CREATE INDEX idx_media_timeline_type_name_id ON media(media_type, name, media_id);
CREATE INDEX idx_media_site_media_not_null ON media(site_id, media_id) WHERE site_id IS NOT NULL;

COMMENT ON TABLE media IS '媒体文件（音频记录、照片、视频）及其核心元数据。媒体可通过 media_collection 连接表属于多个合集。设计决策：媒体可以存在而不被分配到任何合集（孤立状态），以支持分阶段上传和工作流程灵活性。';
COMMENT ON COLUMN media.uuid IS '用于通过API进行多实例数据共享的全局标识符';
COMMENT ON COLUMN media.media_type IS '媒体类型：audio, photo, video';
COMMENT ON COLUMN media.is_metadata IS '音频记录是否为元数据文件';
COMMENT ON COLUMN media.audio_setting_id IS '音频技术设置（音频媒体类型必需）';
COMMENT ON COLUMN media.photo_setting_id IS '照片技术设置（照片/视频媒体类型必需）';
COMMENT ON CONSTRAINT audio_photo_setting_check ON media IS '为音频媒体强制使用音频设置，为照片/视频媒体强制使用照片设置，音频元数据文件不要求音频设置';
COMMENT ON COLUMN media.uploader_id IS '上传媒体文件的用户';
COMMENT ON COLUMN media.creator_id IS '媒体的原始创建者/记录者（由应用程序逻辑设置，通常与 uploader_id 相同）';
COMMENT ON COLUMN media.sensor_id IS '用于捕获媒体的传感器配置（结合记录器+麦克风或相机+镜头）';
COMMENT ON COLUMN media.date_time IS '媒体记录/捕获的日期和时间';
COMMENT ON COLUMN media.size_B IS '文件大小（字节）';
COMMENT ON COLUMN media.md5_hash IS '用于文件完整性验证的MD5哈希';
COMMENT ON COLUMN media.doi IS '用于引用的数字对象标识符';
COMMENT ON COLUMN media.duty_cycle_recording IS '占空比记录器的记录持续时间（秒，仅音频）';
COMMENT ON COLUMN media.duty_cycle_period IS '占空比记录器的总周期（秒，仅音频）';

-- --------------------------------------------------------
-- 文件上传管理
-- --------------------------------------------------------

CREATE TABLE file_upload (
  file_upload_id SERIAL PRIMARY KEY,
  batch_id UUID,
  path TEXT NOT NULL,
  status INTEGER NOT NULL DEFAULT 1,
  filename VARCHAR(250) NOT NULL,
  name VARCHAR(250) NOT NULL,
  media_id INTEGER REFERENCES media(media_id) ON DELETE SET NULL ON UPDATE CASCADE,
  directory INTEGER NOT NULL,
  uploader_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  error TEXT,
  upload_date_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_file_upload_batch ON file_upload(batch_id);
CREATE INDEX idx_file_upload_uploader ON file_upload(uploader_id);
CREATE INDEX idx_file_upload_status ON file_upload(status);
CREATE INDEX idx_file_upload_media ON file_upload(media_id);

COMMENT ON TABLE file_upload IS '媒体文件上传的暂存表：跟踪上传状态并链接到已处理的媒体';
COMMENT ON COLUMN file_upload.batch_id IS '上传批次标识符（分组在一次用户操作中上传的文件）';
COMMENT ON COLUMN file_upload.status IS '处理状态：1=待处理, 2=处理中, 3=完成, 4=错误';

-- --------------------------------------------------------
-- 媒体 ↔ 合集映射
-- --------------------------------------------------------

CREATE TABLE media_collection (
  media_id INTEGER NOT NULL REFERENCES media(media_id) ON DELETE CASCADE ON UPDATE CASCADE,
  collection_id INTEGER NOT NULL REFERENCES collection(collection_id) ON DELETE CASCADE ON UPDATE CASCADE,
  added_by INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  added_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (media_id, collection_id)
);

CREATE INDEX idx_media_collection_media ON media_collection(media_id);
CREATE INDEX idx_media_collection_collection ON media_collection(collection_id);
CREATE INDEX idx_media_collection_added_by ON media_collection(added_by);
CREATE INDEX idx_media_collection_collection_media ON media_collection(collection_id, media_id);

COMMENT ON TABLE media_collection IS '多对多关系：媒体可以属于多个合集';
COMMENT ON COLUMN media_collection.added_by IS '将此媒体与合集关联的用户';
COMMENT ON COLUMN media_collection.added_date IS '媒体被添加到合集的时间';

-- --------------------------------------------------------
-- 频谱图
-- --------------------------------------------------------

CREATE TABLE preview (
  preview_id SERIAL PRIMARY KEY,
  media_id INTEGER NOT NULL REFERENCES media(media_id) ON DELETE CASCADE ON UPDATE CASCADE,
  filename VARCHAR(250) NOT NULL,
  type VARCHAR(30) NOT NULL CHECK (type IN ('spectrogram', 'waveform', 'thumbnail')),
  created_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_preview_media ON preview(media_id);
CREATE INDEX idx_preview_type ON preview(type);

COMMENT ON TABLE preview IS '媒体的预览表示：音频的频谱图/波形图，照片/视频的缩略图';
COMMENT ON COLUMN preview.type IS '预览类型：spectrogram 或 waveform 用于音频，thumbnail 用于照片/视频';

-- --------------------------------------------------------
-- 标签（用于组织的标记）
-- --------------------------------------------------------

CREATE TABLE label (
  label_id SERIAL PRIMARY KEY,
  name VARCHAR(20) NOT NULL,
  type VARCHAR(20) NOT NULL DEFAULT 'private',
  creator_id INTEGER REFERENCES "user"(user_id) ON DELETE SET NULL ON UPDATE CASCADE,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT ck_label_type CHECK (type IN ('private', 'public'))
);

COMMENT ON TABLE label IS '用户定义的标签，用于组织媒体';

-- --------------------------------------------------------

CREATE TABLE label_media (
  media_id INTEGER NOT NULL REFERENCES media(media_id) ON DELETE CASCADE ON UPDATE CASCADE,
  user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  label_id INTEGER NOT NULL REFERENCES label(label_id) ON DELETE CASCADE ON UPDATE CASCADE,
  PRIMARY KEY (media_id, user_id, label_id)
);

CREATE INDEX idx_label_media_media ON label_media(media_id);
CREATE INDEX idx_label_media_user ON label_media(user_id);
CREATE INDEX idx_label_media_label ON label_media(label_id);
CREATE INDEX idx_label_media_user_label_media ON label_media(user_id, label_id, media_id);

COMMENT ON TABLE label_media IS '多对多：用户对媒体应用标签';

-- --------------------------------------------------------
-- 标注（原架构中的'tags'）
-- --------------------------------------------------------

CREATE TABLE annotation (
  annotation_id SERIAL PRIMARY KEY,
  uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
  sound_id INTEGER NOT NULL REFERENCES sound_classification(sound_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  media_id INTEGER NOT NULL REFERENCES media(media_id) ON DELETE CASCADE ON UPDATE CASCADE,
  creator_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  creator_type VARCHAR(128) DEFAULT 'user',
  confidence REAL,
  min_x REAL NOT NULL,
  max_x REAL NOT NULL,
  min_y REAL NOT NULL,
  max_y REAL NOT NULL,
  taxon_id INTEGER REFERENCES taxon(taxon_id) ON DELETE CASCADE ON UPDATE CASCADE,
  uncertain BOOLEAN,
  sound_distance_m INTEGER,
  distance_not_estimable BOOLEAN,
  individual_num INTEGER NOT NULL DEFAULT 1 CHECK (individual_num >= 1),
  animal_sound_type VARCHAR(128),
  reference BOOLEAN NOT NULL DEFAULT FALSE,
  comments VARCHAR(500),
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_annotation_taxon ON annotation(taxon_id);
CREATE INDEX idx_annotation_creator ON annotation(creator_id);
CREATE INDEX idx_annotation_media ON annotation(media_id);
CREATE INDEX idx_annotation_sound ON annotation(sound_id);
CREATE INDEX idx_annotation_creation_date ON annotation(creation_date);
CREATE INDEX idx_annotation_uuid ON annotation(uuid);
CREATE INDEX idx_annotation_media_annotation_id ON annotation(media_id, annotation_id);

COMMENT ON TABLE annotation IS '媒体上的标注：带有分类识别的边界框（音频为时间/频谱，照片为空间）';
COMMENT ON COLUMN annotation.uuid IS '用于通过API进行多实例数据共享的全局标识符';
COMMENT ON COLUMN annotation.creator_type IS '来源：user, model, automated 等。';
COMMENT ON COLUMN annotation.confidence IS '自动标注的置信度分数（0-1）';
COMMENT ON COLUMN annotation.min_x IS '开始时间（秒，音频）或左侧坐标（像素，照片）';
COMMENT ON COLUMN annotation.max_x IS '结束时间（秒，音频）或右侧坐标（像素，照片）';
COMMENT ON COLUMN annotation.min_y IS '最小频率（赫兹，音频）或顶部坐标（像素，照片）';
COMMENT ON COLUMN annotation.max_y IS '最大频率（赫兹，音频）或底部坐标（像素，照片）';
COMMENT ON COLUMN annotation.uncertain IS '用户标记识别为不确定';
COMMENT ON COLUMN annotation.sound_distance_m IS '到声源的估计距离（米，仅音频）';
COMMENT ON COLUMN annotation.individual_num IS '个体动物数量（最小为1）';
COMMENT ON COLUMN annotation.animal_sound_type IS '动物声音类型（仅音频）';
COMMENT ON COLUMN annotation.reference IS '用于训练的高质量参考标注';

-- --------------------------------------------------------
-- 标注审核系统
-- --------------------------------------------------------

CREATE TABLE annotation_review_status (
  annotation_review_status_id SERIAL PRIMARY KEY,
  name VARCHAR(128) NOT NULL
);

COMMENT ON TABLE annotation_review_status IS '标注验证状态：approved, rejected, needs_review 等。';

-- --------------------------------------------------------

CREATE TABLE annotation_review (
  annotation_id INTEGER NOT NULL REFERENCES annotation(annotation_id) ON DELETE CASCADE ON UPDATE CASCADE,
  reviewer_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  annotation_review_status_id INTEGER NOT NULL REFERENCES annotation_review_status(annotation_review_status_id) ON DELETE CASCADE ON UPDATE CASCADE,
  taxon_id INTEGER REFERENCES taxon(taxon_id) ON DELETE CASCADE ON UPDATE CASCADE,
  note VARCHAR(200),
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (annotation_id, reviewer_id)
);

CREATE INDEX idx_annotation_review_status ON annotation_review(annotation_review_status_id);
CREATE INDEX idx_annotation_review_reviewer ON annotation_review(reviewer_id);
CREATE INDEX idx_annotation_review_taxon ON annotation_review(taxon_id);

COMMENT ON TABLE annotation_review IS '其他用户对标注的同行审核';
COMMENT ON COLUMN annotation_review.taxon_id IS '审核者可以建议替代的分类单元（生命目录ID）';

-- --------------------------------------------------------
-- 任务
-- --------------------------------------------------------

CREATE TABLE task (
  task_id SERIAL PRIMARY KEY,
  type VARCHAR(255) NOT NULL,
  media_id INTEGER REFERENCES media(media_id) ON DELETE SET NULL ON UPDATE CASCADE,
  annotation_id INTEGER REFERENCES annotation(annotation_id) ON DELETE SET NULL ON UPDATE CASCADE,
  assigner_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  assignee_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  status VARCHAR(20) NOT NULL DEFAULT 'assigned',
  comment VARCHAR(500),
  datetime TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_task_assigner ON task(assigner_id);
CREATE INDEX idx_task_assignee ON task(assignee_id);
CREATE INDEX idx_task_media ON task(media_id);
CREATE INDEX idx_task_annotation ON task(annotation_id);
CREATE INDEX idx_task_status ON task(status);

COMMENT ON TABLE task IS '用户分配的审核和标注任务';

-- --------------------------------------------------------
-- 声学指数
-- --------------------------------------------------------

CREATE TABLE index_type (
  index_id SERIAL PRIMARY KEY,
  name VARCHAR(100),
  param JSONB,
  description VARCHAR(255),
  url VARCHAR(100)
);

COMMENT ON TABLE index_type IS '声学指数类型（ACI, NDSI, BI等）及其参数';
COMMENT ON COLUMN index_type.param IS '用于指数计算的JSON参数';

-- --------------------------------------------------------

CREATE TABLE index_log (
  log_id SERIAL,
  media_id INTEGER NOT NULL REFERENCES media(media_id) ON DELETE CASCADE ON UPDATE CASCADE,
  user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  index_id INTEGER NOT NULL REFERENCES index_type(index_id) ON DELETE CASCADE ON UPDATE CASCADE,
  version VARCHAR(100),
  min_time VARCHAR(100),
  max_time VARCHAR(100),
  min_frequency VARCHAR(100),
  max_frequency VARCHAR(100),
  variable_type VARCHAR(100),
  variable_order INTEGER NOT NULL,
  variable_name VARCHAR(100),
  variable_value VARCHAR(100),
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_index_log_composite ON index_log(log_id, media_id, index_id);
CREATE INDEX idx_index_log_media ON index_log(media_id);

COMMENT ON TABLE index_log IS '用于声景分析的已计算声学指数（仅音频媒体）';
COMMENT ON COLUMN index_log.version IS '使用的软件/算法版本';

-- --------------------------------------------------------
-- ML 模型
-- --------------------------------------------------------

CREATE TABLE model (
  model_id SERIAL PRIMARY KEY,
  name VARCHAR(100),
  model_path VARCHAR(255),
  labels_path VARCHAR(255),
  source_url VARCHAR(255),
  description TEXT,
  parameter JSONB
);

COMMENT ON TABLE model IS '用于自动物种识别的机器学习模型';
COMMENT ON COLUMN model.parameter IS 'JSON模型配置和超参数';

-- --------------------------------------------------------
-- 作业队列
-- --------------------------------------------------------

CREATE TABLE queue (
  queue_id SERIAL PRIMARY KEY,
  type VARCHAR(100) NOT NULL,
  user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  completed INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  status INTEGER NOT NULL DEFAULT 0,
  start_time TIMESTAMP WITH TIME ZONE,
  stop_time TIMESTAMP WITH TIME ZONE,
  error TEXT,
  warning TEXT
);

CREATE INDEX idx_queue_user ON queue(user_id);
CREATE INDEX idx_queue_status ON queue(status);

COMMENT ON TABLE queue IS '用于长时间运行任务的背景作业队列';
COMMENT ON COLUMN queue.type IS '作业类型：spectrogram, index, model_inference 等。';
COMMENT ON COLUMN queue.status IS '0=待处理, 1=运行中, 2=完成, 3=错误';

-- --------------------------------------------------------
-- 新闻/公告
-- --------------------------------------------------------

CREATE TABLE news (
  news_id SERIAL PRIMARY KEY,
  title VARCHAR(100) NOT NULL,
  content TEXT NOT NULL,
  writer_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  creation_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_news_creation_date ON news(creation_date DESC);
CREATE INDEX idx_news_writer ON news(writer_id);

COMMENT ON TABLE news IS '系统公告和新闻项目';
COMMENT ON COLUMN news.writer_id IS '创建/撰写新闻项的用户';

-- --------------------------------------------------------
-- 应用设置
-- --------------------------------------------------------

CREATE TABLE setting (
  name VARCHAR(100) PRIMARY KEY,
  value TEXT NOT NULL
);

COMMENT ON TABLE setting IS '应用范围的配置设置（键值对）。Web开发人员应填充适当的值。';

-- 可配置的示例设置键（开发人员确定实际值）：
-- fft_window_size, preview_width_px, preview_height_px, max_upload_file_size_mb,
-- max_batch_size, supported_audio_formats, supported_photo_formats, supported_video_formats,
-- enable_batch_upload, enable_api, enable_ml_inference, default_preview_format,
-- spectrogram_colormap, waveform_color, thumbnail_width_px, thumbnail_height_px,
-- default_license_id, session_timeout_minutes, password_min_length, enable_user_registration,
-- smtp_server, smtp_port, smtp_from_email, site_title, site_description, site_logo_url,
-- enable_public_projects, enable_annotations, default_language, timezone, enable_analytics,
-- analytics_retention_days, backup_enabled, backup_frequency_hours, enable_dark_mode,
-- ui_theme, pagination_size, max_search_results

-- --------------------------------------------------------
-- 网络节点
-- --------------------------------------------------------

CREATE TABLE network_node (
  node_id SERIAL PRIMARY KEY,
  app_url VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  is_local BOOLEAN NOT NULL,
  shared BOOLEAN NOT NULL,
  stat_users INTEGER NOT NULL,
  stat_projects INTEGER NOT NULL,
  stat_collections INTEGER NOT NULL,
  stat_audios INTEGER NOT NULL,
  stat_photos INTEGER NOT NULL,
  stat_videos INTEGER NOT NULL,
  stat_annotations INTEGER NOT NULL,
  stat_sites INTEGER NOT NULL,
  last_synced_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX ix_network_node_app_url ON network_node(app_url);
CREATE INDEX ix_network_node_is_local ON network_node(is_local);
CREATE INDEX ix_network_node_shared ON network_node(shared);

COMMENT ON TABLE network_node IS '系统网络节点信息';

-- --------------------------------------------------------
-- 操作日志
-- --------------------------------------------------------

CREATE TABLE operation_log (
  log_id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES "user"(user_id) ON DELETE SET NULL,
  action VARCHAR(50) NOT NULL,
  resource_type VARCHAR(100) NOT NULL,
  resource_id VARCHAR(100),
  description VARCHAR,
  req_ip VARCHAR(50),
  req_endpoint VARCHAR(255),
  payload JSON,
  status_code INTEGER NOT NULL,
  creation_date TIMESTAMP NOT NULL
);

CREATE INDEX ix_operation_log_action ON operation_log(action);
CREATE INDEX ix_operation_log_creation_date ON operation_log(creation_date);
CREATE INDEX ix_operation_log_resource_id ON operation_log(resource_id);
CREATE INDEX ix_operation_log_resource_type ON operation_log(resource_type);
CREATE INDEX ix_operation_log_user_id ON operation_log(user_id);

COMMENT ON TABLE operation_log IS '系统操作日志';

-- --------------------------------------------------------
-- 访问控制视图
-- --------------------------------------------------------

CREATE VIEW user_effective_permissions AS
SELECT up.user_id,
       up.project_id,
       NULL::integer AS collection_id,
       'project'::varchar AS scope_type,
       p.resource_type,
       p.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NULL
  AND p.resource_type = 'project'
  AND p.action = 'read'

UNION

SELECT up.user_id,
       up.project_id,
       NULL::integer AS collection_id,
       'project'::varchar AS scope_type,
       'project'::varchar AS resource_type,
       sub.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
CROSS JOIN (
    VALUES
        ('read'::varchar),
        ('write'::varchar)
) sub(action)
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NULL
  AND p.resource_type = 'project'
  AND p.action = 'write'

UNION

SELECT up.user_id,
       up.project_id,
       up.collection_id,
       'project_collection'::varchar AS scope_type,
       p.resource_type,
       p.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NOT NULL
  AND p.action = 'read'

UNION

SELECT up.user_id,
       up.project_id,
       up.collection_id,
       'project_collection'::varchar AS scope_type,
       p.resource_type,
       sub.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
CROSS JOIN (
    VALUES
        ('read'::varchar),
        ('write'::varchar)
) sub(action)
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NOT NULL
  AND p.action = 'write'

UNION

SELECT up.user_id,
       up.project_id,
       pc.collection_id,
       'project_collection'::varchar AS scope_type,
       p.resource_type,
       p.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
JOIN project_collection pc ON pc.project_id = up.project_id
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NULL
  AND p.resource_type IN ('audio', 'site', 'annotation', 'review')
  AND p.action = 'read'

UNION

SELECT up.user_id,
       up.project_id,
       pc.collection_id,
       'project_collection'::varchar AS scope_type,
       p.resource_type,
       sub.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
JOIN project_collection pc ON pc.project_id = up.project_id
CROSS JOIN (
    VALUES
        ('read'::varchar),
        ('write'::varchar)
) sub(action)
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NULL
  AND p.resource_type IN ('audio', 'site', 'annotation', 'review')
  AND p.action = 'write'

UNION

SELECT up.user_id,
       up.project_id,
       up.collection_id,
       'project_collection'::varchar AS scope_type,
       sub.resource_type,
       sub.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
CROSS JOIN (
    VALUES
        ('collection', 'read'),
        ('collection', 'write'),
        ('audio',      'read'),
        ('audio',      'write'),
        ('site',       'read'),
        ('site',       'write'),
        ('annotation', 'read'),
        ('annotation', 'write'),
        ('review',     'read'),
        ('review',     'write')
) sub(resource_type, action)
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NOT NULL
  AND p.resource_type = 'collection'
  AND p.action = 'write'

UNION

SELECT up.user_id,
       up.project_id,
       pc.collection_id,
       'project_collection'::varchar AS scope_type,
       sub.resource_type,
       sub.action
FROM user_permission up
JOIN permission p ON up.permission_id = p.permission_id
JOIN project_collection pc ON pc.project_id = up.project_id
CROSS JOIN (
    VALUES
        ('collection', 'read'),
        ('collection', 'write'),
        ('audio',      'read'),
        ('audio',      'write'),
        ('site',       'read'),
        ('site',       'write'),
        ('annotation', 'read'),
        ('annotation', 'write'),
        ('review',     'read'),
        ('review',     'write')
) sub(resource_type, action)
WHERE up.project_id IS NOT NULL
  AND up.collection_id IS NULL
  AND p.resource_type = 'project'
  AND p.action = 'write';

CREATE VIEW user_accessible_collections AS
SELECT user_id, project_id, collection_id, resource_type, action
FROM user_effective_permissions
WHERE scope_type = 'project_collection';

COMMENT ON VIEW user_effective_permissions IS '用户有效权限：包含项目和项目内集合路径的继承展开结果';
COMMENT ON VIEW user_accessible_collections IS '用户可访问集合路径权限：由有效权限视图筛选集合范围结果';

-- --------------------------------------------------------
-- 约束和触发器
-- --------------------------------------------------------

-- 约束：公开合集只能存在于公开项目中
CREATE OR REPLACE FUNCTION check_collection_public_constraint()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.public_access = true THEN
    IF EXISTS (
      SELECT 1 FROM project_collection pc
      JOIN project p ON pc.project_id = p.project_id
      WHERE pc.collection_id = NEW.collection_id
        AND p.public = false
    ) THEN
      RAISE EXCEPTION 'Collection cannot be public when associated with non-public projects';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_collection_public_constraint
  BEFORE INSERT OR UPDATE OF public_access ON collection
  FOR EACH ROW
  EXECUTE FUNCTION check_collection_public_constraint();

COMMENT ON FUNCTION check_collection_public_constraint IS '确保合集仅在所有关联项目都公开时才能公开';

-- 约束：防止在有公开合集的情况下将项目设为私有
CREATE OR REPLACE FUNCTION check_project_public_constraint()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.public = false THEN
    IF EXISTS (
      SELECT 1 FROM project_collection pc
      JOIN collection c ON pc.collection_id = c.collection_id
      WHERE pc.project_id = NEW.project_id
        AND c.public_access = true
    ) THEN
      RAISE EXCEPTION 'Project cannot be made private while it has public collections';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_project_public_constraint
  BEFORE UPDATE OF public ON project
  FOR EACH ROW
  EXECUTE FUNCTION check_project_public_constraint();

COMMENT ON FUNCTION check_project_public_constraint IS '确保项目在有公开合集时不能设为私有';

-- 约束：将合集添加到项目时检查公开约束
CREATE OR REPLACE FUNCTION check_project_collection_public_constraint()
RETURNS TRIGGER AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM collection c
    JOIN project p ON p.project_id = NEW.project_id
    WHERE c.collection_id = NEW.collection_id
      AND c.public_access = true
      AND p.public = false
  ) THEN
    RAISE EXCEPTION 'Cannot add public collection to non-public project';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_project_collection_public_constraint
  BEFORE INSERT ON project_collection
  FOR EACH ROW
  EXECUTE FUNCTION check_project_collection_public_constraint();

COMMENT ON FUNCTION check_project_collection_public_constraint IS '确保公开合集不能被添加到非公开项目';
