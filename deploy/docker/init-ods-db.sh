#!/bin/bash
set -e

# HoneyBadge ODS Database Initialization
# Creates the honeybadge_ods database and loads the ODS schema.
# Runs after 01-init.sql (which creates the audit schema in honeybadge_audit).
#
# PostgreSQL docker-entrypoint runs scripts in alphabetical order against
# POSTGRES_DB (honeybadge_audit). To create a *separate* database we must
# use psql explicitly — CREATE DATABASE cannot run inside a transaction block.

echo "[init-ods-db] Creating database honeybadge_ods ..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
    CREATE DATABASE honeybadge_ods;
    GRANT ALL PRIVILEGES ON DATABASE honeybadge_ods TO honeybadge;
EOSQL

echo "[init-ods-db] Loading ODS schema into honeybadge_ods ..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname honeybadge_ods \
    -f /docker-entrypoint-initdb.d/ods_schema.sql

echo "[init-ods-db] Done."
