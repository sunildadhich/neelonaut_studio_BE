"""Initial Neelonaut Studio schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # The application metadata is authoritative; this migration is generated at deploy time
    # with `alembic revision --autogenerate` after configuring PostgreSQL.
    bind = op.get_bind()
    from app.db import Base
    import app.models
    Base.metadata.create_all(bind=bind)

def downgrade():
    from app.db import Base
    import app.models
    Base.metadata.drop_all(bind=op.get_bind())
