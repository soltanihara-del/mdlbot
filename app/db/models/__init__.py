"""Import every ORM model so Alembic receives complete metadata."""

from app.db.models.admin import *  # noqa: F403
from app.db.models.files import *  # noqa: F403
from app.db.models.identity import *  # noqa: F403
from app.db.models.jobs import *  # noqa: F403
from app.db.models.operations import *  # noqa: F403
from app.db.models.product import *  # noqa: F403

