"""Tests for naming an act when several acts claim the same name.

The case is real and it is not rare: `hg-1-2016` is claimed by eighteen documents in the collected
corpus — a Government decision, one of the Senate, one of the Chamber, one of the Permanent
Electoral Authority, one of the College of Psychologists, one of the Central Requisitions
Commission, and twelve more. Every one is a genuine `Hotărâre nr. 1 din 2016`. Keying `acte` on the
citation deleted seventeen of them and their provisions with them, and the arithmetic of the loss
is exact: `count(documente) - count(acte) = 53 242`.
"""

from __future__ import annotations

from pathlib import Path

from scripts import depozit, omonime


def _act(con, id_portal: str, tip: str, numar: str, an: int, emitent: str, titlu: str = "T"):
    """Write one act the way `scrie_act` does, through the same id rule."""
    act_id = omonime.id_unic(
        con, cheie_citare=f"{tip}-{numar}-{an}", tip=tip, emitent=emitent, id_portal=id_portal
    )
    con.execute("DELETE FROM acte WHERE id = ?", (act_id,))
    con.execute(
        "INSERT INTO acte (id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
        " id_portal, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (act_id, f"{tip}-{numar}-{an}", tip, numar, an, titlu, emitent, None, id_portal, "x"),
    )
    return act_id


def _db(tmp_path: Path) -> Path:
    return tmp_path / "corpus.db"


def test_an_act_with_no_namesake_keeps_the_bare_citation_key(tmp_path):
    """The overwhelming majority of the corpus, and the reason nothing that already points at a
    bare key breaks — not the graph's edges, not a watchlist, not a shipped shard."""
    with depozit.deschide(_db(tmp_path)) as con:
        assert _act(con, "1", "lege", "98", 2016, "Parlamentul") == "lege-98-2016"


def test_the_issuer_a_bare_citation_means_keeps_the_bare_key(tmp_path):
    """`Hotărârea Guvernului nr. 1/2016` is what a reader writing `HG nr. 1/2016` means, whichever
    order the corpus happened to collect the eighteen namesakes in."""
    with depozit.deschide(_db(tmp_path)) as con:
        senat = _act(con, "10", "hg", "1", 2016, "Senatul")
        assert senat == "hg-1-2016", "primul venit ia cheia liberă"
        guvern = _act(con, "11", "hg", "1", 2016, "Guvernul")
        assert guvern == "hg-1-2016", "emitentul canonic ia cheia de la unul care nu e"


def test_the_displaced_act_is_not_deleted_it_is_renamed(tmp_path):
    """The whole point. The Senate's decision keeps its row under a qualified id instead of being
    removed to make room for the Government's."""
    with depozit.deschide(_db(tmp_path)) as con:
        _act(con, "10", "hg", "1", 2016, "Senatul")
        _act(con, "11", "hg", "1", 2016, "Guvernul")
        # Re-writing the Senate's act now that the bare key has moved on gives it its own id.
        senat = _act(con, "10", "hg", "1", 2016, "Senatul")
        assert senat == "hg-1-2016-10"
        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 2


def test_the_bare_key_never_changes_hands_between_two_non_canonical_claimants(tmp_path):
    """Otherwise which act `ordin-1-1995` names would depend on the order the corpus was collected
    in, and two runs over the same source would disagree."""
    with depozit.deschide(_db(tmp_path)) as con:
        assert _act(con, "1", "ordin", "1", 1995, "Ministerul Finanțelor") == "ordin-1-1995"
        al_doilea = _act(con, "2", "ordin", "1", 1995, "Ministerul Sănătății")
        assert al_doilea == "ordin-1-1995-2"
        al_treilea = _act(con, "3", "ordin", "1", 1995, "Ministerul Justiției")
        assert al_treilea == "ordin-1-1995-3"


def test_re_reading_a_document_returns_the_id_it_already_holds(tmp_path):
    """A re-collection must replace its own row rather than grow a second one beside it, and the
    corpus is re-collected constantly."""
    with depozit.deschide(_db(tmp_path)) as con:
        _act(con, "1", "ordin", "1", 1995, "Ministerul Finanțelor")
        _act(con, "2", "ordin", "1", 1995, "Ministerul Sănătății")
        for _ in range(3):
            assert _act(con, "2", "ordin", "1", 1995, "Ministerul Sănătății") == "ordin-1-1995-2"
        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 2


def test_two_acts_of_the_same_issuer_type_number_and_year_still_get_apart(tmp_path):
    """Not supposed to happen and it does: 8 316 documents share all four. Most are `rectificare`,
    whose number is that of the act they correct rather than one of their own."""
    with depozit.deschide(_db(tmp_path)) as con:
        unu = _act(con, "1", "rectificare", "741", 2009, "Ministerul Justiției")
        doi = _act(con, "2", "rectificare", "741", 2009, "Ministerul Justiției")
        trei = _act(con, "3", "rectificare", "741", 2009, "Ministerul Justiției")
        assert len({unu, doi, trei}) == 3
        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 3


