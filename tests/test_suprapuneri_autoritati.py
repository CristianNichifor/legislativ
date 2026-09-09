import pytest

from scripts.suprapuneri_autoritati import atributie_comparabila


def _text(autoritate="Ministerul Mediului", obiect="autorizațiile de mediu"):
    return f"{autoritate} emite {obiect}."


def test_different_named_authorities_same_action_object_and_evidence():
    a = atributie_comparabila(_text())
    b = atributie_comparabila(_text("Agenția Națională pentru Protecția Mediului"))
    assert a["cheie"] == b["cheie"]
    assert a["autoritate"] != b["autoritate"]
    assert a["text"] == _text()
    assert a["actiune"] == "emite"
    assert a["obiect"] == "autorizatiile de mediu"


@pytest.mark.parametrize(
    "text",
    [
        _text("Ministerul Mediului și Ministerul Economiei"),
        _text().replace("emite", "emite împreună cu Ministerul Economiei"),
        _text().replace("emite", "emite în colaborare cu Ministerul Economiei"),
        _text().replace("emite", "emite prin delegare"),
        _text().replace("emite", "poate emite"),
        _text().replace("emite", "nu emite"),
        _text("Autoritatea locală Brașov"),
        _text("Agenția Regională Brașov"),
        _text("Agenția pentru Mediu din Brașov"),
        _text("Autoritatea competentă"),
        _text("Autoritatea contractantă"),
        _text("Ministerul de resort"),
        _text().replace("emite", "va emite"),
        _text().replace("emite", "are atribuția de a emite"),
        _text("Solicitantul"),
        _text().replace("emite", "emite cu avizul Ministerului Economiei"),
        _text().replace("emite", "emite la propunerea Ministerului Economiei"),
        _text().replace("emite", "emite dacă sunt îndeplinite condițiile"),
        _text(obiect="autorizațiile prevăzute de prezenta lege"),
        _text(obiect="autorizațiile prevăzute la art. 3"),
        _text() + " Prin excepție, Agenția emite anumite autorizații.",
    ],
)
def test_joint_delegated_conditional_generic_and_local_roles_excluded(text):
    assert atributie_comparabila(text) is None


@pytest.mark.parametrize(
    "a,b",
    [
        (_text(), _text().replace("emite", "verifică")),
        (_text(), _text(obiect="autorizațiile de construire")),
        (
            _text(obiect="autorizațiile în județul Brașov"),
            _text(obiect="autorizațiile în județul Sibiu"),
        ),
        (_text(), _text(obiect="autorizațiile de mediu pentru instalații industriale")),
    ],
)
def test_different_actions_objects_and_territorial_scope_do_not_match(a, b):
    assert atributie_comparabila(a)["cheie"] != atributie_comparabila(b)["cheie"]


def test_article_headers_and_diacritics_preserve_identity():
    a = atributie_comparabila("Art. 3. - (1) " + _text())
    b = atributie_comparabila("Art. 9. - (2) " + _text().replace("ț", "t"))
    assert a["cheie"] == b["cheie"]
    assert a["autoritate"] == b["autoritate"]


def test_avizeaza_is_a_supported_action_not_a_joint_approval_clause():
    assert atributie_comparabila(_text().replace("emite", "avizează"))["actiune"] == "avizeaza"
