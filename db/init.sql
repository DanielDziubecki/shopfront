-- One PostgreSQL instance, one database per service that owns data.
-- Services create their own tables on startup.
CREATE DATABASE catalog;
CREATE DATABASE shipping;
CREATE DATABASE orders;

-- Read-only user for the OpenTelemetry Collector's PostgreSQL receiver.
CREATE USER monitoring WITH PASSWORD 'monitoring';
GRANT pg_monitor TO monitoring;
