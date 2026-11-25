import sqlite3
from typing import List, Optional
from models.entidades import Sede
from dao.database import DB_PATH_DEFAULT


class SedeDAO:
    def __init__(self, db_path: str = DB_PATH_DEFAULT):
        self.db_path = db_path

    def _conn(self):
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _fila_a_sede(row: sqlite3.Row) -> Sede:
        return Sede(
            id_sede=row["id_sede"],
            nombre=row["nombre"],
            direccion=row["direccion"],
            contacto=row["contacto"],
            horarios=row["horarios"],
            activa=bool(row["activa"]),
            comentarios=row["comentarios"] or ""
        )

    def crear(self, sede: Sede) -> None:
        with self._conn() as cx:
            cx.execute("""
                INSERT INTO sedes (id_sede, nombre, direccion, contacto, horarios, activa, comentarios)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sede.id_sede,
                sede.nombre,
                sede.direccion,
                sede.contacto,
                sede.horarios,
                1 if sede.activa else 0,
                sede.comentarios or ""
            ))

    def obtener_por_id(self, id_sede: str) -> Optional[Sede]:
        with self._conn() as cx:
            cx.row_factory = sqlite3.Row
            cur = cx.execute("SELECT * FROM sedes WHERE id_sede = ?", (id_sede,))
            row = cur.fetchone()
            if not row:
                return None
            return self._fila_a_sede(row)

    def listar(self) -> List[Sede]:
        with self._conn() as cx:
            cx.row_factory = sqlite3.Row
            cur = cx.execute("SELECT * FROM sedes ORDER BY id_sede")
            filas = cur.fetchall()
            return [self._fila_a_sede(row) for row in filas]

    def actualizar_estado(self, id_sede: str, activa: bool, comentarios: str = "") -> int:
        """Cambia el estado de la sede y su comentario (motivo de la baja; vacío si está activa)."""
        with self._conn() as cx:
            cur = cx.execute(
                "UPDATE sedes SET activa = ?, comentarios = ? WHERE id_sede = ?",
                (1 if activa else 0, comentarios or "", id_sede)
            )
            return cur.rowcount

    def eliminar(self, id_sede: str) -> int:
        with self._conn() as cx:
            cur = cx.execute("DELETE FROM sedes WHERE id_sede = ?", (id_sede,))
            return cur.rowcount
