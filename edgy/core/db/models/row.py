from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Type

from sqlalchemy.engine.result import Row

from edgy.core.db.models.base import EdgyBaseModel

if TYPE_CHECKING:  # pragma: no cover
    from edgy import Model


class ModelRow(EdgyBaseModel):
    """
    Builds a row for a specific model
    """

    @classmethod
    def from_sqla_row(
        cls,
        row: Row,
        select_related: Optional[Sequence[Any]] = None,
    ) -> Optional[Type["Model"]]:
        """
        Class method to convert a SQLAlchemy Row result into a EdgyModel row type.

        Looping through select_related fields if the query comes from a select_related operation.
        Validates if exists the select_related and related_field inside the models.

        When select_related and related_field exist for the same field being validated, the related
        field is ignored as it won't override the value already collected from the select_related.

        If there is no select_related, then goes through the related field where it **should**
        only return the instance of the the ForeignKey with the ID, making it lazy loaded.

        :return: Model class.
        """
        item: Dict[str, Any] = {}
        select_related = select_related or []

        for related in select_related:
            if "__" in related:
                first_part, remainder = related.split("__", 1)
                try:
                    model_cls = cls.fields[first_part].target
                except KeyError:
                    model_cls = getattr(cls, first_part).related_from
                item[first_part] = model_cls.from_sqla_row(row, select_related=[remainder])
            else:
                try:
                    model_cls = cls.fields[related].target
                except KeyError:
                    model_cls = getattr(cls, related).related_from
                item[related] = model_cls.from_sqla_row(row)

        # Populate the related names
        # Making sure if the model being queried is not inside a select related
        # This way it is not overritten by any value
        for related, foreign_key in cls.meta.foreign_key_fields.items():
            ignore_related: bool = cls.should_ignore_related_name(related, select_related)
            if ignore_related:
                continue

            model_related = foreign_key.target
            child_item = {}

            for column in cls.table.columns:
                if column.name not in model_related.fields.keys():
                    continue
                elif related not in child_item:
                    child_item[column.name] = row[related]
            item[related] = model_related(**child_item)

        # Pull out the regular column values.
        for column in cls.table.columns:
            # Making sure when a table is reflected, maps the right fields of the ReflectModel
            if column.name not in cls.fields.keys():
                continue

            elif column.name not in item:
                item[column.name] = row[column]

        return cls(**item)

    @classmethod
    def should_ignore_related_name(cls, related_name: str, select_related: Sequence[str]) -> bool:
        """
        Validates if it should populate the related field if select related is not considered.
        """
        for related_field in select_related:
            fields = related_field.split("__")
            if related_name in fields:
                return True
        return False