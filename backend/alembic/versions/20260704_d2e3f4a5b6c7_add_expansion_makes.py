"""Add expansion_makes table, replacing hardcoded TARGET_MAKES dict

Revision ID: d2e3f4a5b6c7
Revises: 3c4d5e6f7a8b
Create Date: 2026-07-04

"""
from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = '3c4d5e6f7a8b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'expansion_makes',
        sa.Column('id',            sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column('make',          sa.String(100),  nullable=False),
        sa.Column('year_tier',     sa.String(20),   nullable=False, server_default='default'),
        sa.Column('nhtsa_slug',    sa.String(100),  nullable=True),
        sa.Column('cq_slug',       sa.String(100),  nullable=True),
        sa.Column('carsdata_slug', sa.String(100),  nullable=True),
        sa.Column('carinfo_slug',  sa.String(100),  nullable=True),
        sa.Column('enabled',       sa.Boolean(),    nullable=False, server_default=sa.true()),
        sa.Column('created_at',    sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('make', name='uq_expansion_makes_make'),
    )
    op.create_index('ix_expansion_makes_enabled', 'expansion_makes', ['enabled'])

    # Seed from the current TARGET_MAKES dict in pipelines/vehicle_coverage_expansion.py.
    # NOTE: HINO was defined twice in that dict (identical values) — deduped to one row here.
    # year_tier assigned by segment: Chinese-origin makes -> 'chinese', other commercial/truck
    # makes -> 'commercial', everything else -> 'default'.
    op.execute("""
        INSERT INTO expansion_makes (make, year_tier, nhtsa_slug, cq_slug, carsdata_slug, carinfo_slug, enabled) VALUES
        ('TOYOTA','default','Toyota','toyota','toyota','toyota',true),
        ('NISSAN','default','Nissan','nissan','nissan','nissan',true),
        ('HONDA','default','Honda','honda','honda','honda',true),
        ('MAZDA','default','Mazda','mazda','mazda','mazda',true),
        ('MITSUBISHI','default','Mitsubishi','mitsubishi','mitsubishi','mitsubishi',true),
        ('SUBARU','default','Subaru','subaru','subaru','subaru',true),
        ('DAIHATSU','default','Daihatsu','daihatsu','daihatsu','daihatsu',true),
        ('ISUZU','default','Isuzu','isuzu','isuzu','isuzu',true),
        ('SUZUKI','default','Suzuki','suzuki','suzuki','suzuki',true),
        ('LEXUS','default','Lexus','lexus','lexus','lexus',true),
        ('HINO','commercial','Hino',NULL,'hino','hino',true),
        ('PEUGEOT','default',NULL,'peugeot','peugeot','peugeot',true),
        ('RENAULT','default',NULL,'renault','renault','renault',true),
        ('CITROEN','default',NULL,'citroen','citroen','citroen',true),
        ('FIAT','default','Fiat','fiat','fiat','fiat',true),
        ('OPEL','default',NULL,'opel','opel','opel',true),
        ('VAUXHALL','default',NULL,'vauxhall','vauxhall','vauxhall',true),
        ('VOLVO','default','Volvo','volvo','volvo','volvo',true),
        ('SKODA','default',NULL,'skoda','skoda','skoda',true),
        ('MERCEDES','default','Mercedes-Benz','mercedes-benz','mercedes-benz','mercedes-benz',true),
        ('BMW','default','BMW','bmw','bmw','bmw',true),
        ('AUDI','default','Audi','audi','audi','audi',true),
        ('VOLKSWAGEN','default','Volkswagen','volkswagen','volkswagen','volkswagen',true),
        ('HYUNDAI','default','Hyundai','hyundai','hyundai','hyundai',true),
        ('KIA','default','Kia','kia','kia','kia',true),
        ('HAVAL','chinese',NULL,NULL,'haval','haval',true),
        ('GREAT WALL','chinese',NULL,'great-wall','great-wall','great-wall',true),
        ('CHERY','chinese',NULL,'chery','chery','chery',true),
        ('DONGFENG','chinese',NULL,NULL,'dongfeng','dongfeng',true),
        ('FOTON','chinese',NULL,NULL,'foton','foton',true),
        ('FAW','chinese',NULL,NULL,'faw','faw',true),
        ('SAIC MOTORS','chinese',NULL,NULL,'saic','saic',true),
        ('MAN','commercial',NULL,'man','man','man',true),
        ('SCANIA','commercial',NULL,NULL,'scania','scania',true),
        ('IVECO DAILY','commercial',NULL,'iveco','iveco','iveco',true),
        ('MITSUBISHI FUSO','commercial','Mitsubishi','mitsubishi','mitsubishi-fuso','mitsubishi-fuso',true),
        ('MARUTI SUZUKI','commercial','Suzuki','suzuki','maruti-suzuki','maruti-suzuki',true),
        ('TATA','commercial',NULL,NULL,'tata','tata',true),
        ('EICHER','commercial',NULL,NULL,'eicher','eicher',true),
        ('FORD','default','Ford','ford','ford','ford',true),
        ('JEEP','default','Jeep','jeep','jeep','jeep',true),
        ('LANDROVER','default','Land Rover','land-rover','land-rover','land-rover',true),
        ('CHEVROLET','default','Chevrolet','chevrolet','chevrolet','chevrolet',true),
        ('DODGE','default','Dodge','dodge','dodge','dodge',true),
        ('JAGUAR','default','Jaguar','jaguar','jaguar','jaguar',true)
    """)


def downgrade():
    op.drop_index('ix_expansion_makes_enabled', table_name='expansion_makes')
    op.drop_table('expansion_makes')
