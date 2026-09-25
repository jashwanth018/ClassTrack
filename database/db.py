import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database.db")

# Accept the real ClassTrack formats, including alphanumeric suffixes and lateral-entry roll numbers.
# The important rule is that we keep the full value as text and never generate missing numbers.
ROLL_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


class DatabaseConnection:
    """Small compatibility wrapper for SQLite and psycopg2 connections."""

    def __init__(self, connection: Any, is_postgres: bool):
        self.connection = connection
        self.is_postgres = is_postgres

    def _cursor(self) -> Any:
        if self.is_postgres:
            from psycopg2.extras import DictCursor

            return self.connection.cursor(cursor_factory=DictCursor)
        return self.connection.cursor()

    def _query(self, query: str) -> str:
        return query.replace("?", "%s") if self.is_postgres else query

    def execute(self, query: str, parameters: tuple = ()) -> Any:
        cursor = self._cursor()
        cursor.execute(self._query(query), parameters)
        return cursor

    def executemany(self, query: str, parameters: List[tuple]) -> Any:
        cursor = self._cursor()
        cursor.executemany(self._query(query), parameters)
        return cursor

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exception_type: Any, exception_value: Any, traceback: Any) -> None:
        try:
            if exception_type:
                self.rollback()
            else:
                self.commit()
        finally:
            self.close()


def get_connection() -> DatabaseConnection:
    """Create a connection for DATABASE_URL or the existing local SQLite file."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url == "PASTE_YOUR_NEON_CONNECTION_STRING_HERE":
        database_url = ""
    if database_url:
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires psycopg2-binary.") from exc
        return DatabaseConnection(psycopg2.connect(database_url), is_postgres=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return DatabaseConnection(connection, is_postgres=False)


def init_db() -> None:
    """Create the required SQLite tables if they do not already exist."""
    with get_connection() as connection:
        student_id_definition = "SERIAL PRIMARY KEY" if connection.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS students (
                id {student_id_definition},
                roll_number TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                display_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        if connection.is_postgres:
            student_column_rows = connection.execute(
                """
                SELECT column_name AS name
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'students'
                """
            ).fetchall()
        else:
            student_column_rows = connection.execute("PRAGMA table_info(students)").fetchall()
        student_columns = {row["name"] for row in student_column_rows}
        if "display_order" not in student_columns:
            connection.execute("ALTER TABLE students ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0")

        connection.execute(
            """
            UPDATE students
            SET display_order = id
            WHERE display_order = 0
            """
        )

        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS attendance (
                id {student_id_definition},
                attendance_date TEXT NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('present', 'absent')),
                UNIQUE(attendance_date, student_id),
                FOREIGN KEY(student_id) REFERENCES students(id)
            )
            """
        )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_attendance_date_student ON attendance(attendance_date, student_id)"
        )
        connection.commit()


def validate_roll_number(roll_number: str) -> bool:
    """Accept valid class roll numbers while preserving the raw text value."""
    if not roll_number or not isinstance(roll_number, str):
        return False

    cleaned = roll_number.strip()
    if not cleaned:
        return False

    if len(cleaned) < 4:
        return False

    if not ROLL_NUMBER_PATTERN.fullmatch(cleaned):
        return False

    # Roll numbers may contain letters in the tail (for example A0, C6), so we only require a letter somewhere.
    return any(ch.isalpha() for ch in cleaned)


def total_students() -> int:
    """Return the number of stored students."""
    with get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) as total FROM students").fetchone()
        return int(row["total"]) if row else 0


def get_students(search_term: str = "") -> List[sqlite3.Row]:
    """Fetch students, optionally filtered by full roll number, last two digits, or name."""
    query = "SELECT id, roll_number, name, display_order FROM students"
    params: List[str] = []

    normalized = (search_term or "").strip()
    if normalized:
        term = f"%{normalized}%"
        query += " WHERE LOWER(roll_number) LIKE LOWER(?) OR LOWER(name) LIKE LOWER(?)"
        params.extend([term, term])

        # Allow searches by last two digits as a convenient fallback.
        if len(normalized) >= 2 and normalized.isdigit():
            query += " OR SUBSTR(roll_number, -2) = ?"
            params.append(normalized)

        if re.fullmatch(r"\d{2}", normalized):
            query += " OR SUBSTR(roll_number, -2) = ?"
            params.append(normalized)

    with get_connection() as connection:
        query += " ORDER BY display_order ASC"
        return connection.execute(query, params).fetchall()


