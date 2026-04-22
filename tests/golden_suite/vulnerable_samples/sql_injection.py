"""
SQL Injection Vulnerable Samples

This file contains multiple SQL injection vulnerabilities at different code patterns.
Each represents a real-world attack vector that must be detected by SecurityISO.
"""

import sqlite3
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Session


def get_user_by_id_raw_concat(user_id: str, db_connection):
    """
    VULNERABILITY: SQL Injection via string concatenation
    Line: 17 - Direct string concatenation in SQL query
    Severity: CRITICAL
    
    Impact: Attacker can inject arbitrary SQL code by crafting user_id
    Example attack: user_id = "1; DROP TABLE users; --"
    
    Fix: Use parameterized queries with placeholders
    """
    # VULNERABLE: Line 17-18
    query = "SELECT * FROM users WHERE id = " + user_id
    result = db_connection.execute(query)
    return result.fetchone()


def search_users_by_name(search_term: str, session: Session):
    """
    VULNERABILITY: SQL Injection via f-string in SQLAlchemy raw query
    Line: 28 - f-string in SQLAlchemy text() query
    Severity: CRITICAL
    
    Impact: Attacker controls SQL execution context
    Example attack: search_term = "admin' OR '1'='1"
    
    Fix: Use bound parameters with text()
    """
    # VULNERABLE: Line 28
    query = text(f"SELECT * FROM users WHERE name LIKE '%{search_term}%'")
    return session.execute(query).fetchall()


def authenticate_user(username: str, password: str, db_connection):
    """
    VULNERABILITY: SQL Injection in sqlite3 with f-string
    Line: 40 - f-string used to build SQL query
    Severity: CRITICAL
    
    Impact: Authentication bypass possible
    Example attack: username = "' OR 1=1 --"
    
    Fix: Always use parameterized queries with ? placeholders
    """
    # VULNERABLE: Line 40-41
    cursor = db_connection.cursor()
    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    cursor.execute(query)
    return cursor.fetchone()


def get_user_by_email(email: str, session: Session):
    """
    VULNERABILITY: SQLAlchemy text() with string formatting
    Line: 54 - Mixing text() with string format operations
    Severity: CRITICAL
    
    Impact: SQL injection through email parameter
    Example attack: email = "test'; DROP TABLE users; --@example.com"
    
    Fix: Use parameterized binding with :param syntax
    """
    # VULNERABLE: Line 54
    stmt = text(f"SELECT * FROM users WHERE email = '{email}'")
    return session.execute(stmt).scalar_one_or_none()


def filter_by_column(column_name: str, value: str, db_connection):
    """
    VULNERABILITY: SQL Injection via column name parameter
    Line: 67 - Untrusted column name in query
    Severity: HIGH
    
    Impact: Attacker can specify any column, potentially exposing data
    
    Fix: Use a whitelist of allowed column names
    """
    # VULNERABLE: Line 67-68
    cursor = db_connection.cursor()
    query = f"SELECT * FROM users WHERE {column_name} = ?"
    cursor.execute(query, (value,))
    return cursor.fetchall()


def update_user_profile(user_id: int, field_name: str, value: str, db_connection):
    """
    VULNERABILITY: SQL Injection in UPDATE statement via string concat
    Line: 82 - String concatenation in SET clause
    Severity: CRITICAL
    
    Impact: Attacker can modify arbitrary database fields
    Example attack: value = "'; UPDATE users SET admin=1; --"
    
    Fix: Use parameterized update with proper binding
    """
    # VULNERABLE: Line 82-83
    cursor = db_connection.cursor()
    query = f"UPDATE users SET {field_name} = '{value}' WHERE id = {user_id}"
    cursor.execute(query)
    db_connection.commit()


def fetch_by_status(status: str, db_connection):
    """
    VULNERABILITY: SQL Injection in WHERE clause via f-string
    Line: 97 - Direct string interpolation in WHERE
    Severity: CRITICAL
    
    Impact: Complete database breach possible
    
    Fix: Use parameterized queries with placeholders
    """
    # VULNERABLE: Line 97
    cursor = db_connection.cursor()
    query = f"SELECT * FROM articles WHERE status = '{status}'"
    cursor.execute(query)
    return cursor.fetchall()


def order_by_column(column: str, db_connection):
    """
    VULNERABILITY: SQL Injection in ORDER BY clause
    Line: 111 - Untrusted column in ORDER BY
    Severity: HIGH
    
    Impact: Can be used for data exfiltration via timing attacks
    
    Fix: Whitelist allowed ORDER BY columns
    """
    # VULNERABLE: Line 111
    cursor = db_connection.cursor()
    query = f"SELECT * FROM users ORDER BY {column}"
    cursor.execute(query)
    return cursor.fetchall()


def raw_sql_from_input(sql_fragment: str, session: Session):
    """
    VULNERABILITY: Directly executing user-supplied SQL
    Line: 125 - Complete SQL statement from user input
    Severity: CRITICAL
    
    Impact: Total database compromise
    
    Fix: Never accept arbitrary SQL from users; use ORM or whitelisted queries
    """
    # VULNERABLE: Line 125
    result = session.execute(text(sql_fragment))
    return result.fetchall()
