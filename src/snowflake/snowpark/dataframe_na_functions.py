#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#
from logging import getLogger
from typing import Dict, List, Optional, Tuple, Union

import snowflake.snowpark
from snowflake.snowpark._internal.analyzer.analyzer_package import AnalyzerPackage
from snowflake.snowpark._internal.error_message import SnowparkClientExceptionMessages
from snowflake.snowpark._internal.sp_types.types_package import (
    _VALID_PYTHON_TYPES_FOR_LITERAL_VALUE,
    LiteralType,
    _python_type_to_snow_type,
)
from snowflake.snowpark.functions import iff, lit, when
from snowflake.snowpark.types import (
    DataType,
    DoubleType,
    FloatType,
    IntegerType,
    LongType,
)

logger = getLogger(__name__)


def _is_value_type_matching_for_na_function(
    value: LiteralType, datatype: DataType
) -> bool:
    # Python `int` can match into FloatType/DoubleType,
    # but Python `float` can't match IntegerType/LongType.
    # None should be compatible with any Snowpark type.
    return (
        value is None
        or (
            isinstance(value, int)
            and isinstance(datatype, (IntegerType, LongType, FloatType, DoubleType))
        )
        or (isinstance(value, float) and isinstance(datatype, (FloatType, DoubleType)))
        or isinstance(datatype, type(_python_type_to_snow_type(type(value))[0]))
    )


