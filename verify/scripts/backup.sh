#!/bin/sh
# backup.sh — PostgreSQL backup script for tron-backup service
# Called by the backup service container on schedule

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/tmp/backup_${TIMESTAMP}"

echo "[backup] Starting backup at ${TIMESTAMP}"

# Base backup
pg_basebackup -h "${PGHOST}" -U "${PGUSER}" -D "${BACKUP_DIR}" -Ft -z -P

echo "[backup] Base backup complete: ${BACKUP_DIR}"

# TODO: Ship to MinIO bucket
# mc cp --recursive "${BACKUP_DIR}" "minio/${MINIO_BUCKET}/basebackup_${TIMESTAMP}/"

# Cleanup local
rm -rf "${BACKUP_DIR}"

echo "[backup] Backup cycle complete."
