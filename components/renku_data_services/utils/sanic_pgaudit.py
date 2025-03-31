"""Postgres Audit log functionality.

This mostly just overrides the flask functionality already in pg audit so it works with sanic.
"""

from contextlib import contextmanager
from copy import copy
from typing import Any, Iterator, reveal_type

import sqlalchemy as sa
from postgresql_audit.base import ImproperlyConfigured
from postgresql_audit.base import VersioningManager as BaseVersioningManager
from sanic import Request, Sanic
from sqlalchemy import FromClause, orm
from sqlalchemy.dialects.postgresql import array

from renku_data_services.users.orm import UserORM


def assign_actor(base, cls):
    """Postgresql_audit by default links on primary key, we customize this because we link on keycloak_id."""
    if hasattr(cls, "actor_id"):
        return

    cls.actor_id = sa.Column("actor_id", sa.Text())
    cls.actor = orm.relationship(UserORM, primaryjoin=cls.actor_id == UserORM.keycloak_id, foreign_keys=[cls.actor_id])


class SanicVersioningManager(BaseVersioningManager):
    """Custom version manager that integrates with Sanic to get user id."""

    _actor_cls = "UserORM"

    def get_transaction_values(self):
        """Gets values from Sanic for a pgsql_audit transaction."""
        values = copy(self.values)
        ctx = Sanic.get_app().ctx
        if ctx and hasattr(ctx, "activity_values"):
            values.update(ctx.activity_values)
        if "actor_id" not in values and self.default_actor_id is not None:
            values["actor_id"] = self.default_actor_id
        return values

    @property
    def default_actor_id(self):
        """Get user id from sanic."""
        request = Request.get_current()

        try:
            return request.ctx.keycloak_user_id
        except AttributeError:
            return

    def configure_versioned_classes(self):
        """Configures all versioned classes that were collected during instrumentation process.

        Note: we override this so we can use our own `assign_actor` method.
        """
        for cls in self.pending_classes:
            self.audit_table(cls.__table__, cls.__versioned__.get("exclude"))
        assign_actor(self.base, self.transaction_cls)

    def build_audit_table_query(self, table: sa.Table, exclude_columns: list[str] | None = None) -> sa.Select:
        """Builds a query that, when executed, turns on audit tracking for a table.

        Note: this is just a copy of the pgsql_audit function, but with support for tables in other schemas.
        """
        args: list[Any] = [f"{table.schema}.{table.name}"]
        if exclude_columns:
            for column in exclude_columns:
                if column not in table.c:
                    raise ImproperlyConfigured(
                        f"Could not configure versioning. Table '{table.name}'' does "
                        f"not have a column named '{column}'."
                    )
            args.append(array(exclude_columns))

        if self.schema_name is None:
            func = sa.func.audit_table
        else:
            func = getattr(getattr(sa.func, self.schema_name), "audit_table")
        return sa.select(func(*args))


def merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merges two dictionaries.

    This is from the pg audit flask implementation, but can't be imported without also importing flask.
    """
    c = copy(a)
    c.update(b)
    return c


@contextmanager
def activity_values(**values: dict[str, Any]) -> Iterator[None]:
    """Context manager that allows tracking child changes on the parent.

    Example:
        with activity_values(target_id=str(article.id)):
            article.tags = [Tag(name='Some tag')]
            db.session.commit()
    """
    ctx = Sanic.get_app().ctx
    if not ctx:
        yield  # Needed for contextmanager
        return
    if hasattr(ctx, "activity_values"):
        previous_value = ctx.activity_values
        values = merge_dicts(previous_value, values)
    else:
        previous_value = None
    ctx.activity_values = values
    yield
    if previous_value is None:
        del ctx.activity_values
    else:
        ctx.activity_values = previous_value


versioning_manager = SanicVersioningManager(schema_name="common")
