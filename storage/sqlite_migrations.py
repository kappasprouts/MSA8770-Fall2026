"""Transactional upgrade of the fallback's applicant column contracts."""

import re
from decimal import Decimal

from storage.gpa_utils import parse_gpa


def migrate_applicant_contract(engine):
    # SQLite cannot ALTER a column's nullability/type. Preserve the original
    # table definition (including unknown columns/constraints), indexes and
    # triggers during the standard create/copy/drop/rename rebuild.
    raw = engine.raw_connection()
    cursor = raw.cursor()
    foreign_keys = cursor.execute("PRAGMA foreign_keys").fetchone()[0]
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN IMMEDIATE")
        original = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='applicants'").fetchone()[0]
        updated = original
        for name in ("admission_year", "admission_term"):
            updated = re.sub(
                rf'(\b{name}\b"?\s+(?:INTEGER|VARCHAR\s*\(\s*\d+\s*\)))\s+NOT\s+NULL',
                r'\1', updated, flags=re.IGNORECASE,
            )
        for name in ("unweighted_gpa", "weighted_gpa"):
            updated = re.sub(
                rf'\b{name}\b("?)\s+(?:NUMERIC\s*\([^)]*\)|FLOAT|REAL)',
                name + r'\1 NUMERIC(3, 2)', updated, flags=re.IGNORECASE,
            )
        if updated != original:
            extras = cursor.execute("SELECT sql FROM sqlite_master WHERE tbl_name='applicants' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
            create = re.sub(r'^CREATE TABLE\s+(?:"applicants"|applicants)',
                            'CREATE TABLE "_applicants_contract_upgrade"', updated, count=1, flags=re.IGNORECASE)
            if create == updated:
                raise ValueError("Cannot safely rebuild the legacy applicants table")
            cursor.execute(create)
            cursor.execute('INSERT INTO "_applicants_contract_upgrade" SELECT * FROM applicants')
            cursor.execute('DROP TABLE applicants')
            cursor.execute('ALTER TABLE "_applicants_contract_upgrade" RENAME TO applicants')
            for (sql,) in extras:
                cursor.execute(sql)
        columns = {row[1]: row for row in cursor.execute("PRAGMA table_info(applicants)")}
        for name in ("admission_year", "admission_term"):
            if name in columns and columns[name][3]:
                raise ValueError(f"Legacy {name} remained NOT NULL")
        for name in ("unweighted_gpa", "weighted_gpa"):
            if name in columns:
                for app_id, value in cursor.execute(f'SELECT app_id, {name} FROM applicants WHERE {name} IS NOT NULL').fetchall():
                    normalized = parse_gpa(value)
                    if normalized is None or abs(normalized) >= Decimal("10"):
                        raise ValueError(f"Cannot migrate {name} for {app_id} to NUMERIC(3,2)")
                    if normalized != Decimal(str(value)):
                        cursor.execute(f'UPDATE applicants SET {name}=? WHERE app_id=?',
                                       (str(normalized), app_id))
        if cursor.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Applicant migration found a foreign-key violation")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        cursor.execute(f"PRAGMA foreign_keys={foreign_keys}")
        cursor.close()
        raw.close()
