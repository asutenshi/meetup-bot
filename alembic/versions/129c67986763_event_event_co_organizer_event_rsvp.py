"""event, event_co_organizer, event_rsvp

Revision ID: 129c67986763
Revises: b2f1c9a4e7d3
Create Date: 2026-08-27 04:42:34.822517

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '129c67986763'
down_revision: str | Sequence[str] | None = 'b2f1c9a4e7d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('location', sa.String(), nullable=False),
        sa.Column('budget_per_person', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('seats_limit', sa.Integer(), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'planned', 'cancelled', 'completed',
                name='eventstatus', native_enum=False, create_constraint=True,
            ),
            server_default='planned',
            nullable=False,
        ),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('announcement_message_id', sa.BigInteger(), nullable=True),
        sa.Column('attendance_finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_event_created_by_user')),
        sa.ForeignKeyConstraint(
            ['project_id'], ['project.id'], name=op.f('fk_event_project_id_project')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_event')),
    )
    op.create_table(
        'event_co_organizer',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column(
            'added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['event_id'], ['event.id'], name=op.f('fk_event_co_organizer_event_id_event')
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['user.id'], name=op.f('fk_event_co_organizer_user_id_user')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_event_co_organizer')),
        sa.UniqueConstraint(
            'event_id', 'user_id', name=op.f('uq_event_co_organizer_event_id')
        ),
    )
    op.create_table(
        'event_rsvp',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'going', 'not_going',
                name='rsvpstatus', native_enum=False, create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            'responded_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['event_id'], ['event.id'], name=op.f('fk_event_rsvp_event_id_event')
        ),
        sa.ForeignKeyConstraint(
            ['updated_by'], ['user.id'], name=op.f('fk_event_rsvp_updated_by_user')
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['user.id'], name=op.f('fk_event_rsvp_user_id_user')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_event_rsvp')),
        sa.UniqueConstraint('event_id', 'user_id', name=op.f('uq_event_rsvp_event_id')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('event_rsvp')
    op.drop_table('event_co_organizer')
    op.drop_table('event')
