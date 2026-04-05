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


MODELS_STATE = (
    "eJztmllv2zgQgP+K4JemQNZwfcTZfXOO3bpokiLxHmhRCLRFy1xLpEpSTY3C/71D2rooyV"
    "ccRy38kkhzKJyP5AxHyvfamCMfPzI+rfdCh8j3zK39YX2vUZDCRZH61KqhIMgolUyioadd"
    "kDK0PeYKbToUkqORBM0YeQKDyMFixEkgCaPKfgDqqbAeJ8xyiAO/kbQQVReY1tUjHDaCZx"
    "DqbmQdUvIlxLZkLpYTzMHn02cQE+rgb1hEt8HUHhPsOZlgiaMeoOW2nAVa1qfyT22oBjK0"
    "R8wLfZoYBzM5YTS2JlQqqYsp5khi9XjJQxU0DT1vSSjisBhpYrIYYsrHwWMUegqd8s6Ri4"
    "QpPEvRiFFFHUYjdICu+iu/Nd+0u+3z1ln7HEz0SGJJd74IL4l94agJ3A5qc61HEi0sNMaE"
    "Wygwt7eCl/JYTzDilUK4BBQTjEwShMliqxLDhBlsCTWCHLLLCeLFzBIPAxkMcwNkuVV3AG"
    "Y++mZ7mLpyAredxgpA//TuL9/27k86jdcqFga7fJFNbpeaplZlGfrMwZ6t77bgmPXaieUL"
    "LL8MyjeNTViCVSlMrcvS5HjEuFO4j8thZpyOLCOWowmiLhZ5ku8e7m6LSaZcDI5/Uwjwk0"
    "NG8tTyiJCfK0l1BUQVtBqzL8QXL83u5Kb3n4n18v3dhYbAhHS5fop+wIWBmAQ2chwwKKBc"
    "vl6zXj/lgm13Nliv7U7pclUqc+dDJEJuvfXTXj8lytbZBihbZ6UolcrY+ByrcG0k8yivQC"
    "OJj0v2f8bTwOksXevRRUULPsTg3FFvtpzbFXQH/Zvrh0Hv5kMmMVz1BtdK09TSmSE9MWci"
    "foj1b3/w1lK31se722szf8R2g481NSYUSmZT9qhyQbIMI2kEZq4ahfE0deRVgiH0H48Ial"
    "5Ow5qszDav8pu+KUEUuXpaFFw1zKT5eseGteK2TGlO13Rk/7Phhr3YB8wFVBhMpQVrJsQW"
    "uFpwx2f5TmyN7Z77sAvi/kKt2O/NZqvVbTZaZ+eddrfbOW/E/URetaqxuOj/pXqLzK5Y37"
    "Dp+dom18cOz9V65DDHl9VtPwI08xgqWKvlh7yUyx4OeS+Q4Q99ykNSYj+QBWe80myQdtnp"
    "5cJOWBtPzgl7e7UAODH/utMhxHDdwymkUo1IlQ4dUdi5U0dm+X9FRJPcYS5N3+ORsgJHyv"
    "TkjmF+dtqlGcfjHn3hPXps+X6h/Vmdlg/aK58IsZiOos4vZXC6pgEMYtMN+8Ce5XIEY0Lc"
    "SnytE1x369YrxCWB2RB17BD56nW+M9za+/jN7uDf7Lb9avKk7yWHp/f8r/jTI9uCo+F2uE"
    "95tb110s3OJm+gwaoUp9bND5hsU80R84q+y9wgOhsw9VNPWx/CR3RUtOKTBHwPj6ri4p9H"
    "ay6SJn8i9e2zMBSOPX0iiV9xZAvHmHGNe4pnMcvl+/94Kpa6xHNpICeche4k8rODTPkCMx"
    "gZlovd03u47F3pkm6baXm+rm7qUIorZhTlyloZL5BNqqQytqT6HxQXogtEqt6Jorq41v5Y"
    "CY+V8Bkr4X5egr5E3jYz0ZOzd/b4XLVp2yGHZwMyM3lS97I5PJenzUSeTvJ7yOFJm2Uk8f"
    "kP/aEGIg=="
)
