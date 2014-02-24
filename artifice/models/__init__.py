from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Text, DateTime, Boolean, DECIMAL, ForeignKey, String 
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method

from sqlalchemy import select, func, and_, event, DDL

from sqlalchemy.orm import relationship
from sqlalchemy.schema import ForeignKeyConstraint
import datetime

from sqlalchemy.dialects.postgresql import ExcludeConstraint, TSRANGE


Base = declarative_base()
#

class Resource(Base):
    """Database model for storing metadata associated with a resource."""
    __tablename__ = 'resources'
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True )
    info = Column(Text)
    created = Column(DateTime, nullable=False)

class UsageEntry(Base):
    """Simplified data store of usage information for a given service,
       in a resource, in a tenant. Similar to ceilometer datastore,
       but stores local transformed data."""
    __tablename__ = 'usage'

    # Service is things like incoming vs. outgoing, as well as instance
    # flavour
    service = Column(String(100), primary_key=True)
    volume = Column(DECIMAL, nullable=False)
    resource_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), primary_key=True)
    start = Column(DateTime, nullable=False)
    end = Column(DateTime, nullable=False)
    created = Column(DateTime, nullable=False)

    resource = relationship(Resource,
                            primaryjoin=(resource_id == Resource.id))
    tenant = relationship(Resource,
                          primaryjoin=(tenant_id == Resource.tenant_id))

    __table_args__ = ( ForeignKeyConstraint(
        ["resource_id", "tenant_id"],
        ["resources.id", "resources.tenant_id"],
        name="fk_resource", use_alter=True
        ), )

    @hybrid_property
    def length(self):
        return self.end - self.start
    
    @hybrid_method
    def intersects(self, other):
        return ( self.start <= other.end and other.start <= self.end )

class Tenant(Base):
    """Model for storage of metadata related to a tenant."""
    __tablename__ = 'tenants'
    # ID is a uuid
    id = Column(String(36), primary_key=True, nullable=False)
    name = Column(Text, nullable=False)
    info = Column(Text)
    active = Column(Boolean, default=True)
    created = Column(DateTime, nullable=False)

    resources = relationship(Resource, backref="tenant")
    usages = relationship(UsageEntry, backref="tenant")
    # Some reference data to something else?
    #

# this might not be a needed model?
class SalesOrder(Base):
    """Historic billing periods so that tenants cannot be rebuild accidentally."""
    __tablename__ = 'sales_orders'
    tenant_id = Column(String(36), primary_key=True)
    resource_id = Column(String(36), primary_key=True)
    start = Column(DateTime, nullable=False)
    end = Column(DateTime, nullable=False)

    @hybrid_property
    def length(self):
        return self.end - self.start
    
    @hybrid_method
    def intersects(self, other):
        return ( self.start <= other.end and other.start <= self.end )

    __table_args__ = (  ForeignKeyConstraint(
        ["resource_id", "tenant_id"],
        ["resources.id", "resources.tenant_id"],
        name="fk_sales", use_alter=True
        ), )


# Create a trigger in MySQL that enforces our range overlap constraints,
# since MySQL lacks a native range overlap type.

# Mysql trigger:
mysql_trigger = """CREATE TRIGGER usage_entry_range_constraint
               BEFORE %(type)s ON %(table)s
               FOR EACH ROW
               BEGIN
                DECLARE c INT;
                SET c = (select count(*) from %(table)s t 
                         WHERE ( NEW.start <= t.end
                                 AND t.start <= NEW.end )
                           AND tenant_id = NEW.tenant_id
                           AND resource_id = NEW.resource_id);
                IF c > 0 THEN
                    SET NEW.start = NULL
                    SET NEW.end = NULL
                END;
               END;;""" 


# before insert

for table in (SalesOrder.__table__, UsageEntry.__table__):
    for type_ in ("INSERT", "UPDATE"):
        event.listen(
            UsageEntry.__table__,
            "after_create",
            DDL(mysql_trigger % {
                "table": table,
                "type": type_}).\
            execute_if(dialect="mysql"))


# And the postgres constraints
# Ideally this would use Postgres' exclusion constraints and a TSRange type.
# This is currently not feasible because I can't find a way to emit different
# DDL for MySQL and Postgres to support the varying concepts (single vs. dual columns).

pgsql_trigger_func = """
CREATE FUNCTION %(table)s_exclusion_constraint_trigger() RETURNS trigger AS $trigger$
    DECLARE
        existing INTEGER = 0;
    BEGIN
        SELECT count(*) INTO existing FROM %(table)s t
         WHERE t.tenant_id = NEW.tenant_id
           AND t.resource_id = NEW.resource_id
           AND ( NEW.start <= t.end
                 AND t.start <= NEW.end );
        IF existing > 0 THEN
            RAISE SQLSTATE '23P01';
        END IF;
    END;
$trigger$ LANGUAGE PLPGSQL;
"""


pgsql_trigger = """
CREATE TRIGGER %(table)s_exclusion_trigger BEFORE INSERT OR UPDATE ON %(table)s
    FOR EACH ROW EXECUTE PROCEDURE %(table)s_exclusion_constraint_trigger();
"""

event.listen(
        UsageEntry.__table__,
        "after_create",
        DDL(pgsql_trigger_func % {"table": UsageEntry.__tablename__}).execute_if(dialect="postgresql")
)
event.listen(
        UsageEntry.__table__,
        "after_create",
        DDL(pgsql_trigger % {"table": UsageEntry.__tablename__}).execute_if(dialect="postgresql")
        )

event.listen(
        SalesOrder.__table__,
        "after_create",
        DDL(pgsql_trigger_func % {"table": SalesOrder.__tablename__}).execute_if(dialect="postgresql")
)

event.listen(
        SalesOrder.__table__,
        "after_create",
        DDL(pgsql_trigger % {"table": SalesOrder.__tablename__}).\
                execute_if(dialect="postgresql")
)

event.listen(
        UsageEntry.__table__,
        "before_drop",
        DDL("DROP TRIGGER %s_exclusion_trigger" % UsageEntry.__tablename__).\
                execute_if(dialect="postgresql")
)

event.listen(
        UsageEntry.__table__,
        "before_drop",
        DDL("DROP FUNCTION %s_exclusion_constraint_trigger()" % UsageEntry.__tablename__ ).\
                execute_if(dialect="postgresql")
)

event.listen(
        UsageEntry.__table__,
        "before_drop",
        DDL("DROP TRIGGER %s_exclusion_trigger()" % SalesOrder.__tablename__ ).\
                execute_if(dialect="postgresql")
)

event.listen(
        UsageEntry.__table__,
        "before_drop",
        DDL("DROP FUNCTION %s_exclusion_constraint_trigger()" % SalesOrder.__tablename__ ).\
                execute_if(dialect="postgresql")
)
