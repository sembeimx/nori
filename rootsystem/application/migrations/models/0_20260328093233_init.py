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
) /* Tracks who did what and when. */;
CREATE TABLE IF NOT EXISTS "jobs" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "queue" VARCHAR(50) NOT NULL DEFAULT 'default',
    "payload" JSON NOT NULL,
    "attempts" INT NOT NULL DEFAULT 0,
    "reserved_at" TIMESTAMP,
    "available_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_jobs_queue_73917e" ON "jobs" ("queue");
CREATE TABLE IF NOT EXISTS "permissions" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(100) NOT NULL UNIQUE,
    "description" VARCHAR(255) NOT NULL DEFAULT ''
) /* A granular permission (e.g. 'articles.edit'). */;
CREATE TABLE IF NOT EXISTS "roles" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(50) NOT NULL UNIQUE
) /* A role that groups permissions. */;
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS "role_permission" (
    "roles_id" INT NOT NULL REFERENCES "roles" ("id") ON DELETE CASCADE,
    "permission_id" INT NOT NULL REFERENCES "permissions" ("id") ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "uidx_role_permis_roles_i_3e510e" ON "role_permission" ("roles_id", "permission_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "eJztWllv2zgQ/iuCX5oCWcOV7TjdN+Vo66JJisTdXbQoBFqiJW4kUiWppEbh/16S1n04lu"
    "M4SuGXRJqD5nwczkHqV8cnNvRY1whtxD8Rp/O39quDgQ/FQ4l3qHVAEKQcSeBg6ilhIKVM"
    "jziKDKaMU2BxwZkBj0FBsiGzKAo4IljKTwT7lmn3LtFsZIv/gGsAyweIu3IIm1hiDISdta"
    "RDjH6E0OTEgdyFVOh8+y7ICNvwJ2Txa3BrzhD07JyZyJYDKLrJ54GijTF/pwTlRKamRbzQ"
    "x6lwMOcuwYk0wlxSHYghBRzK4TkNpdE49LwIoRiH5UxTkeUUMzo2nIHQk9BJ7RJyMTEDT0"
    "SyCJaoi9kwZaAjf+Uv/c1gNDjuHw2OhYiaSUIZLZbmpbYvFRUCl5POQvEBB0sJBWOKW8gg"
    "NRuBl9F4GMEYrwyEEUAJgrFICmHqbG3CMMVMbAk5gxJkpy6g1ZilGgXIxDTXgKzkdTvAzA"
    "c/TQ9ih7viddhbAdA/xvXpB+P6YNh7LW0hYpcvo8llxNEVK4+hCj6memuAY15rIyyfwf1y"
    "UL7prYOlkKoFU/HyaFJoEWpX7uN6MHNKeyxjLC0XYAeyMpIfb64uq5HMqBRw/IKFgd9sZP"
    "FDzUOMf28lqitAlEbLOfuM/fCy2B1cGP8VYT39dHWiQCCMO1SNogY4KUCMAhPYthCoQLne"
    "X/NaL9JhB8M1/HUwrHVXySrufGEJ4423flbrRULZP1oDyv5RLZSSVdj4FEpzTcDLUJ4JDk"
    "c+rNn/Oc0CnHak2o0fWprwhQ32Ffbm0dquQHcyvji/mRgXn3OB4cyYnEuOrqjzAvWguBLJ"
    "INq/48kHTb5qX68uz4vxI5GbfO3IOYGQExOTexkLUjeMqTEwC9kozG4zJa8kTEX/cQ9Ezi"
    "txiE7qZMssX/eLFICBo5ZFgiunGbVdH8m0U9GNSfLhqkbsfzJdrwWrX98tN1MnyPmD+qm3"
    "ut7vj/Re/+h4OBiNhse9pCkos1Z1Byfj97JByLn2w12XsDVsVPgmCk/VP5RgTh7b20MEYO"
    "4RUOGr9ZVaRmULldozhOldl2qAc+gHvKJQq40GWZWNTgg2grX36JiwtfMBASekdxtVEgXV"
    "LZQSreom2lQ5xGaXSoec+98BpJDcYC2Luvu6sAV14b7g/0MXtiUF/2dIfcTYci1KdX+Gu7"
    "L8DxK5NS9iDM2hQEwFUC3V1Q5g1+lqrwDlSCwC60Ib8VevyxczjbX3FzU7v6hpelT+qEPy"
    "3aP39Oe62Zk1wLGgtrv7m87WOi99uM6xo5CqhVPxFjuMsZlimnhVh/EXAM8nRP5VyzYW5g"
    "NsVXl8FHqvxTht9PxF7HAxNf2JzG1X2Q4KPVWCJM1wPmXMCFVA38J5gmJ03JssQsRLNSMB"
    "7lISOm6sZwa5rCXExEQgX+4b4+bUOFM53CwG5MXKRKnsqEiRsX31yTHxiHXSohTWuPzSwB"
    "FGBSyT4FhVInxQfp/69qnvCVPfdk7JniNQFwPQ48J1vlJu25o1Ddp5a4qhO01x+aBdCszF"
    "yJ2N6lsI2mkjVRu1DUiR5VbF7YizMnKDVKY19xr7APxwAL6DlDUsmzMqL/OTp60VzbnjRL"
    "E1GoAYib9MAJ/m4xyCOcQV53UrPs5JVfZXPnVXPs96erb4DUF1VWQ="
)
