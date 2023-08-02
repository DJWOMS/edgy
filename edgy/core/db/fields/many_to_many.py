from typing import TYPE_CHECKING, Any, Optional, Type, TypeVar, cast

import sqlalchemy

import edgy
from edgy.core.connection.registry import Registry
from edgy.core.db.constants import CASCADE, RESTRICT
from edgy.core.db.fields.base import BaseField
from edgy.core.db.fields.foreign_keys import ForeignKey
from edgy.core.terminal import Print
from edgy.core.utils.models import create_edgy_model

if TYPE_CHECKING:
    from edgy import Model

T = TypeVar("T", bound="Model")


CLASS_DEFAULTS = ["cls", "__class__", "kwargs"]
terminal = Print()


class ForeignKeyFieldFactory:
    """The base for all model fields to be used with Edgy"""

    _type: Any = None

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseField:  # type: ignore
        cls.validate(**kwargs)

        to: Any = kwargs.pop("to", None)
        null: bool = kwargs.pop("null", False)
        on_update: str = kwargs.pop("on_update", CASCADE)
        on_delete: str = kwargs.pop("on_delete", RESTRICT)
        related_name: str = kwargs.pop("related_name", None)
        comment: str = kwargs.pop("comment", None)
        through: Any = kwargs.pop("through", None)
        owner: Any = kwargs.pop("owner", None)
        server_default: Any = kwargs.pop("server_default", None)
        server_onupdate: Any = kwargs.pop("server_onupdate", None)
        registry: Registry = kwargs.pop("registry", None)
        is_o2o = kwargs.pop("is_o2o", False)
        is_fk = kwargs.pop("is_fk", False)
        is_m2m = True
        field_type = cls._type

        namespace = dict(
            __type__=field_type,
            to=to,
            on_update=on_update,
            on_delete=on_delete,
            related_name=related_name,
            annotation=field_type,
            null=null,
            comment=comment,
            owner=owner,
            server_default=server_default,
            server_onupdate=server_onupdate,
            through=through,
            registry=registry,
            column_type=field_type,
            is_m2m=is_m2m,
            is_o2o=is_o2o,
            is_fk=is_fk,
            constraints=cls.get_constraints(),
            **kwargs,
        )
        Field = type(cls.__name__, (BaseManyToManyForeignKeyField, BaseField), {})
        return Field(**namespace)  # type: ignore

    @classmethod
    def validate(cls, **kwargs: Any) -> None:  # pragma no cover
        """
        Used to validate if all required parameters on a given field type are set.
        :param kwargs: all params passed during construction
        :type kwargs: Any
        """

    @classmethod
    def get_column_type(cls, **kwargs: Any) -> Any:
        """Returns the propery column type for the field"""
        return None

    @classmethod
    def get_constraints(cls, **kwargs: Any) -> Any:
        return []


class BaseManyToManyForeignKeyField(BaseField):
    is_m2m: bool = True

    def add_model_to_register(self, model: Any) -> None:
        """
        Adds the model to the registry to make sure it can be generated by the Migrations
        """
        self.registry.models[model.__name__] = model

    def create_through_model(self) -> Any:
        """
        Creates the default empty through model.

        Generates a middle model based on the owner of the field and the field itself and adds
        it to the main registry to make sure it generates the proper models and migrations.
        """
        from edgy.core.db.models.metaclasses import MetaInfo

        if self.through:  # type: ignore
            if isinstance(self.through, str):  # type: ignore
                self.through = self.owner.meta.registry.models[self.through]  # type: ignore

            self.through.meta.is_multi = True
            self.through.meta.multi_related = [self.to.__name__.lower()]  # type: ignore
            return self.through

        owner_name = self.owner.__name__
        to_name = self.to.__name__
        class_name = f"{owner_name}{to_name}"
        tablename = f"{owner_name.lower()}s_{to_name}s".lower()

        new_meta_namespace = {
            "tablename": tablename,
            "registry": self.registry,
            "is_multi": True,
            "multi_related": [to_name.lower()],
        }

        new_meta: MetaInfo = MetaInfo(None)
        new_meta.load_dict(new_meta_namespace)

        # Define the related names
        owner_related_name = (
            f"{self.related_name}_{class_name.lower()}s_set"
            if self.related_name
            else f"{owner_name.lower()}_{class_name.lower()}s_set"
        )

        to_related_name = (
            f"{self.related_name}"
            if self.related_name
            else f"{to_name.lower()}_{class_name.lower()}s_set"
        )
        fields = {
            "id": edgy.IntegerField(primary_key=True),
            f"{owner_name.lower()}": ForeignKey(  # type: ignore
                self.owner,
                null=True,
                on_delete=CASCADE,
                related_name=owner_related_name,
            ),
            f"{to_name.lower()}": ForeignKey(  # type: ignore
                self.to, null=True, on_delete=CASCADE, related_name=to_related_name
            ),
        }

        # Create the through model
        through_model = create_edgy_model(
            __name__=class_name,
            __module__=self.__module__,
            __definitions__=fields,
            __metadata__=new_meta,
        )
        self.through = cast(Type["Model"], through_model)

        self.add_model_to_register(self.through)

    @property
    def target(self) -> Any:
        if not hasattr(self, "_target"):
            if isinstance(self.to, str):
                self._target = self.registry.models[self.to]  # type: ignore
            else:
                self._target = self.to
        return self._target

    def get_column(self, name: str) -> sqlalchemy.Column:
        target = self.target
        to_field = target.fields[target.pkname]

        column_type = to_field.column_type
        constraints = [
            sqlalchemy.schema.ForeignKey(
                f"{target.meta.tablename}.{target.pkname}",
                ondelete=CASCADE,
                onupdate=CASCADE,
                name=f"fk_{self.owner.meta.tablename}_{target.meta.tablename}"
                f"_{target.pkname}_{name}",
            )
        ]
        return sqlalchemy.Column(name, column_type, *constraints, nullable=self.null)

    def has_default(self) -> bool:
        """Checks if the field has a default value set"""
        return hasattr(self, "default")


class ManyToManyField(ForeignKeyFieldFactory):
    _type = sqlalchemy.ForeignKey

    def __new__(  # type: ignore
        cls,
        to: "Model",
        *,
        through: Optional["Model"] = None,
        **kwargs: Any,
    ) -> BaseField:
        null = kwargs.get("null", None)
        if null:
            terminal.write_warning("Declaring `null` on a ManyToMany relationship has no effect.")

        kwargs = {
            **kwargs,
            **{key: value for key, value in locals().items() if key not in CLASS_DEFAULTS},
        }
        kwargs["null"] = True
        return super().__new__(cls, **kwargs)

    @classmethod
    def validate(cls, **kwargs: Any) -> None:
        related_name = kwargs.get("related_name", None)

        if related_name:
            assert isinstance(related_name, str), "related_name must be a string."

        kwargs["related_name"] = related_name.lower() if related_name else None


ManyToMany = ManyToManyField