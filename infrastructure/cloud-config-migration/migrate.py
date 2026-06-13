import os

import psycopg2


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS edge_camera_configs (
    config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Supabase cameras.camera_id ile ayni UUID.
    camera_id UUID NOT NULL UNIQUE,
    customer_id TEXT NOT NULL,
    organization_id UUID,

    -- Kameranin hangi edge cihazinda calisacagini belirtir.
    edge_device_id TEXT NOT NULL,
    camera_name TEXT NOT NULL,
    area_name TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- RTSP adresi parola haric parcalara ayrilir.
    rtsp_scheme TEXT NOT NULL DEFAULT 'rtsp',
    rtsp_host TEXT NOT NULL,
    rtsp_port INTEGER NOT NULL DEFAULT 8554,
    rtsp_path TEXT NOT NULL,
    rtsp_username TEXT NOT NULL DEFAULT 'sentialx',
    credential_key TEXT NOT NULL DEFAULT 'mediamtx-default',
    rtsp_transport TEXT NOT NULL DEFAULT 'tcp',

    -- Edge tarafindaki frame secme davranisi.
    processing_mode TEXT NOT NULL DEFAULT 'motion',
    analysis_types TEXT[] NOT NULL DEFAULT ARRAY['ppe']::TEXT[],
    policy_map JSONB NOT NULL DEFAULT '{}'::jsonb,
    motion_threshold NUMERIC(6,5) NOT NULL DEFAULT 0.03000,
    event_window_seconds INTEGER NOT NULL DEFAULT 5,
    top_frames INTEGER NOT NULL DEFAULT 3,
    cooldown_seconds INTEGER NOT NULL DEFAULT 10,
    interval_seconds INTEGER NOT NULL DEFAULT 10,
    jpeg_quality INTEGER NOT NULL DEFAULT 88,

    -- Agent ayar yenileme ve operasyon alanlari.
    config_version BIGINT NOT NULL DEFAULT 1,
    health_status TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at TIMESTAMPTZ,
    last_error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT edge_camera_rtsp_port_check
        CHECK (rtsp_port BETWEEN 1 AND 65535),
    CONSTRAINT edge_camera_transport_check
        CHECK (rtsp_transport IN ('tcp', 'udp', 'automatic')),
    CONSTRAINT edge_camera_mode_check
        CHECK (processing_mode IN ('motion', 'interval')),
    CONSTRAINT edge_camera_analysis_check
        CHECK (
            cardinality(analysis_types) > 0
            AND analysis_types <@ ARRAY[
                'ppe',
                'fire',
                'restricted_area',
                'near_miss'
            ]::TEXT[]
        ),
    CONSTRAINT edge_camera_threshold_check
        CHECK (motion_threshold >= 0 AND motion_threshold <= 1),
    CONSTRAINT edge_camera_event_window_check
        CHECK (event_window_seconds BETWEEN 1 AND 300),
    CONSTRAINT edge_camera_top_frames_check
        CHECK (top_frames BETWEEN 1 AND 20),
    CONSTRAINT edge_camera_cooldown_check
        CHECK (cooldown_seconds BETWEEN 0 AND 3600),
    CONSTRAINT edge_camera_interval_check
        CHECK (interval_seconds BETWEEN 1 AND 86400),
    CONSTRAINT edge_camera_jpeg_quality_check
        CHECK (jpeg_quality BETWEEN 40 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_edge_camera_configs_device_active
ON edge_camera_configs (edge_device_id, is_active);

CREATE INDEX IF NOT EXISTS idx_edge_camera_configs_customer
ON edge_camera_configs (customer_id);

CREATE INDEX IF NOT EXISTS idx_edge_camera_configs_analysis
ON edge_camera_configs USING GIN (analysis_types);

CREATE OR REPLACE FUNCTION update_edge_camera_config_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    IF ROW(
        NEW.camera_id,
        NEW.customer_id,
        NEW.organization_id,
        NEW.edge_device_id,
        NEW.camera_name,
        NEW.area_name,
        NEW.is_active,
        NEW.rtsp_scheme,
        NEW.rtsp_host,
        NEW.rtsp_port,
        NEW.rtsp_path,
        NEW.rtsp_username,
        NEW.credential_key,
        NEW.rtsp_transport,
        NEW.processing_mode,
        NEW.analysis_types,
        NEW.policy_map,
        NEW.motion_threshold,
        NEW.event_window_seconds,
        NEW.top_frames,
        NEW.cooldown_seconds,
        NEW.interval_seconds,
        NEW.jpeg_quality,
        NEW.metadata
    ) IS DISTINCT FROM ROW(
        OLD.camera_id,
        OLD.customer_id,
        OLD.organization_id,
        OLD.edge_device_id,
        OLD.camera_name,
        OLD.area_name,
        OLD.is_active,
        OLD.rtsp_scheme,
        OLD.rtsp_host,
        OLD.rtsp_port,
        OLD.rtsp_path,
        OLD.rtsp_username,
        OLD.credential_key,
        OLD.rtsp_transport,
        OLD.processing_mode,
        OLD.analysis_types,
        OLD.policy_map,
        OLD.motion_threshold,
        OLD.event_window_seconds,
        OLD.top_frames,
        OLD.cooldown_seconds,
        OLD.interval_seconds,
        OLD.jpeg_quality,
        OLD.metadata
    ) THEN
        NEW.config_version = OLD.config_version + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_edge_camera_config_timestamp
ON edge_camera_configs;

CREATE TRIGGER trg_edge_camera_config_timestamp
BEFORE UPDATE ON edge_camera_configs
FOR EACH ROW
EXECUTE FUNCTION update_edge_camera_config_timestamp();

INSERT INTO edge_camera_configs (
    camera_id,
    customer_id,
    organization_id,
    edge_device_id,
    camera_name,
    area_name,
    rtsp_host,
    rtsp_path,
    processing_mode,
    analysis_types,
    policy_map,
    motion_threshold,
    event_window_seconds,
    top_frames,
    cooldown_seconds,
    interval_seconds,
    metadata
)
VALUES
(
    '11111111-1111-4111-8111-111111111111',
    'demo-customer',
    NULL,
    'edge-demo-01',
    'PPE Test Camera',
    'production',
    '127.0.0.1',
    'kamera1',
    'motion',
    ARRAY['ppe']::TEXT[],
    '{"ppe": 1}'::jsonb,
    0.03000,
    5,
    3,
    10,
    10,
    '{"source": "local-test-video"}'::jsonb
),
(
    '22222222-2222-4222-8222-222222222222',
    'demo-customer',
    NULL,
    'edge-demo-01',
    'Fire Test Camera',
    'warehouse',
    '127.0.0.1',
    'kamera2',
    'motion',
    ARRAY['fire']::TEXT[],
    '{"fire": 3}'::jsonb,
    0.03000,
    5,
    3,
    10,
    10,
    '{"source": "local-test-video"}'::jsonb
),
(
    '33333333-3333-4333-8333-333333333333',
    'demo-customer',
    NULL,
    'edge-demo-01',
    'Combined Test Camera',
    'live-test',
    '127.0.0.1',
    'kamera3',
    'interval',
    ARRAY['ppe', 'fire']::TEXT[],
    '{"ppe": 1, "fire": 3}'::jsonb,
    0.03000,
    5,
    3,
    10,
    10,
    '{"source": "local-webcam"}'::jsonb
)
ON CONFLICT (camera_id) DO UPDATE SET
    customer_id = EXCLUDED.customer_id,
    organization_id = EXCLUDED.organization_id,
    edge_device_id = EXCLUDED.edge_device_id,
    camera_name = EXCLUDED.camera_name,
    area_name = EXCLUDED.area_name,
    is_active = EXCLUDED.is_active,
    rtsp_host = EXCLUDED.rtsp_host,
    rtsp_path = EXCLUDED.rtsp_path,
    processing_mode = EXCLUDED.processing_mode,
    analysis_types = EXCLUDED.analysis_types,
    policy_map = EXCLUDED.policy_map,
    motion_threshold = EXCLUDED.motion_threshold,
    event_window_seconds = EXCLUDED.event_window_seconds,
    top_frames = EXCLUDED.top_frames,
    cooldown_seconds = EXCLUDED.cooldown_seconds,
    interval_seconds = EXCLUDED.interval_seconds,
    metadata = EXCLUDED.metadata;
"""


def main() -> None:
    db_url = os.environ["DB_URL"]
    with psycopg2.connect(db_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION_SQL)
            cursor.execute(
                """
                SELECT camera_id, camera_name, rtsp_path, processing_mode,
                       analysis_types, config_version
                FROM edge_camera_configs
                ORDER BY rtsp_path
                """
            )
            rows = cursor.fetchall()
    print(f"edge_camera_configs ready: {len(rows)} rows")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
