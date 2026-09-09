"""Dependency-free schema-9 DDL, owned by the dossier migration transaction."""


def migreaza(con):
    con.execute(
        "CREATE TABLE legaturi_ue (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "id TEXT NOT NULL UNIQUE, propunere_id TEXT NOT NULL REFERENCES propuneri(id), "
        "creat_la TEXT NOT NULL, cerere_json TEXT NOT NULL, rezultat_json TEXT NOT NULL)"
    )
    con.execute("CREATE INDEX legaturi_ue_propunere ON legaturi_ue(propunere_id,seq DESC)")
    for operation in ("UPDATE", "DELETE"):
        con.execute(
            f"CREATE TRIGGER legaturi_ue_no_{operation.lower()} BEFORE {operation} ON legaturi_ue "
            "BEGIN SELECT RAISE(ABORT,'EU links are append-only'); END"
        )
