r"""
=================================================
Functions for sqlite db
=================================================
"""


import os
import sqlite3


def clear_db(database_name):
    if os.path.exists(database_name):
        os.remove(database_name)
    if os.path.exists(database_name + "-journal"):
        os.remove(database_name + "-journal")


def create_sql_table(database_name, table_name, cols, d_types):
    conn = sqlite3.connect(database_name)
    c = conn.cursor()
    s = ""
    for i in range(len(cols)):
        if i == 0:
            s = s + cols[i] + " " + d_types[i] + " " + "PRIMARY KEY, "
        elif i == len(cols) - 1:
            s = s + cols[i] + " " + d_types[i]
        else:
            s = s + cols[i] + " " + d_types[i] + "," + " "
    fs = "(" + s + ")"
    c.execute(
        """CREATE TABLE if not exists """ + table_name + """ """ + fs + """;"""
    )
    conn.commit()


def execute_sql_command(command: str, database_name: str, values) -> None:
    """
    Function to execute a SQL command from Python.
    Parameters
    ----------
    command: str
        SQL command (use strings with three quotes on each side
        so that it can be a multiline string
    database_name: str
        File name of the database (e.g, “my.db”)
    Returns
    -------
    No return, executes the command
    """
    # will create if not present
    conn = sqlite3.connect(database_name, timeout=30.0)
    c = conn.cursor()
    if len(values) == 0:
        c.execute(command)
    elif type(values) == list:
        c.executemany(command, values)
    else:
        c.execute(command, values)
    # saves the changes
    conn.commit()
