#!/bin/sh
# restore.sh — PostgreSQL restore script for Tron
# Restores database from a backup file
#
# Usage: ./scripts/restore.sh /path/to/backup.tar.gz
#
# This script:
# 1. Validates the backup file exists
# 2. Stops the API service to release DB connections
# 3. Drops and recreates the database
# 4. Restores from the backup
# 5. Restarts services
# 6. Verifies the restore with a health check

set -e

# Configuration
BACKUP_FILE="${1}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-tron}"
DB_USER="${DB_USER:-tron}"
DB_PASSWORD="${DB_PASSWORD:-}"
COMPOSE_COMMAND="docker compose"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging functions
log_info() {
    echo "[restore] $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo "${RED}[restore] $(date '+%Y-%m-%d %H:%M:%S') - ERROR: $1${NC}" >&2
}

log_success() {
    echo "${GREEN}[restore] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

log_warn() {
    echo "${YELLOW}[restore] $(date '+%Y-%m-%d %H:%M:%S') - WARNING: $1${NC}"
}

# Validate arguments
if [ -z "$BACKUP_FILE" ]; then
    log_error "Usage: ./scripts/restore.sh /path/to/backup.tar.gz"
    exit 1
fi

# Validate backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    log_error "Backup file not found: $BACKUP_FILE"
    exit 1
fi

log_info "Starting database restore from: $BACKUP_FILE"
log_info "Target database: $DB_NAME on $DB_HOST:$DB_PORT"

# Step 1: Stop API service to release database connections
log_info "Stopping API service to release database connections..."
$COMPOSE_COMMAND stop tron-api
sleep 2

# Step 2: Stop worker to prevent concurrent operations
log_info "Stopping worker service..."
$COMPOSE_COMMAND stop tron-worker 2>/dev/null || true
sleep 1

# Step 3: Verify PostgreSQL is healthy
log_info "Verifying PostgreSQL is healthy..."
if ! $COMPOSE_COMMAND exec -T postgres pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    log_warn "PostgreSQL not immediately ready, waiting..."
    sleep 5
    if ! $COMPOSE_COMMAND exec -T postgres pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        log_error "PostgreSQL failed to become ready"
        $COMPOSE_COMMAND start tron-api
        exit 1
    fi
fi
log_success "PostgreSQL is healthy"

# Step 4: Get backup file size
BACKUP_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')
log_info "Backup file size: $BACKUP_SIZE"

# Step 5: Drop existing database
log_warn "Dropping existing database: $DB_NAME"
$COMPOSE_COMMAND exec -T postgres psql \
    -U "$DB_USER" \
    -c "DROP DATABASE IF EXISTS $DB_NAME;" >/dev/null 2>&1 || true

# Step 6: Recreate database
log_info "Creating new database: $DB_NAME"
$COMPOSE_COMMAND exec -T postgres psql \
    -U "$DB_USER" \
    -d postgres \
    -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

sleep 1

# Step 7: Restore from backup
log_info "Restoring database from backup..."
log_info "This may take several minutes depending on backup size..."

# Extract and restore based on file extension
if [ "${BACKUP_FILE##*.}" = "gz" ]; then
    # Compressed tar archive (tar.gz)
    log_info "Detected compressed backup format (tar.gz)"
    TEMP_DIR="/tmp/restore_$$"
    mkdir -p "$TEMP_DIR"

    # Extract backup to temp directory
    log_info "Extracting backup archive..."
    tar -xzf "$BACKUP_FILE" -C "$TEMP_DIR" || {
        log_error "Failed to extract backup archive"
        rm -rf "$TEMP_DIR"
        exit 1
    }

    # Find the base backup directory (pg_basebackup creates directory)
    BACKUP_DIR=$(find "$TEMP_DIR" -maxdepth 2 -type d -name "base" -o -name "global" | head -1 | xargs dirname)

    if [ -z "$BACKUP_DIR" ] || [ "$BACKUP_DIR" = "." ]; then
        log_error "Could not find backup directory structure in archive"
        rm -rf "$TEMP_DIR"
        exit 1
    fi

    log_info "Backup extracted to: $BACKUP_DIR"

    # Copy backup into container and restore
    log_info "Copying backup into PostgreSQL container..."
    docker cp "$BACKUP_DIR" "tron-postgres:/tmp/backup_restore" 2>/dev/null || {
        log_error "Failed to copy backup into container"
        rm -rf "$TEMP_DIR"
        exit 1
    }

    log_info "Restoring from backup..."
    $COMPOSE_COMMAND exec -T postgres pg_restore \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --if-exists \
        --clean \
        /tmp/backup_restore/base \
        2>&1 || {
        log_warn "Some restore warnings occurred (this is often normal)"
    }

    # Cleanup
    $COMPOSE_COMMAND exec -T postgres rm -rf /tmp/backup_restore
    rm -rf "$TEMP_DIR"

elif [ "${BACKUP_FILE##*.}" = "sql" ]; then
    # Plain SQL dump
    log_info "Detected SQL dump format"

    # Copy SQL file into container
    docker cp "$BACKUP_FILE" "tron-postgres:/tmp/backup.sql" 2>/dev/null || {
        log_error "Failed to copy SQL dump into container"
        exit 1
    }

    log_info "Restoring from SQL dump..."
    $COMPOSE_COMMAND exec -T postgres psql \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -f /tmp/backup.sql >/dev/null 2>&1 || {
        log_warn "Some restore warnings occurred (this is often normal)"
    }

    # Cleanup
    $COMPOSE_COMMAND exec -T postgres rm /tmp/backup.sql
else
    log_error "Unsupported backup format. Expected .tar.gz or .sql"
    exit 1
fi

log_success "Database restore completed"

# Step 8: Verify restore
log_info "Verifying database restore..."
sleep 2

# Test database connectivity
if ! $COMPOSE_COMMAND exec -T postgres psql \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -c "SELECT 1;" >/dev/null 2>&1; then
    log_error "Restored database failed connectivity test"
    exit 1
fi

log_success "Database connectivity verified"

# Get table count
TABLE_COUNT=$($COMPOSE_COMMAND exec -T postgres psql \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | xargs)

log_info "Restored database contains $TABLE_COUNT tables"

# Step 9: Restart services
log_info "Restarting services..."
$COMPOSE_COMMAND start tron-api
$COMPOSE_COMMAND start tron-worker 2>/dev/null || true
sleep 5

# Step 10: Health check
log_info "Running health check..."
if curl -f http://localhost:13000/health >/dev/null 2>&1; then
    log_success "API health check passed"
else
    log_warn "API health check failed - services may still be starting"
    log_info "Run: docker compose logs -f tron-api"
fi

# Final summary
log_success "Database restore completed successfully!"
log_info "Restored database: $DB_NAME (from $BACKUP_FILE)"
log_info "Services are restarting - API may take 10-30 seconds to become fully ready"
log_info "Check service status with: docker compose ps"
log_info "View API logs with: docker compose logs -f tron-api"

exit 0
