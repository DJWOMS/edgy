import functools
from typing import Any, ClassVar, Dict, Optional, Sequence

import sqlalchemy
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine
from typing_extensions import Self

from edgy.conf import settings
from edgy.core.db.datastructures import Index, UniqueConstraint
from edgy.core.db.fields.many_to_many import BaseManyToManyForeignKeyField
from edgy.core.db.models._internal import DescriptiveMeta
from edgy.core.db.models.managers import Manager
from edgy.core.db.models.metaclasses import BaseModelMeta, BaseModelReflectMeta, MetaInfo
from edgy.core.utils.functional import edgy_setattr
from edgy.core.utils.models import DateParser, ModelParser
from edgy.exceptions import ImproperlyConfigured


class EdgyBaseModel(BaseModel, DateParser, ModelParser, metaclass=BaseModelMeta):
    """
    Base of all Edgy models with the core setup.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    query: ClassVar[Manager] = Manager()
    meta: ClassVar[MetaInfo] = MetaInfo(None)
    Meta: ClassVar[DescriptiveMeta] = DescriptiveMeta()
    __db_model__: ClassVar[bool] = False
    __raw_query__: ClassVar[Optional[str]] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # type: ignore
        super().__init__(**kwargs)
        values = self.setup_model_fields_from_kwargs(kwargs)
        edgy_setattr(self, "__dict__", values)

    def setup_model_fields_from_kwargs(self, kwargs: Any) -> Any:
        """
        Loops and setup the kwargs of the model
        """
        if "pk" in kwargs:
            kwargs[self.pkname] = kwargs.pop("pk")

        kwargs = {k: v for k, v in kwargs.items() if k in self.meta.fields_mapping}

        for key, value in kwargs.items():
            if key not in self.fields:
                if not hasattr(self, key):
                    raise ValueError(f"Invalid keyword {key} for class {self.__class__.__name__}")

            # Set model field and add to the kwargs dict
            edgy_setattr(self, key, value)
            kwargs[key] = getattr(self, key)
        return kwargs

    @property
    def pk(self) -> Any:
        return getattr(self, self.pkname)

    @pk.setter
    def pk(self, value: Any) -> Any:
        edgy_setattr(self, self.pkname, value)

    @property
    def raw_query(self) -> Any:
        return getattr(self, self.__raw_query__)

    @raw_query.setter
    def raw_query(self, value: Any) -> Any:
        edgy_setattr(self, self.raw_query, value)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self}>"

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.pkname}={self.pk})"

    @property
    def table(self) -> sqlalchemy.Table:
        return self.__class__.table

    @classmethod
    def build(cls) -> sqlalchemy.Table:
        """
        Builds the SQLAlchemy table representation from the loaded fields.
        """
        tablename = cls.meta.tablename
        metadata = cls.meta.registry._metadata
        unique_together = cls.meta.unique_together
        index_constraints = cls.meta.indexes

        columns = []
        for name, field in cls.fields.items():
            columns.append(field.get_column(name))

        # Handle the uniqueness together
        uniques = []
        for field in unique_together or []:
            unique_constraint = cls._get_unique_constraints(field)
            uniques.append(unique_constraint)

        # Handle the indexes
        indexes = []
        for field in index_constraints or []:
            index = cls._get_indexes(field)
            indexes.append(index)

        return sqlalchemy.Table(
            tablename, metadata, *columns, *uniques, *indexes, extend_existing=True
        )

    @classmethod
    def _get_unique_constraints(cls, columns: Sequence) -> Optional[sqlalchemy.UniqueConstraint]:
        """
        Returns the unique constraints for the model.

        The columns must be a a list, tuple of strings or a UniqueConstraint object.

        :return: Model UniqueConstraint.
        """
        if isinstance(columns, str):
            return sqlalchemy.UniqueConstraint(columns)
        elif isinstance(columns, UniqueConstraint):
            return sqlalchemy.UniqueConstraint(*columns.fields)
        return sqlalchemy.UniqueConstraint(*columns)

    @classmethod
    def _get_indexes(cls, index: Index) -> Optional[sqlalchemy.Index]:
        """
        Creates the index based on the Index fields
        """
        return sqlalchemy.Index(index.name, *index.fields)

    def update_from_dict(self, dict_values: Dict[str, Any]) -> Self:
        """Updates the current model object with the new fields"""
        for key, value in dict_values.items():
            setattr(self, key, value)
        return self

    def extract_db_fields(self):
        """
        Extacts all the db fields and excludes the related_names since those
        are simply relations.
        """
        related_names = self.meta.related_names
        return {k: v for k, v in self.__dict__.items() if k not in related_names}

    def __setattr__(self, key: Any, value: Any) -> Any:
        if key in self.fields:
            # Setting a relationship to a raw pk value should set a
            # fully-fledged relationship instance, with just the pk loaded.
            field = self.fields[key]
            if isinstance(field, BaseManyToManyForeignKeyField):
                value = getattr(self, settings.many_to_many_relation.format(key=key))
            else:
                value = self.fields[key].expand_relationship(value)

        edgy_setattr(self, key, value)

    def __eq__(self, other: Any) -> bool:
        if self.__class__ != other.__class__:
            return False
        for key in self.fields.keys():
            if getattr(self, key, None) != getattr(other, key, None):
                return False
        return True


class EdgyBaseReflectModel(EdgyBaseModel, metaclass=BaseModelReflectMeta):
    """
    Reflect on async engines is not yet supported, therefore, we need to make a sync_engine
    call.
    """

    @classmethod
    @functools.lru_cache
    def get_engine(cls, url: str) -> Engine:
        return sqlalchemy.create_engine(url)

    @property
    def pk(self) -> Any:
        return getattr(self, self.pkname, None)

    @pk.setter
    def pk(self, value: Any) -> Any:
        setattr(self, self.pkname, value)

    @classmethod
    def build(cls) -> Any:
        """
        The inspect is done in an async manner and reflects the objects from the database.
        """
        metadata = cls.meta.registry._metadata  # type: ignore
        tablename = cls.meta.tablename
        return cls.reflect(tablename, metadata)

    @classmethod
    def reflect(cls, tablename, metadata):
        try:
            return sqlalchemy.Table(
                tablename, metadata, autoload_with=cls.meta.registry.sync_engine
            )
        except Exception as e:
            raise ImproperlyConfigured(
                detail=f"Table with the name {tablename} does not exist."
            ) from e