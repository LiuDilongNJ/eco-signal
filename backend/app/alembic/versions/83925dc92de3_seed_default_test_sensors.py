"""seed_default_test_sensors

Revision ID: 83925dc92de3
Revises: ec69d2cf92ad
Create Date: 2026-09-11 14:53:13.918584

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '83925dc92de3'
down_revision = 'ec69d2cf92ad'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO recorder (name, version, brand)
        SELECT 'Test Recorder', 'test', 'ecoSignal'
        WHERE NOT EXISTS (SELECT 1 FROM recorder WHERE name = 'Test Recorder');

        INSERT INTO microphone (name, microphone_element)
        SELECT 'Test Microphone', 'test'
        WHERE NOT EXISTS (SELECT 1 FROM microphone WHERE name = 'Test Microphone');

        INSERT INTO camera (name, version, brand)
        SELECT 'Test Camera', 'test', 'ecoSignal'
        WHERE NOT EXISTS (SELECT 1 FROM camera WHERE name = 'Test Camera');

        INSERT INTO lens (name, brand)
        SELECT 'Test Lens', 'ecoSignal'
        WHERE NOT EXISTS (SELECT 1 FROM lens WHERE name = 'Test Lens');

        INSERT INTO recorder_microphone (recorder_id, microphone_id)
        SELECT r.recorder_id, m.microphone_id
        FROM recorder r, microphone m
        WHERE r.name = 'Test Recorder' AND m.name = 'Test Microphone'
          AND NOT EXISTS (
              SELECT 1 FROM recorder_microphone rm
              WHERE rm.recorder_id = r.recorder_id AND rm.microphone_id = m.microphone_id
          );

        INSERT INTO camera_lens (camera_id, lens_id)
        SELECT c.camera_id, l.lens_id
        FROM camera c, lens l
        WHERE c.name = 'Test Camera' AND l.name = 'Test Lens'
          AND NOT EXISTS (
              SELECT 1 FROM camera_lens cl
              WHERE cl.camera_id = c.camera_id AND cl.lens_id = l.lens_id
          );

        INSERT INTO sensor (name, sensor_type, recorder_id, microphone_id, description, serial_number)
        SELECT 'Test Audio Sensor', 'audio', r.recorder_id, m.microphone_id,
               'Default test recorder-microphone combination for first-run uploads.', 'TEST-AUDIO-001'
        FROM recorder r, microphone m
        WHERE r.name = 'Test Recorder' AND m.name = 'Test Microphone'
          AND NOT EXISTS (
              SELECT 1 FROM sensor WHERE name = 'Test Audio Sensor' AND sensor_type = 'audio'
          );

        INSERT INTO sensor (name, sensor_type, camera_id, lens_id, description, serial_number)
        SELECT 'Test Photo Sensor', 'photo', c.camera_id, l.lens_id,
               'Default test camera-lens combination for first-run uploads.', 'TEST-PHOTO-001'
        FROM camera c, lens l
        WHERE c.name = 'Test Camera' AND l.name = 'Test Lens'
          AND NOT EXISTS (
              SELECT 1 FROM sensor WHERE name = 'Test Photo Sensor' AND sensor_type = 'photo'
          );
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM sensor
        WHERE name IN ('Test Audio Sensor', 'Test Photo Sensor');

        DELETE FROM recorder_microphone
        WHERE recorder_id IN (SELECT recorder_id FROM recorder WHERE name = 'Test Recorder')
          AND microphone_id IN (SELECT microphone_id FROM microphone WHERE name = 'Test Microphone');

        DELETE FROM camera_lens
        WHERE camera_id IN (SELECT camera_id FROM camera WHERE name = 'Test Camera')
          AND lens_id IN (SELECT lens_id FROM lens WHERE name = 'Test Lens');

        DELETE FROM recorder WHERE name = 'Test Recorder';
        DELETE FROM microphone WHERE name = 'Test Microphone';
        DELETE FROM camera WHERE name = 'Test Camera';
        DELETE FROM lens WHERE name = 'Test Lens';
        """
    )
