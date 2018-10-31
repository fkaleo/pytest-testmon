# -*- coding: utf-8 -*-

from collections import defaultdict
import os
import tempfile
import sqlite3

marks = list()


def pytest_sessionstart(session):
    conn = sqlite3.connect(os.path.join(str(session.config.rootdir), ".runtime_info"))
    conn.execute("PRAGMA recursive_triggers = TRUE ")
    conn.execute("PRAGMA foreign_keys=on")
    init_table(conn.cursor())
    session.config.conn = conn


def pytest_runtest_makereport(call, item):
    conn = item.config.conn
    c = conn.cursor()

    with conn:
        if call.excinfo:
            last_mark_info = None
            exception_text = get_exception_text(call.excinfo)
            for traceback_entry in call.excinfo.traceback:
                if not is_project_path(traceback_entry.path, item.config.rootdir):
                    continue  # skiping files outside of project path
                striped_statement = str(traceback_entry.statement).lstrip()
                start = len(str(traceback_entry.statement)) - len(striped_statement)
                mark_info = {
                    "exception_text": exception_text,
                    "path": str(traceback_entry.path),
                    "line": traceback_entry.lineno,
                    "start": start,
                    "end": len(str(traceback_entry.statement)),
                    "check_output": striped_statement
                }
                if last_mark_info:
                    mark_info["prev"] = last_mark_info
                    last_mark_info["next"] = mark_info
                marks.append(mark_info)
                last_mark_info = mark_info
            if last_mark_info:
                exception_id = insert_exception(c,
                                                item.nodeid,
                                                exception_text,
                                                last_mark_info)
                insert_file_mark(c, marks, exception_id)
        elif call.when == 'setup':
            remove_exception_by_nodeid(c, item.nodeid)
    marks.clear()


def is_project_path(path, cwd):
    prefix = os.path.commonprefix([str(path), str(cwd)])
    if cwd == prefix:
        return True
    return False


def get_exception_text(excinfo):
    reason = str(excinfo.value)
    typename = str(excinfo.typename)
    return "{}: {}".format(typename, reason)


def remove_exception_by_nodeid(c, nodeid):
    c.execute("""DELETE FROM Exception
                WHERE nodeid=:nodeid
    """, {"nodeid": nodeid})


def init_table(c):
    # check if there is a table named FileMark in the database, if not: create
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='FileMark'")

    if c.fetchone() is None:
        c.execute("""CREATE TABLE Exception (
                    exception_id INTEGER PRIMARY KEY,
                    nodeid text UNIQUE,
                    file_name text,
                    line integer,
                    exception_text text
        )""")

        c.execute("""CREATE TABLE FileMark (
                    file_mark_id INTEGER PRIMARY KEY,
                    type text,
                    text text,
                    file_name text,
                    begin_line integer,
                    begin_character integer,
                    end_line integer,
                    end_character integer,
                    check_content text,
                    target_path text,
                    target_line integer,
                    target_character integer,
                    gutterLinkType text,
                    exception_id integer NOT NULL,
                        FOREIGN KEY (exception_id) REFERENCES exception(exception_id)
                        ON DELETE CASCADE
        )""")


def insert_exception(c, nodeid, text, mark):
    c.execute("""INSERT OR REPLACE INTO Exception (
                nodeid,
                file_name,
                line,
                exception_text
                )
                VALUES (:nodeid, :file_name, :line, :exception_text)""", [nodeid, mark["path"], mark["line"], text])

    return c.lastrowid


def insert_file_mark(c, mark_list, exception_id):
    for mark in mark_list:
        param_list = []

        common_params = {
            "file_name": mark["path"],
            "begin_line": mark["line"],
            "check_output": mark["check_output"],
            "exception_id": exception_id
        }

        for mark_type in ["RedUnderLineDecoration", "Suffix"]:
            param_list.append(dict(
                common_params,
                **{
                    "type": mark_type,
                    "text": mark["exception_text"],
                    "begin_character": mark["start"],
                    "end_line": mark["line"],
                    "end_character": mark["end"],
                    "exception_id": exception_id
                }))

        if "prev" in mark:
            up = dict(common_params,
                      **{"type": "GutterLink",
                         "gutterLinkType": "U",
                         "target_path": mark["prev"]["path"],
                         "target_line": mark["prev"]["line"],
                         "target_character": mark["prev"]["start"],
                         })
            param_list.append(up)

        if "next" in mark:
            down = dict(common_params,
                        **{
                            "type": "GutterLink",
                            "gutterLinkType": "D",
                            "target_path": mark["next"]["path"],
                            "target_line": mark["next"]["line"],
                            "target_character": mark["next"]["start"],
                        })
            param_list.append(down)

        for params in param_list:
            c.execute("""INSERT INTO FileMark
                         VALUES (:id, :type, :text, :file_name, :begin_line, :begin_character,
                                :end_line, :end_character, :check_output, :target_path,
                                :target_line, :target_character, :gutterLinkType, :exception_id)""",
                      defaultdict(lambda: None, params))