def insert_student(roll_number: str, name: str) -> None:
    """Insert a student if not already present. The roll_number column is unique."""
    with get_connection() as connection:
        next_order = connection.execute(
            "SELECT COALESCE(MAX(display_order), 0) + 1 AS next_order FROM students"
        ).fetchone()["next_order"]
        connection.execute(
            "INSERT INTO students (roll_number, name, display_order) VALUES (?, ?, ?)",
            (roll_number.strip(), name.strip(), next_order),
        )
        connection.commit()


def upsert_student(roll_number: str, name: str) -> bool:
    """Insert or update an existing student safely without creating duplicates."""
    cleaned_roll_number = roll_number.strip()
    cleaned_name = name.strip()

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id, name FROM students WHERE roll_number = ?",
            (cleaned_roll_number,),
        ).fetchone()

        if existing is None:
            next_order = connection.execute(
                "SELECT COALESCE(MAX(display_order), 0) + 1 AS next_order FROM students"
            ).fetchone()["next_order"]
            connection.execute(
                "INSERT INTO students (roll_number, name, display_order) VALUES (?, ?, ?)",
                (cleaned_roll_number, cleaned_name, next_order),
            )
            connection.commit()
            return True

        if existing["name"] != cleaned_name:
            connection.execute(
                "UPDATE students SET name = ? WHERE id = ?",
                (cleaned_name, existing["id"]),
            )
            connection.commit()

        return False


def import_students_from_excel(file_path: str) -> Tuple[bool, str, int]:
    """Replace the roster from a validated Excel file when attendance is absent."""
    try:
        import pandas as pd
    except ImportError:
        return False, "Excel import requires pandas to be installed.", 0

    if not file_path or not os.path.exists(file_path):
        return False, "Please select a valid Excel file.", 0

    try:
        dataframe = pd.read_excel(file_path)
    except Exception:
        return False, "Invalid Excel format.", 0

    dataframe = dataframe.dropna(how="all")
    if dataframe.empty:
        return False, "No student data found in the Excel file.", 0

    # Normalize common possible column names used in nominal rolls.
    columns = {str(column).strip().lower(): column for column in dataframe.columns}
    roll_column = None
    name_column = None

    for candidate in ["roll number", "roll_number", "rollno", "roll no", "rollnumber"]:
        if candidate in columns:
            roll_column = columns[candidate]
            break

    for candidate in ["name", "student name", "student_name", "studentname"]:
        if candidate in columns:
            name_column = columns[candidate]
            break

    if roll_column is None or name_column is None:
        return False, "Import failed: Excel must contain 'roll number' and 'name' columns.", 0

    imported_students = []
    seen_roll_numbers = set()

    for display_order, (row_index, row) in enumerate(dataframe.iterrows(), start=1):
        roll_value = row.get(roll_column)
        name_value = row.get(name_column)
        roll_number = str(roll_value).strip() if not pd.isna(roll_value) else ""
        student_name = str(name_value) if not pd.isna(name_value) else ""

        if not roll_number or not student_name.strip():
            return False, f"Missing required student information in row {int(row_index) + 2}.", 0

        if not validate_roll_number(roll_number):
            return False, f"Invalid roll number '{roll_number}' found in row {int(row_index) + 2}.", 0

        if roll_number in seen_roll_numbers:
            return False, "Import failed: Duplicate roll numbers found in the Excel file.", 0

        seen_roll_numbers.add(roll_number)
        imported_students.append((roll_number, student_name, display_order))

    if not imported_students:
        return False, "No student data found in the Excel file.", 0

    with get_connection() as connection:
        attendance_count = connection.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        if attendance_count:
            return (
                False,
                "Attendance records already exist. The nominal roll cannot be replaced automatically because existing attendance history must be preserved.",
                0,
            )

        try:
            connection.execute("BEGIN")
            connection.execute("DELETE FROM students")
            connection.executemany(
                "INSERT INTO students (roll_number, name, display_order) VALUES (?, ?, ?)",
                imported_students,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    imported_count = len(imported_students)
    return True, f"✓ Nominal roll imported successfully. {imported_count} students imported.", imported_count


def load_attendance_for_date(attendance_date: str) -> Dict[str, str]:
    """Return a mapping of student_id -> status for a specific date."""
    if not attendance_date:
        return {}

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT student_id, status FROM attendance WHERE attendance_date = ?",
            (attendance_date,),
        ).fetchall()

    return {str(row["student_id"]): row["status"] for row in rows}


