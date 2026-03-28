from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "audit_logs" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "user_id" INT,
    "action" VARCHAR(50) NOT NULL,
    "model_name" VARCHAR(100),
    "record_id" VARCHAR(100),
    "changes" JSON,
    "ip_address" VARCHAR(45),
    "request_id" VARCHAR(36),
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS "jobs" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "queue" VARCHAR(50) NOT NULL DEFAULT 'default',
    "payload" JSON NOT NULL,
    "attempts" INT NOT NULL DEFAULT 0,
    "reserved_at" TIMESTAMP,
    "available_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "failed_at" TIMESTAMP,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_jobs_queue_73917e" ON "jobs" ("queue");
CREATE TABLE IF NOT EXISTS "permissions" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(100) NOT NULL UNIQUE,
    "description" VARCHAR(255) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS "roles" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(50) NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS "role_permission" (
    "roles_id" INT NOT NULL REFERENCES "roles" ("id") ON DELETE CASCADE,
    "permission_id" INT NOT NULL REFERENCES "permissions" ("id") ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "uidx_role_permis_roles_i_3e510e" ON "role_permission" ("roles_id", "permission_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "role_permission";
        DROP TABLE IF EXISTS "roles";
        DROP TABLE IF EXISTS "permissions";
        DROP TABLE IF EXISTS "jobs";
        DROP TABLE IF EXISTS "audit_logs";"""