class DataFrameNaFunctions:
    """Provides functions for handling missing values in a :class:`DataFrame`."""

    def __init__(self, df: "snowflake.snowpark.dataframe.DataFrame"):
        self.df = df

    def drop(
        self,
        how: str = "any",
        thresh: Optional[int] = None,
        subset: Optional[Union[str, List[str], Tuple[str, ...]]] = None,
    ) -> "snowflake.snowpark.dataframe.DataFrame":
        """
        Returns a new DataFrame that excludes all rows containing fewer than
        a specified number of non-null and non-NaN values in the specified
        columns.

        Args:
            how: An ``str`` with value either 'any' or 'all'. If 'any', drop a row if
                it contains any nulls. If 'all', drop a row only if all its values are null.
                The default value is 'any'. If ``thresh`` is provided, ``how`` will be ignored.
            thresh: The minimum number of non-null and non-NaN
                values that should be in the specified columns in order for the
                row to be included. It overwrites ``how``. In each case:

                    * If ``thresh`` is not provided or ``None``, the length of ``subset``
                      will be used when ``how`` is 'any' and 1 will be used when ``how``
                      is 'all'.

                    * If ``thresh`` is greater than the number of the specified columns,
                      the method returns an empty DataFrame.

                    * If ``thresh`` is less than 1, the method returns the original DataFrame.

            subset: A list of the names of columns to check for null and NaN values.
                In each case:

                    * If ``subset`` is not provided or ``None``, all columns will be included.

                    * If ``subset`` is empty, the method returns the original DataFrame.

        Examples::

            df = session.createDataFrame([[1.0, 1], [float('nan'), 2], [None, 3], [4, None], [float('nan'), None]]).toDF("a", "b")
            # drop a row if it contains any nulls, with checking all columns
            df.na.drop()
            # drop a row only if all its values are null, with checking all columns
            df.na.drop(how='all')
            # drop a row if it contains at least one non-null and non-NaN values, with checking all columns
            df.na.drop(thresh=1)
            # drop a row if it contains any nulls, with checking column "a"
            df.na.drop(subset=["a"])

        See Also:
            :func:`DataFrame.dropna`
        """
        # translate to
        # select * from table where
        # iff(float_col = 'NaN' or float_col is null, 0, 1)
        # iff(non_float_col is null, 0, 1) >= thresh

        if how is not None and how not in ["any", "all"]:
            raise ValueError("how ('" + how + "') should be 'any' or 'all'")

        # if subset is not provided, drop will be applied to all columns
        if subset is None:
            subset = self.df.columns
        elif isinstance(subset, str):
            subset = [subset]
        elif not isinstance(subset, (list, tuple)):
            raise TypeError("subset should be a list or tuple of column names")

        # if thresh is not provided,
        # drop a row if it contains any nulls when how == 'any',
        # otherwise drop a row only if all its values are null.
        if thresh is None:
            thresh = len(subset) if how == "any" else 1

        # if thresh is less than 1, or no column is specified
        # to be dropped, return the dataframe directly
        if thresh < 1 or len(subset) == 0:
            return self.df
        # if thresh is greater than the number of columns,
        # drop a row only if all its values are null
        elif thresh > len(subset):
            return self.df.limit(0)
        else:
            df_col_type_dict = {
                AnalyzerPackage.quote_name(field.name): field.datatype
                for field in self.df.schema.fields
            }
            normalized_col_name_set = {
                AnalyzerPackage.quote_name(col_name) for col_name in subset
            }
            col_counter = None
            for normalized_col_name in normalized_col_name_set:
                if normalized_col_name not in df_col_type_dict:
                    raise SnowparkClientExceptionMessages.DF_CANNOT_RESOLVE_COLUMN_NAME(
                        normalized_col_name
                    )
                col = self.df.col(normalized_col_name)
                if isinstance(
                    df_col_type_dict[normalized_col_name], (FloatType, DoubleType)
                ):
                    # iff(col = 'NaN' or col is null, 0, 1)
                    is_na = iff((col == "NaN") | col.is_null(), 0, 1)
                else:
                    # iff(col is null, 0, 1)
                    is_na = iff(col.is_null(), 0, 1)
                if col_counter:
                    col_counter += is_na
                else:
                    col_counter = is_na
            return self.df.where(col_counter >= thresh)

    def fill(
        self,
        value: Union[LiteralType, Dict[str, LiteralType]],
        subset: Optional[Union[str, List[str], Tuple[str, ...]]] = None,
    ) -> "snowflake.snowpark.dataframe.DataFrame":
        """
        Returns a new DataFrame that replaces all null and NaN values in the specified
        columns with the values provided.

        Args:
            value: A scalar value or a ``dict`` that associates the names of columns with the
                values that should be used to replace null and NaN values in those
                columns. If ``value`` is a ``dict``, ``subset`` is ignored. If ``value``
                is an empty ``dict``, the method returns the original DataFrame.
            subset: A list of the names of columns to check for null and NaN values.
                In each case:

                    * If ``subset`` is not provided or ``None``, all columns will be included.

                    * If ``subset`` is empty, the method returns the original DataFrame.

        Examples::

            df = session.createDataFrame([[1.0, 1], [float('nan'), 2], [None, 3], [4, None], [float('nan'), None]]).toDF("a", "b")
            # fill null and NaN values in all columns
            df.na.fill(3.14)
            # fill null and NaN values in column "a"
            df.na.fill({"a": 3.14})
            # fill null and NaN values in column "a" and "b"
            df.na.fill({"a": 3.14, "b": 15})

        Note:
            If the type of a given value in ``value`` doesn't match the
            column data type (e.g. a ``float`` for :class:`~snowflake.snowpark.types.StringType`
            column), this replacement will be skipped in this column. Especially,

                * ``int`` can be filled in a column with
                  :class:`~snowflake.snowpark.types.FloatType` or
                  :class:`~snowflake.snowpark.types.DoubleType`, but ``float`` cannot
                  filled in a column with :class:`~snowflake.snowpark.types.IntegerType`
                  or :class:`~snowflake.snowpark.types.LongType`.

        See Also:
            :func:`DataFrame.fillna`
        """
        # translate to
        # select col, iff(float_col = 'NaN' or float_col is null, replacement, float_col)
        # iff(non_float_col is null, replacement, non_float_col) from table where

        if subset is None:
            subset = self.df.columns
        elif isinstance(subset, str):
            subset = [subset]
        elif not isinstance(subset, (list, tuple)):
            raise TypeError("subset should be a list or tuple of column names")

        if isinstance(value, dict):
            if not all([isinstance(k, str) for k in value.keys()]):
                raise ValueError("All keys in value should be column names (str)")
            value_dict = value
        else:
            value_dict = {col_name: value for col_name in subset}
        if not value_dict:
            return self.df
        if not all(
            [
                isinstance(v, _VALID_PYTHON_TYPES_FOR_LITERAL_VALUE)
                for v in value_dict.values()
            ]
        ):
            raise ValueError(
                "All values in value should be in one of "
                f"{_VALID_PYTHON_TYPES_FOR_LITERAL_VALUE} types"
            )

        # the dictionary is ordered after Python3.7
        df_col_type_dict = {
            AnalyzerPackage.quote_name(field.name): field.datatype
            for field in self.df.schema.fields
        }
        normalized_value_dict = {}
        for col_name, value in value_dict.items():
            normalized_col_name = AnalyzerPackage.quote_name(col_name)
            if normalized_col_name not in df_col_type_dict:
                raise SnowparkClientExceptionMessages.DF_CANNOT_RESOLVE_COLUMN_NAME(
                    normalized_col_name
                )
            normalized_value_dict[normalized_col_name] = value

        res_columns = []
        for col_name, datatype in df_col_type_dict.items():
            col = self.df.col(col_name)
            if col_name in normalized_value_dict:
                value = normalized_value_dict[col_name]
                if _is_value_type_matching_for_na_function(value, datatype):
                    if isinstance(datatype, (FloatType, DoubleType)):
                        # iff(col = 'NaN' or col is null, value, col)
                        res_columns.append(
                            iff((col == "NaN") | col.is_null(), value, col).as_(
                                col_name
                            )
                        )
                    else:
                        # iff(col is null, value, col)
                        res_columns.append(iff(col.is_null(), value, col).as_(col_name))
                else:
                    logger.warning(
                        "Input value type doesn't match the target column data type, "
                        f"this replacement was skipped. Column Name: {col_name}, "
                        f"Type: {datatype}, Input Value: {value}, Type: {type(value)}"
                    )
                    res_columns.append(col)
            else:
                # it's not in the value dict, just append the original column
                res_columns.append(col)

        return self.df.select(res_columns)

    def replace(
        self,
        to_replace: Union[
            LiteralType,
            List[LiteralType],
            Tuple[LiteralType, ...],
            Dict[LiteralType, LiteralType],
        ],
        value: Optional[
            Union[LiteralType, List[LiteralType], Tuple[LiteralType, ...]]
        ] = None,
        subset: Optional[Union[str, List[str], Tuple[str, ...]]] = None,
    ) -> "snowflake.snowpark.dataframe.DataFrame":
        """
        Returns a new DataFrame that replaces values in the specified columns.

        Args:
            to_replace: A scalar value, or a list of values or a ``dict`` that associates
                the original values with the replacement values. If ``to_replace``
                is a ``dict``, ``value`` and ``subset`` are ignored. To replace a null
                value, use ``None`` in ``to_replace``. To replace a NaN value, use
                ``float("nan")`` in ``to_replace``. If ``to_replace`` is empty,
                the method returns the original DataFrame.
            value: A scalar value, or a list of values for the replacement. If
                ``value`` is a list, ``value`` should be of the same length as
                ``to_replace``. If ``value`` is a scalar and ``to_replace`` is a list,
                then ``value`` is used as a replacement for each item in ``to_replace``.
            subset: A list of the names of columns in which the values should be
                replaced. If ``cols`` is not provided or ``None``, the replacement
                will be applied to all columns. If ``cols`` is empty, the method
                returns the original DataFrame.

        Examples::

            df = session.createDataFrame([[1, 1.0, "1.0"], [2, 2.0, "2.0"]], schema=["a", "b", "c"])
            # replace 1 with 3 in all columns
            df.na.replace(1, 3)
            # replace 1 with 3 and 2 with 4 in all columns
            df.na.replace([1, 2], [3, 4])
            # replace 1 with 3 and 2 with 3 in all columns
            df.na.replace([1, 2], 3)
            # the following line intends to replaces 1 with 3 and 2 with 4 in all columns
            # and will give [Row(3, 3.0, "1.0"), Row(4, 4.0, "2.0")]
            df.na.replace({1: 3, 2: 4})
            # the following line intends to replace 1 with "3" in column "a",
            # but will be ignored since "3" (str) doesn't match the original data type
            df.na.replace({1: "3"}, ["a"])

        Note:
            If the type of a given value in ``to_replace`` or ``value`` doesn't match the
            column data type (e.g. a ``float`` for :class:`~snowflake.snowpark.types.StringType`
            column), this replacement will be skipped in this column. Especially,

                * ``int`` can replace or be replaced in a column with
                  :class:`~snowflake.snowpark.types.FloatType` or
                  :class:`~snowflake.snowpark.types.DoubleType`, but ``float`` cannot
                  replace or be replaced in a column with :class:`~snowflake.snowpark.types.IntegerType`
                  or :class:`~snowflake.snowpark.types.LongType`.

                * ``None`` can replace or be replaced in a column with any data type.

        See Also:
            :func:`DataFrame.replace`
        """
        if subset is None:
            subset = self.df.columns
        elif isinstance(subset, str):
            subset = [subset]
        elif not isinstance(subset, (list, tuple)):
            raise TypeError("subset should be a list or tuple of column names")
        elif len(subset) == 0:
            return self.df

        if isinstance(to_replace, dict):
            replacement = to_replace
        elif isinstance(to_replace, (list, tuple)):
            if isinstance(value, (list, tuple)):
                if len(to_replace) != len(value):
                    raise ValueError(
                        "to_replace and value lists should be of the same length."
                        f"Got {len(to_replace)} and {len(value)}"
                    )
                else:
                    replacement = {k: v for k, v in zip(to_replace, value)}
            else:
                replacement = {k: value for k in to_replace}
        else:
            replacement = {to_replace: value}
        if not replacement:
            return self.df
        if not all(
            [
                isinstance(k, _VALID_PYTHON_TYPES_FOR_LITERAL_VALUE)
                and isinstance(v, _VALID_PYTHON_TYPES_FOR_LITERAL_VALUE)
                for k, v in replacement.items()
            ]
        ):
            raise ValueError(
                "All keys and values in value should be in one of "
                f"{_VALID_PYTHON_TYPES_FOR_LITERAL_VALUE} types"
            )

        # the dictionary is ordered after Python3.7
        df_col_type_dict = {
            AnalyzerPackage.quote_name(field.name): field.datatype
            for field in self.df.schema.fields
        }
        normalized_col_name_set = {
            AnalyzerPackage.quote_name(col_name) for col_name in subset
        }
        for normalized_col_name in normalized_col_name_set:
            if normalized_col_name not in df_col_type_dict:
                raise SnowparkClientExceptionMessages.DF_CANNOT_RESOLVE_COLUMN_NAME(
                    normalized_col_name
                )

        res_columns = []
        for col_name, datatype in df_col_type_dict.items():
            col = self.df.col(col_name)
            if col_name in normalized_col_name_set:
                case_when = None
                for key, value in replacement.items():
                    if _is_value_type_matching_for_na_function(
                        key, datatype
                    ) and _is_value_type_matching_for_na_function(value, datatype):
                        cond = col.is_null() if key is None else (col == lit(key))
                        replace_value = lit(None) if value is None else lit(value)
                        case_when = (
                            case_when.when(cond, replace_value)
                            if case_when
                            else when(cond, replace_value)
                        )
                    else:
                        logger.warning(
                            "Input key or value type doesn't match the target column data type, "
                            f"this replacement was skipped. Column Name: {col_name}, "
                            f"Type: {datatype}, Input Key: {key}, Type: {type(key)}, "
                            f"Input Value: {value}, Type: {type(value)}"
                        )
                if case_when:
                    case_when = case_when.otherwise(col).as_(col_name)
                    res_columns.append(case_when)
                else:
                    # all replacements are skipped due to data type mismatch
                    res_columns.append(col)
            else:
                res_columns.append(col)

        return self.df.select(res_columns)