def save_attendance_for_date(attendance_date: str, attendance_map: Dict[int, str]) -> Dict[str, int]:
    """Upsert attendance for every student on a date within a single SQLite transaction."""
    if not attendance_date:
        raise ValueError("A valid attendance date is required.")

    valid_statuses = {"present", "absent"}
    cleaned_map: Dict[int, str] = {}

    for student_id, status in attendance_map.items():
        student_id_int = int(student_id)
        status_value = str(status).strip().lower()

        if status_value not in valid_statuses:
            raise ValueError(f"Invalid attendance status for student {student_id_int}: {status}")

        cleaned_map[student_id_int] = status_value

    with get_connection() as connection:
        try:
            connection.execute("BEGIN")

            existing_student_ids = {
                row["id"]
                for row in connection.execute("SELECT id FROM students").fetchall()
            }

            for student_id in cleaned_map:
                if student_id not in existing_student_ids:
                    raise ValueError(f"Student ID {student_id} does not exist in the students table.")

            for student_id, status_value in cleaned_map.items():
                connection.execute(
                    """
                    INSERT INTO attendance (attendance_date, student_id, status)
                    VALUES (?, ?, ?)
                    ON CONFLICT(attendance_date, student_id)
                    DO UPDATE SET status = excluded.status
                    """,
                    (attendance_date, student_id, status_value),
                )

            connection.commit()
        except Exception:
            connection.rollback()
            raise

    total_students_count = total_students()
    present_count = 0
    absent_count = 0

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) as count FROM attendance WHERE attendance_date = ? GROUP BY status",
            (attendance_date,),
        ).fetchall()

    for row in rows:
        if row["status"] == "present":
            present_count = int(row["count"])
        elif row["status"] == "absent":
            absent_count = int(row["count"])

    absent_count = max(total_students_count - present_count, 0)
    return {
        "total": total_students_count,
        "present": present_count,
        "absent": absent_count,
    }


def get_attendance_summary(attendance_date: str) -> Dict[str, int]:
    """Return the summary counts for the selected date."""
    if not attendance_date:
        return {"total": 0, "present": 0, "absent": 0}

    total_count = total_students()
    present_count = 0

    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) as present_count FROM attendance WHERE attendance_date = ? AND status = 'present'",
            (attendance_date,),
        ).fetchone()
        if row:
            present_count = int(row["present_count"])

    absent_count = max(total_count - present_count, 0)
    return {
        "total": total_count,
        "present": present_count,
        "absent": absent_count,
    }


def get_dashboard_attendance(attendance_date: str) -> Dict[str, object]:
    """Return today's dashboard counts and whether attendance was recorded."""
    total_count = total_students()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS recorded_count,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_count,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_count
            FROM attendance
            WHERE attendance_date = ?
            """,
            (attendance_date,),
        ).fetchone()

    recorded = int(row["recorded_count"]) if row else 0
    present = int(row["present_count"] or 0) if row else 0
    absent = int(row["absent_count"] or 0) if row else 0
    percentage = round((present / total_count * 100) if recorded and total_count else 0, 2)
    return {
        "has_records": recorded > 0,
        "total": total_count,
        "present": present if recorded else 0,
        "absent": absent if recorded else 0,
        "percentage": percentage,
    }


def get_recent_attendance(limit: int = 5) -> List[Dict[str, object]]:
    """Return the latest recorded attendance dates and their dynamic counts."""
    total_count = total_students()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                attendance_date,
                COUNT(*) AS recorded_count,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_count
            FROM attendance
            GROUP BY attendance_date
            ORDER BY attendance_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    recent = []
    for row in rows:
        present = int(row["present_count"] or 0)
        recent.append(
            {
                "date": row["attendance_date"],
                "present": present,
                "total": total_count,
                "percentage": round((present / total_count * 100) if total_count else 0, 2),
            }
        )
    return recent


def get_attendance_records_for_date(attendance_date: str) -> List[sqlite3.Row]:
    """Return saved attendance joined to active students in nominal-roll order."""
    if not attendance_date:
        return []

    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                students.id,
                students.roll_number,
                students.name,
                students.display_order,
                attendance.status
            FROM attendance
            INNER JOIN students ON students.id = attendance.student_id
            WHERE attendance.attendance_date = ?
            ORDER BY students.display_order ASC
            """,
            (attendance_date,),
        ).fetchall()
