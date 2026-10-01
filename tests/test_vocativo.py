"""Testes da trava contra handle usado como vocativo.

O LLM às vezes escreve "@cliente_dificil Cliente difícil, ..." — repetir o
handle como se fosse o nome da pessoa soa robótico numa resposta pública.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.config import ACTION_REPLY
from ig_responder.generator import Draft, personalize
from ig_responder.persona import default_persona


def _draft(texto, author):
    return Draft(comment_id="1", comment_text="c", author=author,
                 sentiment="concordancia", sentiment_confidence=0.8,
                 text=texto, action=ACTION_REPLY, confidence=0.9,
                 motivo="", engine="llm")


P = default_persona()


@pytest.mark.parametrize("entrada,author,proibido", [
    ("@cliente_dificil Cliente difícil, é só uma costurinha, mas o serviço é o mesmo.",
     "cliente_dificil", "Cliente difícil"),
    ("@atelie_da_jo Atelie da jo, o serviço tem valor.",
     "atelie_da_jo", "Atelie da jo"),
    ("@costura_e_arte Costura e arte, obrigado!",
     "costura_e_arte", "Costura e arte"),
    ("@promo_br Promo br, ganhe dinheiro!",
     "promo_br", "Promo br"),
])
def test_handle_nao_vira_vocativo(entrada, author, proibido):
    d = personalize(_draft(entrada, author), P, author)
    assert proibido.lower() not in d.text.lower(), d.text
    assert d.text.startswith(f"@{author} ")


def test_mencao_simples_preservada():
    d = personalize(_draft("Exatamente! Mais peças é mais trabalho.", "ana"), P, "ana")
    assert d.text == "@ana Exatamente! Mais peças é mais trabalho."


def test_nome_proprio_mantido():
    """Um vocativo legítimo (nome de pessoa) deve sobreviver."""
    d = personalize(_draft("@joana.lima Joana, que relato importante! 👏", "joana.lima"),
                    P, "joana.lima")
    assert "Joana" in d.text
    assert d.text.startswith("@joana.lima ")


def test_nao_duplica_mencao():
    d = personalize(_draft("@ana Exatamente!", "ana"), P, "ana")
    assert d.text.count("@ana") == 1


def test_personalize_idempotente():
    d = _draft("@cliente_dificil Cliente difícil, o serviço é o mesmo.", "cliente_dificil")
    d = personalize(d, P, "cliente_dificil")
    primeira = d.text
    d = personalize(d, P, "cliente_dificil")
    assert d.text == primeira
