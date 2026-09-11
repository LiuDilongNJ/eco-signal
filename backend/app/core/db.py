"""
Database connection and initialization module.
"""
from sqlmodel import Session, create_engine, select, text

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import Camera, Lens, Microphone, Recorder, Role, Sensor, User
from app.repositories import role_repository
from app.schemas.role import RoleCreate

engine = create_engine(
    str(settings.sqlalchemy_database_uri),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
)


DEFAULT_TEST_RECORDER_NAME = "Test Recorder"
DEFAULT_TEST_MICROPHONE_NAME = "Test Microphone"
DEFAULT_TEST_CAMERA_NAME = "Test Camera"
DEFAULT_TEST_LENS_NAME = "Test Lens"
DEFAULT_TEST_AUDIO_SENSOR_NAME = "Test Audio Sensor"
DEFAULT_TEST_PHOTO_SENSOR_NAME = "Test Photo Sensor"


def ensure_default_sensors(session: Session) -> None:
    """Create test sensors required for first-run media uploads."""
    recorder = session.exec(
        select(Recorder).where(Recorder.name == DEFAULT_TEST_RECORDER_NAME)
    ).first()
    if not recorder:
        recorder = Recorder(name=DEFAULT_TEST_RECORDER_NAME, brand="ecoSignal", version="test")
        session.add(recorder)

    microphone = session.exec(
        select(Microphone).where(Microphone.name == DEFAULT_TEST_MICROPHONE_NAME)
    ).first()
    if not microphone:
        microphone = Microphone(
            name=DEFAULT_TEST_MICROPHONE_NAME,
            microphone_element="test",
        )
        session.add(microphone)

    camera = session.exec(
        select(Camera).where(Camera.name == DEFAULT_TEST_CAMERA_NAME)
    ).first()
    if not camera:
        camera = Camera(name=DEFAULT_TEST_CAMERA_NAME, brand="ecoSignal", version="test")
        session.add(camera)

    lens = session.exec(
        select(Lens).where(Lens.name == DEFAULT_TEST_LENS_NAME)
    ).first()
    if not lens:
        lens = Lens(name=DEFAULT_TEST_LENS_NAME, brand="ecoSignal")
        session.add(lens)

    session.commit()
    for device in (recorder, microphone, camera, lens):
        session.refresh(device)

    audio_sensor = session.exec(
        select(Sensor).where(
            Sensor.name == DEFAULT_TEST_AUDIO_SENSOR_NAME,
            Sensor.sensor_type == "audio",
        )
    ).first()
    if not audio_sensor:
        session.add(
            Sensor(
                name=DEFAULT_TEST_AUDIO_SENSOR_NAME,
                sensor_type="audio",
                recorder_id=recorder.recorder_id,
                microphone_id=microphone.microphone_id,
                description="Default test recorder-microphone combination for first-run uploads.",
                serial_number="TEST-AUDIO-001",
            )
        )

    photo_sensor = session.exec(
        select(Sensor).where(
            Sensor.name == DEFAULT_TEST_PHOTO_SENSOR_NAME,
            Sensor.sensor_type == "photo",
        )
    ).first()
    if not photo_sensor:
        session.add(
            Sensor(
                name=DEFAULT_TEST_PHOTO_SENSOR_NAME,
                sensor_type="photo",
                camera_id=camera.camera_id,
                lens_id=lens.lens_id,
                description="Default test camera-lens combination for first-run uploads.",
                serial_number="TEST-PHOTO-001",
            )
        )

    session.commit()


def sync_db_sequences(session: Session) -> None:
    """Synchronize all PostgreSQL sequence values with the current maximum column values."""
    bind = session.get_bind()
    if bind is None or getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return

    sync_sql = text(
        """
        DO $$
        DECLARE
            r RECORD;
            v_max BIGINT;
        BEGIN
            FOR r IN (
                SELECT 
                    t.relname AS tbl,
                    a.attname AS col,
                    s.relname AS seq
                FROM pg_class s
                JOIN pg_depend d ON d.objid = s.oid
                JOIN pg_class t ON d.refobjid = t.oid
                JOIN pg_attribute a ON (d.refobjid = a.attrelid AND d.refobjsubid = a.attnum)
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE s.relkind = 'S'
                  AND n.nspname = 'public'
                  AND t.relkind = 'r'
                ORDER BY t.relname
            ) LOOP
                EXECUTE format('SELECT COALESCE(MAX(%I), 0) FROM %I', r.col, r.tbl) INTO v_max;
                IF v_max > 0 THEN
                    EXECUTE format('SELECT setval(%L, %s, true)', r.seq, v_max);
                END IF;
            END LOOP;
        END $$;
        """
    )
    session.exec(sync_sql)
    session.commit()


def init_db(session: Session) -> None:
    """Initialize database with the configured superuser account."""
    admin_role: Role = session.exec(
        select(Role).where(Role.name == settings.ADMIN_ROLE_NAME)
    ).first()
    if not admin_role:
        role_in = RoleCreate(name=settings.ADMIN_ROLE_NAME)
        admin_role: Role = role_repository.create(session=session, obj_in=role_in)

    user: User | None = session.exec(
        select(User).where(User.username == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user = session.get(User, 1)

    if user:
        user.username = settings.FIRST_SUPERUSER
        user.password = get_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
        user.role_id = admin_role.role_id
        session.add(user)
        session.commit()

    ensure_default_sensors(session)
    sync_db_sequences(session)
