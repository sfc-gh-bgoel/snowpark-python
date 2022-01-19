#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#
import datetime

import pytest

from snowflake.connector.errors import ProgrammingError
from snowflake.snowpark import Row, Session
from tests.utils import Utils


@pytest.fixture(scope="function")
def table_name_1(session: Session):
    table_name = Utils.random_name()
    Utils.create_table(session, table_name, "num int")
    session._run_query(f"insert into {table_name} values (1), (2), (3)")
    yield table_name
    Utils.drop_table(session, table_name)


@pytest.fixture(scope="function")
def table_name_4(session: Session):
    table_name = Utils.random_name()
    Utils.create_table(session, table_name, "num int")
    session._run_query(f"insert into {table_name} values (1), (2), (3)")
    yield table_name
    Utils.drop_table(session, table_name)


@pytest.fixture(scope="function")
def temp_table_name(session: Session, temp_schema: str):
    table_name = Utils.random_name()
    table_name_with_schema = f"{temp_schema}.{table_name}"
    Utils.create_table(session, table_name_with_schema, "str string")
    session._run_query(f"insert into {table_name_with_schema} values ('abc')")
    yield table_name
    Utils.drop_table(session, table_name_with_schema)


@pytest.fixture(scope="function")
def table_with_time(session: Session):
    table_name = Utils.random_name()
    Utils.create_table(session, table_name, "time time")
    session._run_query(
        f"insert into {table_name} select to_time(a) from values('09:15:29'),"
        f"('09:15:29.99999999') as T(a)"
    )
    yield table_name
    Utils.drop_table(session, table_name)


def test_read_snowflake_table(session, table_name_1):
    df = session.table(table_name_1)
    Utils.check_answer(df, [Row(1), Row(2), Row(3)])

    df1 = session.read.table(table_name_1)
    Utils.check_answer(df1, [Row(1), Row(2), Row(3)])

    db_schema_table_name = (
        f"{session.getCurrentDatabase()}.{session.getCurrentSchema()}.{table_name_1}"
    )
    df2 = session.table(db_schema_table_name)
    Utils.check_answer(df2, [Row(1), Row(2), Row(3)])

    df3 = session.read.table(db_schema_table_name)
    Utils.check_answer(df3, [Row(1), Row(2), Row(3)])


def test_save_as_snowflake_table(session, table_name_1):
    df = session.table(table_name_1)
    assert df.collect() == [Row(1), Row(2), Row(3)]
    table_name_2 = Utils.random_name()
    table_name_3 = Utils.random_name()
    try:
        # copy table_name_1 to table_name_2, default mode
        df.write.saveAsTable(table_name_2)

        df2 = session.table(table_name_2)
        assert df2.collect() == [Row(1), Row(2), Row(3)]

        # append mode
        df.write.mode("append").saveAsTable(table_name_2)
        df4 = session.table(table_name_2)
        assert df4.collect() == [Row(1), Row(2), Row(3), Row(1), Row(2), Row(3)]

        # ignore mode
        df.write.mode("IGNORE").saveAsTable(table_name_2)
        df3 = session.table(table_name_2)
        assert df3.collect() == [Row(1), Row(2), Row(3), Row(1), Row(2), Row(3)]

        # overwrite mode
        df.write.mode("OvErWrItE").saveAsTable(table_name_2)
        df5 = session.table(table_name_2)
        assert df5.collect() == [Row(1), Row(2), Row(3)]

        # test for append when the original table does not exist
        # need to create the table before insertion
        df.write.mode("aPpEnD").saveAsTable(table_name_3)
        df6 = session.table(table_name_3)
        assert df6.collect() == [Row(1), Row(2), Row(3)]

        # errorifexists mode
        with pytest.raises(ProgrammingError):
            df.write.mode("errorifexists").saveAsTable(table_name_2)
    finally:
        Utils.drop_table(session, table_name_2)
        Utils.drop_table(session, table_name_3)


