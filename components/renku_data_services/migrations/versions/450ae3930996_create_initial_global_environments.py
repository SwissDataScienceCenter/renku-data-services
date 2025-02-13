"""bootstrap initial global environments

Mainly used for CI deployments so they have a envs for testing.

Revision ID: 450ae3930996
Revises: d71f0f795d30
Create Date: 2025-02-07 02:34:53.408066

"""

import logging
from dataclasses import dataclass

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from renku_data_services.base_models.core import InternalServiceAdmin

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")
# revision identifiers, used by Alembic.
revision = "450ae3930996"
down_revision = "d71f0f795d30"
branch_labels = None
depends_on = None


@dataclass
class Environment:
    name: str
    container_image: str
    default_url: str
    port: int = 8888
    description: str = ""
    working_directory: str | None = None
    mount_directory: str | None = None
    uid: int = 1000
    gid: int = 1000
    args: list[str] | None = None
    command: list[str] | None = None


GLOBAL_ENVIRONMENTS = [
    Environment(
        name="Python/Jupyter",
        description="Standard python environment",
        container_image="renku/renkulab-py:latest",
        default_url="/lab",
        working_directory="/home/jovyan/work",
        mount_directory="/home/jovyan/work",
        port=8888,
        uid=1000,
        gid=100,
        command=["sh", "-c"],
        args=[
            '/entrypoint.sh jupyter server --ServerApp.ip=0.0.0.0 --ServerApp.port=8888 --ServerApp.base_url=$RENKU_BASE_URL_PATH --ServerApp.token="" --ServerApp.password="" --ServerApp.allow_remote_access=true --ContentsManager.allow_hidden=true --ServerApp.allow_origin=* --ServerApp.root_dir="/home/jovyan/work"'
        ],
    ),
    Environment(
        name="Rstudio",
        description="Standard R environment",
        container_image="renku/renkulab-r:latest",
        default_url="/rstudio",
        working_directory="/home/jovyan/work",
        mount_directory="/home/jovyan/work",
        port=8888,
        uid=1000,
        gid=100,
        command=["sh", "-c"],
        args=[
            '/entrypoint.sh jupyter server --ServerApp.ip=0.0.0.0 --ServerApp.port=8888 --ServerApp.base_url=$RENKU_BASE_URL_PATH --ServerApp.token="" --ServerApp.password="" --ServerApp.allow_remote_access=true --ContentsManager.allow_hidden=true --ServerApp.allow_origin=* --ServerApp.root_dir="/home/jovyan/work"'
        ],
    ),
]


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    try:
        connection = op.get_bind()

        logging.info("creating global environments")
        env_stmt = sa.select(sa.column("id", type_=sa.String)).select_from(sa.table("environments", schema="sessions"))
        existing_envs = connection.execute(env_stmt).all()
        if existing_envs:
            logging.info("skipping environment creation as there already are existing environments")
            return
        for env in GLOBAL_ENVIRONMENTS:
            op.execute(
                sa.text(
                    """INSERT INTO sessions.environments(
                        id, 
                        name, description,
                        created_by_id, 
                        creation_date, 
                        container_image, 
                        default_url, 
                        port,
                        working_directory,
                        mount_directory,
                        uid,
                        gid,
                        args,
                        command,
                        environment_kind 
                    )VALUES (
                        generate_ulid(), 
                        :name, 
                        :description, 
                        :created_by_id, 
                        now(), 
                        :container_image, 
                        :default_url,
                        :port,
                        :working_directory,
                        :mount_directory,
                        :uid,
                        :gid,
                        :args,
                        :command,
                        'GLOBAL'
                    )"""  # nosec: B608
                ).bindparams(
                    sa.bindparam("name", value=env.name, type_=sa.Text),
                    sa.bindparam("description", value=env.description, type_=sa.Text),
                    sa.bindparam("created_by_id", value=InternalServiceAdmin.id, type_=sa.Text),
                    sa.bindparam("container_image", value=env.container_image, type_=sa.Text),
                    sa.bindparam("default_url", value=env.default_url, type_=sa.Text),
                    sa.bindparam("port", value=env.port, type_=sa.Integer),
                    sa.bindparam("working_directory", value=env.working_directory, type_=sa.Text),
                    sa.bindparam("mount_directory", value=env.mount_directory, type_=sa.Text),
                    sa.bindparam("uid", value=env.uid, type_=sa.Integer),
                    sa.bindparam("gid", value=env.gid, type_=sa.Integer),
                    sa.bindparam("args", value=env.args, type_=JSONVariant),
                    sa.bindparam("command", value=env.command, type_=JSONVariant),
                )
            )
            logging.info(f"created global environment {env.name}")

    except Exception:
        logging.exception("creation of intial global environments failed")

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
