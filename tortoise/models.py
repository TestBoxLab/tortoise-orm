import operator

from pypika import Table

from tortoise import fields
from tortoise.fields import ManyToManyRelationManager, RelationQueryContainer
from tortoise.queryset import QuerySet


def is_in(field, value):
    return field.isin(value)


def not_in(field, value):
    return field.notin(value) | field.isnull()


def not_equal(field, value):
    return field.ne(value) | field.isnull()


def is_null(field, value):
    return field.isnull(value)


def not_null(field, value):
    return field.notnull(value)


def get_m2m_filters(field_name, field):
    filters = {
        field_name: {
            'field': field.forward_key,
            'backward_key': field.backward_key,
            'operator': operator.eq,
            'table': Table(field.through),
        },
        '{}__not'.format(field_name): {
            'field': field.forward_key,
            'backward_key': field.backward_key,
            'operator': not_equal,
            'table': Table(field.through),
        },
        '{}__in'.format(field_name): {
            'field': field.forward_key,
            'backward_key': field.backward_key,
            'operator': is_in,
            'table': Table(field.through),
        },
        '{}__not_in'.format(field_name): {
            'field': field.forward_key,
            'backward_key': field.backward_key,
            'operator': not_in,
            'table': Table(field.through),
        },
    }
    return filters


def get_backward_fk_filters(field_name, field):
    filters = {
        field_name: {
            'field': 'id',
            'backward_key': field.relation_field,
            'operator': operator.eq,
            'table': Table(field.type._meta.table),
        },
        '{}__not'.format(field_name): {
            'field': 'id',
            'backward_key': field.relation_field,
            'operator': not_equal,
            'table': Table(field.type._meta.table),
        },
        '{}__in'.format(field_name): {
            'field': 'id',
            'backward_key': field.relation_field,
            'operator': is_in,
            'table': Table(field.type._meta.table),
        },
        '{}__not_in'.format(field_name): {
            'field': 'id',
            'backward_key': field.relation_field,
            'operator': not_in,
            'table': Table(field.type._meta.table),
        },
    }
    return filters


def get_filters_for_field(field_name: str, field: fields.Field, source_field: str):
    if isinstance(field, fields.ManyToManyField):
        return get_m2m_filters(field_name, field)
    filters = {
        field_name: {
            'field': source_field,
            'operator': operator.eq,
        },
        '{}__not'.format(field_name): {
            'field': source_field,
            'operator': not_equal,
        },
        '{}__in'.format(field_name): {
            'field': source_field,
            'operator': is_in,
        },
        '{}__not_in'.format(field_name): {
            'field': source_field,
            'operator': not_in,
        },
        '{}__isnull'.format(field_name): {
            'field': source_field,
            'operator': is_null,
        },
        '{}__not_isnull'.format(field_name): {
            'field': source_field,
            'operator': not_null,
        },
        '{}__gte'.format(field_name): {
            'field': source_field,
            'operator': operator.ge,
        },
        '{}__lte'.format(field_name): {
            'field': source_field,
            'operator': operator.le,
        },
        '{}__gt'.format(field_name): {
            'field': source_field,
            'operator': operator.gt,
        },
        '{}__lt'.format(field_name): {
            'field': source_field,
            'operator': operator.lt,
        },
    }
    return filters


class MetaInfo:
    def __init__(self, meta):
        self.abstract = getattr(meta, 'abstract', False)
        self.table = getattr(meta, 'table', None)
        self.app = getattr(meta, 'app', 'models')
        self.fields = set()
        self.db_fields = set()
        self.m2m_fields = set()
        self.fk_fields = set()
        self.backward_fk_fields = set()
        self.fetch_fields = set()
        self.fields_db_projection = {}
        self.fields_db_projection_reverse = {}
        self.filters = {}
        self.fields_map = {}
        self.db = None


