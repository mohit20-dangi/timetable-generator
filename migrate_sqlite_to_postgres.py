#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script

This script:
1. Reads data from your existing SQLite database (timetable.db)
2. Generates a PostgreSQL-compatible SQL dump file
3. The dump file can be used to initialize PostgreSQL in Docker

Usage:
    python migrate_sqlite_to_postgres.py [sqlite_db_path] [output_sql_file]

Example:
    python migrate_sqlite_to_postgres.py backend/timetable.db backend/init_postgres.sql
"""

import sqlite3
import sys
import os
from datetime import datetime
from typing import List, Tuple, Any


def get_sqlite_tables(conn: sqlite3.Connection) -> List[str]:
    """Get all table names from SQLite database."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'alembic_%';")
    return [row[0] for row in cursor.fetchall()]


def get_table_schema(conn: sqlite3.Connection, table: str) -> List[Tuple]:
    """Get column info for a table."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table});")
    return cursor.fetchall()


def get_table_data(conn: sqlite3.Connection, table: str) -> List[Tuple]:
    """Get all data from a table."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table};")
    return cursor.fetchall()


def sqlite_type_to_postgres(sqlite_type: str) -> str:
    """Convert SQLite type to PostgreSQL type."""
    type_map = {
        'INTEGER': 'INTEGER',
        'TEXT': 'TEXT',
        'REAL': 'DOUBLE PRECISION',
        'BLOB': 'BYTEA',
        'NUMERIC': 'NUMERIC',
        'BOOLEAN': 'BOOLEAN',
        'DATE': 'DATE',
        'DATETIME': 'TIMESTAMP',
        'TIMESTAMP': 'TIMESTAMP',
        'VARCHAR': 'VARCHAR',
        'CHAR': 'CHAR',
    }
    upper_type = sqlite_type.upper()
    for key, value in type_map.items():
        if key in upper_type:
            return value
    return 'TEXT'  # Default fallback


def generate_create_table(table: str, columns: List[Tuple]) -> str:
    """Generate CREATE TABLE statement for PostgreSQL."""
    lines = [f"CREATE TABLE IF NOT EXISTS {table} ("]
    col_defs = []
    primary_keys = []
    
    for col in columns:
        cid, name, ctype, notnull, default_val, pk = col
        pg_type = sqlite_type_to_postgres(ctype)
        col_def = f"    {name} {pg_type}"
        
        if notnull:
            col_def += " NOT NULL"
        if default_val is not None:
            # Handle default values
            if default_val.upper() in ('NULL', 'CURRENT_TIMESTAMP'):
                col_def += f" DEFAULT {default_val}"
            elif pg_type in ('INTEGER', 'BIGINT', 'SMALLINT'):
                col_def += f" DEFAULT {default_val}"
            elif pg_type in ('DOUBLE PRECISION', 'REAL', 'NUMERIC'):
                col_def += f" DEFAULT {default_val}"
            else:
                # Escape single quotes for text defaults
                escaped = str(default_val).replace("'", "''")
                col_def += f" DEFAULT '{escaped}'"
        if pk:
            primary_keys.append(name)
        col_defs.append(col_def)
    
    lines.append(",\n".join(col_defs))
    
    if primary_keys:
        lines.append(f",\n    PRIMARY KEY ({', '.join(primary_keys)})")
    
    lines.append("\n);")
    return "\n".join(lines)


def generate_insert_statements(table: str, columns: List[Tuple], rows: List[Tuple]) -> List[str]:
    """Generate INSERT statements for PostgreSQL."""
    if not rows:
        return []
    
    col_names = [col[1] for col in columns]
    col_list = ", ".join(col_names)
    
    statements = []
    for row in rows:
        values = []
        for i, val in enumerate(row):
            if val is None:
                values.append("NULL")
            elif isinstance(val, bool):
                values.append("TRUE" if val else "FALSE")
            elif isinstance(val, (int, float)):
                values.append(str(val))
            elif isinstance(val, bytes):
                # Handle BLOB/BYTEA
                hex_str = val.hex()
                values.append(f"decode('{hex_str}', 'hex')")
            else:
                # Escape single quotes
                escaped = str(val).replace("'", "''")
                values.append(f"'{escaped}'")
        val_list = ", ".join(values)
        statements.append(f"INSERT INTO {table} ({col_list}) VALUES ({val_list});")
    
    return statements


def migrate_sqlite_to_postgres(sqlite_path: str, output_path: str):
    """Main migration function."""
    print(f"Reading SQLite database: {sqlite_path}")
    
    if not os.path.exists(sqlite_path):
        print(f"Error: SQLite database not found at {sqlite_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    
    tables = get_sqlite_tables(conn)
    print(f"Found {len(tables)} tables: {', '.join(tables)}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # Write header
        f.write(f"-- PostgreSQL dump generated from SQLite\n")
        f.write(f"-- Source: {sqlite_path}\n")
        f.write(f"-- Generated: {datetime.now().isoformat()}\n")
        f.write(f"-- \n")
        f.write(f"-- To import: psql -U timetable -d timetable -f {os.path.basename(output_path)}\n\n")
        
        # Disable triggers and constraints during import
        f.write("SET session_replication_role = replica;\n\n")
        
        for table in tables:
            print(f"  Processing table: {table}...")
            columns = get_table_schema(conn, table)
            rows = get_table_data(conn, table)
            
            # Generate CREATE TABLE
            create_sql = generate_create_table(table, columns)
            f.write(f"{create_sql}\n\n")
            
            # Generate INSERT statements
            inserts = generate_insert_statements(table, columns, rows)
            if inserts:
                f.write(f"-- Data for table {table} ({len(inserts)} rows)\n")
                f.write("\n".join(inserts))
                f.write("\n\n")
        
        # Re-enable triggers and constraints
        f.write("SET session_replication_role = DEFAULT;\n")
        
        # Reset sequences for auto-increment columns
        f.write("\n-- Reset sequences for SERIAL/IDENTITY columns\n")
        for table in tables:
            columns = get_sqlite_schema(conn, table)
            for col in columns:
                if col[5]:  # primary key
                    col_name = col[1]
                    f.write(f"SELECT setval(pg_get_serial_sequence('{table}', '{col_name}'), COALESCE(MAX({col_name}), 1)) FROM {table};\n")
    
    conn.close()
    print(f"\nMigration complete! Output written to: {output_path}")
    print(f"File size: {os.path.getsize(output_path) / 1024:.1f} KB")


def get_sqlite_schema(conn: sqlite3.Connection, table: str) -> List[Tuple]:
    """Get column info for a table (alias for get_table_schema)."""
    return get_table_schema(conn, table)


if __name__ == "__main__":
    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else "backend/timetable.db"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "backend/init_postgres.sql"
    
    migrate_sqlite_to_postgres(sqlite_path, output_path)