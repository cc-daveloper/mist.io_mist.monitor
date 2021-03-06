import logging

from pymongo import MongoClient
from memcache import Client as MemcacheClient

from mist.io.dal import StrField, IntField, FloatField, BoolField
from mist.io.dal import ListField, DictField
from mist.io.dal import OODict, FieldsList, make_field
from mist.core.dal import FieldsDict  # escapes mongo dots
from mist.core.dal import OODictMongoMemcache, OODictMongoMemcacheLock

from mist.monitor import config

from mist.monitor.exceptions import RuleNotFoundError
from mist.monitor.exceptions import ConditionNotFoundError


log = logging.getLogger(__name__)


class _IntList(FieldsList):
    _item_type = IntField


class Condition(OODictMongoMemcache):

    cond_id = StrField()

    uuid = StrField()
    rule_id = StrField()

    metric = StrField()
    operator = StrField()  # must be in ('gt', 'lt')
    aggregate = StrField()  # must be in ('all', 'any', 'avg')
    value = FloatField()  # threshold
    reminder_list = make_field(_IntList)()  # in seconds
    reminder_offset = IntField()  # seconds to add to items of reminder_list
    active_after = FloatField()  # timestamp

    state = BoolField()
    state_since = FloatField()
    incident_id = StrField()

    notification_level = IntField()

    def __init__(self, _dict=None, mongo_client=None, memcache_client=None):
        """Properly initialize OODictMongoMemcache for condition data."""
        super(Condition, self).__init__(
            memcache_host=config.MEMCACHED_URI,
            mongo_uri=config.MONGO_URI,
            mongo_db='mist',
            mongo_coll='conditions',
            mongo_id='cond_id',
            mongo_client=mongo_client,
            memcache_client=memcache_client,
            _dict=_dict
        )

    def get_from_cond_id(self, cond_id):
        """Populate self from db with data for conditon with specified id."""
        self.get_from_field('cond_id', cond_id)

    def get_machine(self):
        """Returns a Machine instance this rule is associated with."""
        # make sure mongo client is connected
        self._get_mongo_coll()
        # and reuse connection to initiate Machine instance
        machine = Machine(_dict=None,
                          mongo_client=self._mongo_client,
                          memcache_client=self._memcache)
        machine.get_from_uuid(self.uuid)
        return machine

    def __str__(self):
        """Return a human readable string representation of this condition."""
        if self.operator == 'lt':
            operator = '<'
        elif self.operator == 'gt':
            operator = '>'
        else:
            operator = "?"
        return "%s(%s)%s%s for 60+%ds" % (
            self.aggregate, self.metric, operator, self.value,
            self.reminder_offset
        )


def get_condition_from_cond_id(cond_id):
    """Helper function that returns a Condition instance of this cond_id."""
    condition = Condition()
    condition.get_from_cond_id(cond_id)
    return condition


class Rule(OODict):
    """A rule object is mainly a set of pointers to conditions."""
    warning = StrField()


class Rules(FieldsDict):
    """A rules dict-like object inside a Machine instance."""
    _item_type = make_field(Rule)
    _key_error = RuleNotFoundError


class Machine(OODictMongoMemcacheLock):
    """A monitored machine in the machines list of some backend"""

    uuid = StrField()

    collectd_password = StrField()

    enabled_time = FloatField()
    activated = BoolField()

    rules = make_field(Rules)()

    def __init__(self, _dict=None, mongo_client=None, memcache_client=None):
        """Properly initialize OODictMongo for machine data."""
        super(Machine, self).__init__(
            memcache_host=config.MEMCACHED_URI,
            mongo_uri=config.MONGO_URI,
            mongo_db='mist',
            mongo_coll='machines',
            mongo_id='uuid',
            mongo_client=mongo_client,
            memcache_client=memcache_client,
            _dict=_dict
        )

    def get_from_uuid(self, uuid):
        """Populate self from db with data for machine with specified uuid."""
        self.get_from_field('uuid', uuid)

    def get_condition(self, rule_id):
        """Returns a Condition instance this rule is associated with."""
        # make sure mongo client is connected
        self._get_mongo_coll()
        # and reuse connection to initiate Condition instance
        condition = Condition(_dict=None,
                              mongo_client=self._mongo_client,
                              memcache_client=self._memcache)
        cond_id = self.rules[rule_id].warning
        condition.get_from_cond_id(cond_id)
        if not condition:
            raise ConditionNotFoundError(cond_id)
        return condition

    def __str__(self):
        """A human readable represantation of a machine with monitoring."""
        msg = "Machine '%s' (%d rules)" % (self.uuid, len(self.rules))
        for rule_id in self.rules:
            msg += "\n - %s" % self.get_condition(rule_id)
        return msg


def get_machine_from_uuid(uuid):
    """Helper function that returns a Machine instance of this uuid."""
    machine = Machine()
    machine.get_from_uuid(uuid)
    return machine


def get_all_machines(mongo_uri=None):
    """Get an iterator over all machine entries"""
    conn = MongoClient(mongo_uri or config.MONGO_URI)
    cache = MemcacheClient(config.MEMCACHED_URI)
    machines_cursor = conn['mist'].machines.find()
    return (Machine(machine_dict, conn, cache) for machine_dict in machines_cursor)