class ModelMeta(type):
    def __new__(mcs, name, bases, attrs, *args, **kwargs):
        fields_db_projection = {}
        fields_map = {}
        filters = {}
        fk_fields = set()
        m2m_fields = set()
        meta = MetaInfo(attrs.get('Meta'))

        for key, value in attrs.items():
            if isinstance(value, fields.Field):
                fields_map[key] = value
                if isinstance(value, fields.ForeignKeyField):
                    key_field = '{}_id'.format(key)
                    fields_db_projection[key_field] = key_field
                    fields_map[key_field] = fields.Field(int)
                    filters.update(get_filters_for_field(
                        field_name=key_field,
                        field=fields_map[key_field],
                        source_field=key_field
                    ))
                    fk_fields.add(key)
                elif isinstance(value, fields.ManyToManyField):
                    m2m_fields.add(key)
                else:
                    fields_db_projection[key] = value.source_field if value.source_field else key
                    filters.update(get_filters_for_field(
                        field_name=key,
                        field=fields_map[key],
                        source_field=fields_db_projection[key]
                    ))
        new_class = super().__new__(mcs, name, bases, attrs)

        new_class._meta = meta
        new_class._meta.fields_map = fields_map
        new_class._meta.fields_db_projection = fields_db_projection
        new_class._meta.fields_db_projection_reverse = {
            value: key for key, value in fields_db_projection.items()
        }
        new_class._meta.fields = set(fields_map.keys())
        new_class._meta.db_fields = set(fields_db_projection.values())
        new_class._meta.filters = filters
        new_class._meta.fk_fields = fk_fields
        new_class._meta.backward_fk_fields = set()
        new_class._meta.m2m_fields = m2m_fields
        new_class._meta.fetch_fields = fk_fields | m2m_fields
        new_class._meta.db = None
        if not fields_map:
            new_class._meta.abstract = True
        if not new_class._meta.abstract:
            from tortoise import Tortoise
            Tortoise.register_model(new_class._meta.app, new_class.__name__, new_class)
        return new_class


class Model(metaclass=ModelMeta):
    def __init__(self, *args, **kwargs):
        for key, field in self._meta.fields_map.items():
            if isinstance(field, fields.BackwardFKRelation):
                setattr(self, key, RelationQueryContainer(field.type, field.relation_field, self))
            elif isinstance(field, fields.ManyToManyField):
                setattr(self, key, ManyToManyRelationManager(field.type, self, field))
            elif isinstance(field, fields.Field):
                setattr(self, key, field.default)
            else:
                setattr(self, key, None)

        for key, value in kwargs.items():
            if key in self._meta.fk_fields:
                assert hasattr(value, 'id') and value.id, (
                    'You should first call .save() on {} before referring to it'.format(value)
                )
                setattr(self, '{}_id'.format(key), value.id)
            elif key in self._meta.backward_fk_fields:
                raise AssertionError(
                    'You can\'t set backward relations through init, change related model instead'
                )
            elif key in self._meta.m2m_fields:
                raise AssertionError(
                    'You can\'t set m2m relations through init, use m2m_manager instead'
                )
            elif key in self._meta.fields:
                setattr(self, key, value)
            elif key in self._meta.db_fields:
                setattr(self, self._meta.fields_db_projection_reverse.get(key), value)

    async def _insert_instance(self, using_db=None):
        db = using_db if using_db else self._meta.db
        await db.executor_class(
            model=self.__class__,
            db=db,
        ).execute_insert(self)

    async def _update_instance(self, using_db=None):
        db = using_db if using_db else self._meta.db
        await db.executor_class(
            model=self.__class__,
            db=db,
        ).execute_update(self)

    async def save(self, *args, **kwargs):
        if not self.id:
            await self._insert_instance(*args, **kwargs)
        else:
            await self._update_instance(*args, **kwargs)

    @classmethod
    async def create(cls, **kwargs):
        instance = cls(**kwargs)
        await instance.save(kwargs.get('using_db'))
        return instance

    async def delete(self, using_db=None):
        db = using_db if using_db else self._meta.db
        if not self.id:
            return
        await db.executor_class(
            model=self.__class__,
            db=db,
        ).execute_delete(self)

    def m2m_manager(self, field_name, using_db=None):
        assert field_name in self._meta.m2m_fields
        return ManyToManyRelationManager(self, self._meta.fields_map[field_name], using_db)

    async def fetch_related(self, *args, using_db=None):
        db = using_db if using_db else self._meta.db
        await db.executor_class(
            model=self.__class__,
            db=db,
        ).prefetch_for_list([self], *args)

    def __str__(self):
        return self.__class__.__name__

    def __repr__(self):
        return '<{}: {}>'.format(
            self.__class__.__name__,
            self.__str__()
        )

    def __hash__(self):
        if not hasattr(self.id) or not self.id:
            raise TypeError('Model instances without id are unhashable')
        return hash(self.id)

    def __eq__(self, other):
        if type(self) == type(other) and self.id == other.id:
            return True
        return False

    @classmethod
    async def get_or_create(cls, using_db=None, defaults=None, **kwargs):
        if not defaults:
            defaults = {}
        instance = await cls.filter(**kwargs).first()
        if instance:
            return instance, False
        return await cls(**defaults, **kwargs).save(using_db=using_db), True

    @classmethod
    def first(cls):
        return QuerySet(cls).first()

    @classmethod
    def filter(cls, *args, **kwargs):
        return QuerySet(cls).filter(*args, **kwargs)

    @classmethod
    def all(cls):
        return QuerySet(cls)

    class Meta:
        pass