def test_the_qualified_id_does_not_depend_on_how_the_issuer_is_spelled(tmp_path):
    """The service encodes its responses in a charset without `ș` and `ț` and emits `?` for both,
    so 113 910 documents — 55% of the corpus — carry `Ministerul Sănătă?ii` where the page says
    `Sănătății`. An id built from the name would change the day those are repaired, and every
    stored reference to it would dangle. The portal's own document id cannot."""
    with depozit.deschide(_db(tmp_path)) as con:
        _act(con, "1", "ordin", "1", 1995, "Ministerul Finanțelor")
        stricat = _act(con, "2", "ordin", "1", 1995, "Ministerul Sănătă?ii")
        con.execute("UPDATE acte SET emitent = ? WHERE id = ?", ("Ministerul Sănătății", stricat))
        reparat = _act(con, "2", "ordin", "1", 1995, "Ministerul Sănătății")
        assert reparat == stricat == "ordin-1-1995-2"


def test_the_candidates_are_ordered_by_what_a_citation_most_likely_means(tmp_path):
    """A reader following `HG nr. 1/2016` should land on the Government's, and be able to see that
    five other acts answer to the same name rather than be told there is one."""
    with depozit.deschide(_db(tmp_path)) as con:
        _act(con, "10", "hg", "1", 2016, "Senatul")
        _act(con, "11", "hg", "1", 2016, "Guvernul")
        _act(con, "10", "hg", "1", 2016, "Senatul")
        _act(con, "12", "hg", "1", 2016, "Colegiul Psihologilor din România")
        lista = omonime.candidati(con, "hg-1-2016")
        assert [r[5] for r in lista][0] == "Guvernul"
        assert len(lista) == 3
        assert omonime.rezolva(con, "hg-1-2016") == "hg-1-2016"


def test_a_key_no_act_claims_resolves_to_nothing_rather_than_to_something(tmp_path):
    with depozit.deschide(_db(tmp_path)) as con:
        assert omonime.rezolva(con, "lege-1-1800") is None
        assert omonime.candidati(con, "lege-1-1800") == []


def test_a_corpus_collected_before_the_column_existed_gains_it_filled(tmp_path):
    """`id` is the right backfill: every act stored under the old rule holds a bare key, and where
    several claimed one the survivor is the one that held it."""
    cale = _db(tmp_path)
    with depozit.deschide(cale) as con:
        con.execute(
            "INSERT INTO acte (id, tip, numar, an, titlu, emitent, id_portal, citit_la)"
            " VALUES ('lege-98-2016','lege','98',2016,'T','Parlamentul','1','x')",
        )
        con.execute("UPDATE acte SET cheie_citare = NULL")
        con.commit()
    with depozit.deschide(cale) as con:
        assert con.execute("SELECT cheie_citare FROM acte").fetchone()[0] == "lege-98-2016"


# --- recuperarea celor care și-au pierdut rândul --------------------------------------------


def _document(con, id_portal: str, tip: str, numar: str, an: int, emitent: str, text: str):
    con.execute(
        "INSERT OR REPLACE INTO documente (id_portal, cheie_act, tip, numar, an, titlu, emitent,"
        " vigoare, sursa_url, text, adus_la) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            id_portal,
            f"{tip}-{numar}-{an}",
            tip,
            numar,
            an,
            f"{tip.upper()} nr. {numar}/{an}",
            emitent,
            None,
            f"http://x/{id_portal}",
            text,
            "x",
        ),
    )


def test_the_documents_that_lost_their_act_row_get_one_back(tmp_path):
    """Nothing is refetched: `documente` is the archive and nothing deletes from it, so the text
    of all 53 242 is still there. Only the act row and the provisions were destroyed."""
    cale = _db(tmp_path)
    with depozit.deschide(cale) as con:
        _document(con, "111", "ordin", "1", 1995, "Ministerul Finanțelor", "text finanțe")
        _document(con, "222", "ordin", "1", 1995, "Ministerul Sănătății", "text sănătate")
        # The corpus as the old rule left it: one act row for two documents.
        _act(con, "111", "ordin", "1", 1995, "Ministerul Finanțelor")
        con.commit()

    r = omonime.recupereaza(cale, log=lambda *_: None)
    assert r == {"fara_act": 1, "recuperate": 1}

    with depozit.deschide(cale, readonly=True) as con:
        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 2
        assert omonime.rezolva(con, "ordin-1-1995") == "ordin-1-1995"
        texte = {r[0] for r in con.execute("SELECT text FROM provizii")}
        assert "text sănătate" in texte, "textul recuperat nu a ajuns în provizii"
        assert depozit.cauta(con, "sanatate", 5), "textul recuperat nu e căutabil"


def test_running_the_recovery_twice_adds_nothing(tmp_path):
    """It is a repair, not a collection: an act row is only ever added, never replaced."""
    cale = _db(tmp_path)
    with depozit.deschide(cale) as con:
        _document(con, "111", "ordin", "1", 1995, "Ministerul Finanțelor", "text finanțe")
        _document(con, "222", "ordin", "1", 1995, "Ministerul Sănătății", "text sănătate")
        _act(con, "111", "ordin", "1", 1995, "Ministerul Finanțelor")
        con.commit()
    omonime.recupereaza(cale, log=lambda *_: None)
    a_doua = omonime.recupereaza(cale, log=lambda *_: None)
    assert a_doua == {"fara_act": 0, "recuperate": 0}
    with depozit.deschide(cale, readonly=True) as con:
        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 2
        # One provision, not two: the surviving act was written by the helper without any, and the
        # repair adds text only for the document it recovered. It does not touch what is there.
        assert con.execute("SELECT count(*) FROM provizii").fetchone()[0] == 1