@pytest.mark.skip(
    "Python doesn't have non-string argument for mode. Scala has this test but python doesn't need to."
)
def test_save_as_snowflake_table_string_argument(table_name_4):
    """
    Scala's `DataFrameWriter.mode()` accepts both enum values of SaveMode and str.
    It's conventional that python uses str and pyspark does use str only. So the above test method
    `test_save_as_snowflake_table` already tests the string argument. This test will be the same as
    `test_save_as_snowflake_table` if ported from Scala so it's omitted.
    """


def test_multipart_identifier(session, table_name_1):
    name1 = table_name_1
    name2 = session.getCurrentSchema() + "." + name1
    name3 = session.getCurrentDatabase() + "." + name2

    expected = [Row(1), Row(2), Row(3)]
    assert session.table(name1).collect() == expected
    assert session.table(name2).collect() == expected
    assert session.table(name3).collect() == expected

    name4 = Utils.random_name()
    name5 = session.getCurrentSchema() + "." + name4
    name6 = session.getCurrentDatabase() + "." + name5

    session.table(name1).write.mode("Overwrite").saveAsTable(name4)
    try:
        assert session.table(name4).collect() == expected
    finally:
        Utils.drop_table(session, name4)

    session.table(name1).write.mode("Overwrite").saveAsTable(name5)
    try:
        assert session.table(name4).collect() == expected
    finally:
        Utils.drop_table(session, name5)

    session.table(name1).write.mode("Overwrite").saveAsTable(name6)
    try:
        assert session.table(name6).collect() == expected
    finally:
        Utils.drop_table(session, name5)


def test_write_table_to_different_schema(session, temp_schema, table_name_1):
    name1 = table_name_1
    name2 = temp_schema + "." + name1
    session.table(name1).write.saveAsTable(name2)
    try:
        assert session.table(name2).collect() == [Row(1), Row(2), Row(3)]
    finally:
        Utils.drop_table(session, name2)


def test_read_from_different_schema(session, temp_schema, temp_table_name):
    table_from_different_schema = f"{temp_schema}.{temp_table_name}"
    df = session.table(table_from_different_schema)
    Utils.check_answer(df, [Row("abc")])


def test_quotes_upper_and_lower_case_name(session, table_name_1):
    tested_table_names = [
        '"' + table_name_1 + '"',
        table_name_1.lower(),
        table_name_1.upper(),
    ]
    for table_name in tested_table_names:
        Utils.check_answer(session.table(table_name), [Row(1), Row(2), Row(3)])


@pytest.mark.skip("To port from scala after Python implements Geography")
def test_table_with_semi_structured_types(session):
    pass


@pytest.mark.skip("To port from scala after Python implements Geography")
def test_row_with_geography(session):
    pass


def test_table_with_time_type(session, table_with_time):
    df = session.table(table_with_time)
    # snowflake time has accuracy to 0.99999999. Python has accuracy to 0.999999.
    Utils.check_answer(
        df,
        [Row(datetime.time(9, 15, 29)), Row(datetime.time(9, 15, 29, 999999))],
        sort=False,
    )


def test_consistent_table_name_behaviors(session):
    table_name = Utils.random_name()
    db = session.getCurrentDatabase()
    sc = session.getCurrentSchema()
    df = session.createDataFrame([[1], [2], [3]]).toDF("a")
    df.write.mode("overwrite").saveAsTable(table_name)
    table_names = [
        table_name,
        [table_name],
        [sc, table_name],
        [db, sc, table_name],
        f"{db}.{sc}.{table_name}",
    ]
    try:
        for tn in table_names:
            Utils.check_answer(session.table(tn), [Row(1), Row(2), Row(3)])
    finally:
        Utils.drop_table(session, table_name)

    for tn in table_names:
        df.write.mode("Overwrite").saveAsTable(tn)
        try:
            Utils.check_answer(session.table(table_name), [Row(1), Row(2), Row(3)])
        finally:
            Utils.drop_table(session, table_name)