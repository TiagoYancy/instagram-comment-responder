"""Testes do núcleo: sentimento, persona, política, store e geração offline."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.config import ACTION_ESCALATE, ACTION_IGNORE, ACTION_REPLY, Settings
from ig_responder.generator import generate, personalize, template_reply
from ig_responder.persona import Persona, default_persona, learn_persona
from ig_responder.policy import (
    DECISION_AUTO_PUBLISH,
    DECISION_NEEDS_APPROVAL,
    DECISION_SKIP,
    decide,
)
from ig_responder.sentiment import classify
from ig_responder.store import Store


# ------------------------------------------------------------- sentimento
@pytest.mark.parametrize("texto,esperado", [
    ("Que verdade! Falou tudo, vou começar a cobrar o meu valor 👏👏", "elogio"),
    ("Vdd, eu sempre tive vergonha de cobrar mais", "concordancia"),
    ("Exatamente! Mais peças é mais trabalho", "concordancia"),
    ("Concordo plenamente", "concordancia"),
    ("de onde você é? qual cidade?", "pergunta"),
    ("como faço para parar de dar desconto?", "duvida"),
    ("Aconteceu comigo semana passada, a cliente levou 4 peças e pediu desconto. "
     "Aprendi a dizer não e hoje trabalho em paz no meu ateliê.", "experiencia"),
    ("GANHE DINHEIRO EM CASA!! clique aqui http://spam.example.com renda extra", "spam"),
    ("isso é papo de quem cobra caro, discordo totalmente", "critica"),
    ("👏👏👏", "concordancia"),
])
def test_classify(texto, esperado):
    r = classify(texto)
    assert r.label == esperado, f"{texto!r} -> {r.label} (esperado {esperado}); scores={r.scores}"


def test_classify_vazio():
    assert classify("").label == "outro"


def test_classify_confianca_range():
    for t in ["vdd", "falou tudo", "de onde você é?", "clique aqui http://x.com"]:
        c = classify(t).confidence
        assert 0.0 <= c <= 1.0


# ---------------------------------------------------------------- persona
def test_default_persona_tem_valores():
    p = default_persona()
    assert p.handle == "@amigodacostureira"
    assert p.usa_at_mencao is True
    assert len(p.valores) >= 5
    assert "experiencia" in p.exemplos


def test_persona_roundtrip(tmp_path):
    p = default_persona()
    out = p.save(tmp_path / "p.json")
    back = Persona.load(out)
    assert back.handle == p.handle
    assert back.emojis_favoritos == p.emojis_favoritos
    assert back.exemplos.keys() == p.exemplos.keys()


def test_learn_persona_de_corpus():
    corpus = [{
        "url": "x",
        "text": (
            "amigodacostureira\n \n1w\nCOSTUREIRA 👀\n"
            "seguidora_a\n \n1w\nConcordo plenamente!\nLike\nReply\n"
            "amigodacostureira\n \n1w\n"
            "@seguidora_a Concordo! O serviço tem valor e não pode ser tratado como favor. ❤️\n"
            "Like\nReply\n"
            "amigodacostureira\n \n1w\n"
            "@seguidora_b Exatamente! Mais peças representam mais tempo e mais responsabilidade.\n"
            "Like\nReply\n"
        ),
    }]
    p = learn_persona(corpus, handle="@amigodacostureira", base=Persona())
    assert p.usa_at_mencao is True
    assert p.tratamento == "você"
    assert p.comprimento_frase == "curta"
    assert "❤️" in p.emojis_favoritos


def test_system_prompt_contem_voz():
    sp = default_persona().system_prompt()
    assert "amigodacostureira" in sp
    assert "NUNCA" in sp
    assert '"texto"' in sp


# -------------------------------------------------------------- política
def _draft(sent="concordancia", conf=0.9, action=ACTION_REPLY, text="@x Tudo certo!"):
    from ig_responder.generator import Draft
    return Draft(comment_id="1", comment_text="c", author="x",
                 sentiment=sent, sentiment_confidence=0.9,
                 text=text, action=action, confidence=conf,
                 motivo="", engine="template")


def _settings(mode):
    s = Settings()
    s.approval_mode = mode
    s.min_confidence = 0.75
    return s


def test_dry_run_nunca_publica():
    d = decide(_draft(), _settings("dry_run"))
    assert d.kind == DECISION_SKIP


def test_approve_sempre_enfileira():
    d = decide(_draft(), _settings("approve"))
    assert d.kind == DECISION_NEEDS_APPROVAL


def test_auto_publica_alta_confianca():
    d = decide(_draft(), _settings("auto"))
    assert d.kind == DECISION_AUTO_PUBLISH


def test_auto_barra_baixa_confianca():
    d = decide(_draft(conf=0.5), _settings("auto"))
    assert d.kind == DECISION_NEEDS_APPROVAL


def test_auto_nunca_publica_critica():
    d = decide(_draft(sent="critica", action=ACTION_ESCALATE), _settings("auto"))
    assert d.kind == DECISION_NEEDS_APPROVAL


def test_spam_sempre_ignorado():
    for mode in ("auto", "approve", "dry_run"):
        d = decide(_draft(sent="spam", action=ACTION_IGNORE, text=""), _settings(mode))
        assert d.kind == DECISION_SKIP


def test_auto_barra_promessa_comercial():
    d = decide(_draft(text="@x te dou desconto de 50%"), _settings("auto"))
    assert d.kind == DECISION_NEEDS_APPROVAL


def test_auto_barra_texto_vazio():
    d = decide(_draft(text="   "), _settings("auto"))
    assert d.kind == DECISION_NEEDS_APPROVAL


# ------------------------------------------------------------ geração off
def test_template_reply_menciona_nome():
    s = Settings()
    s.llm_enabled = False
    sent = classify("Concordo plenamente")
    d = generate(default_persona(), sent, "maria.silva", "Concordo plenamente", s)
    d = personalize(d, default_persona(), "maria.silva")
    assert d.text.startswith("@maria.silva")
    assert d.action == ACTION_REPLY


def test_template_spam_nao_gera_texto():
    s = Settings()
    s.llm_enabled = False
    sent = classify("clique aqui http://spam.com ganhe dinheiro")
    d = generate(default_persona(), sent, "spammer", "clique aqui", s)
    assert d.action == ACTION_IGNORE
    assert d.text == ""


def test_critica_escala():
    s = Settings()
    s.llm_enabled = False
    sent = classify("discordo, papo furado de quem cobra caro")
    d = generate(default_persona(), sent, "alguem", "discordo", s)
    assert d.action == ACTION_ESCALATE


def test_personalize_nao_duplica_at():
    s = Settings()
    s.llm_enabled = False
    sent = classify("Vdd")
    d = generate(default_persona(), sent, "ana", "Vdd", s)
    d = personalize(d, default_persona(), "ana")
    d = personalize(d, default_persona(), "ana")
    assert d.text.count("@ana") == 1


# ----------------------------------------------------------------- store
def test_store_ciclo(tmp_path):
    st = Store(tmp_path / "t.sqlite3")
    from ig_responder.client import Comment
    c = Comment(id="c1", text="oi", username="ana", timestamp="2026-01-01T00:00:00+0000")
    st.save_comment(c, classify("oi"), media_id="m1")
    assert st.seen("c1") is True

    d = _draft()
    d.comment_id = "c1"
    from ig_responder.policy import Decision
    did = st.save_draft(d, Decision(DECISION_NEEDS_APPROVAL, "teste"), media_id="m1")
    assert did > 0
    assert len(st.pending()) == 1

    st.set_state(did, "rejected")
    assert len(st.pending()) == 0
    assert st.stats()["rejected"] == 1
    st.close()


def test_store_setting(tmp_path):
    st = Store(tmp_path / "t2.sqlite3")
    assert st.get_setting("approval_mode", "dry_run") == "dry_run"
    st.set_setting("approval_mode", "auto")
    assert st.get_setting("approval_mode") == "auto"
    st.close()


# ------------------------------------------------------------ config/modo
def test_modo_invalido_falha():
    s = Settings()
    s.approval_mode = "banana"
    with pytest.raises(ValueError):
        s.validate_mode()


def test_settings_load_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("IG_APPROVAL_MODE=auto\nIG_MIN_CONFIDENCE=0.9\n", encoding="utf-8")
    monkeypatch.delenv("IG_APPROVAL_MODE", raising=False)
    monkeypatch.delenv("IG_MIN_CONFIDENCE", raising=False)
    s = Settings.load(env)
    assert s.approval_mode == "auto"
    assert s.min_confidence == 0.9
