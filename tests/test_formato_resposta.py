"""Testes do formato de resposta observado na conta real.

Padrões confirmados em captura de tela do @costureira:
  - a resposta é encadeada (campo "Responder"), indentada sob o comentário
  - começa com @menção
  - parágrafo ÚNICO, sem quebra de linha
  - emoji no final, 1 a 2 no máximo
  - comentário curto de opinião -> resposta curta + pergunta que puxa conversa
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.config import ACTION_REPLY
from ig_responder.generator import Draft, personalize
from ig_responder.persona import default_persona

P = default_persona()


def _draft(texto, author="pizolatojozelia"):
    return Draft(comment_id="1", comment_text="c", author=author,
                 sentiment="concordancia", sentiment_confidence=0.8,
                 text=texto, action=ACTION_REPLY, confidence=0.9,
                 motivo="", engine="llm")


# ------------------------------------------------- exemplos reais da conta
EXEMPLOS_REAIS = [
    "@pizolatojozelia Falou uma coisa importantíssima! 🍑❤️",
    "@pizolatojozelia Você acha que a maior dificuldade da costureira é "
    "descobrir quanto cobrar ou ter coragem de manter o preço? 🎯",
]


@pytest.mark.parametrize("texto", EXEMPLOS_REAIS)
def test_exemplos_reais_preservados(texto):
    """Respostas reais do dono devem passar intactas pelo personalize."""
    d = personalize(_draft(texto), P, "pizolatojozelia")
    assert d.text == texto


def test_mencao_no_inicio():
    d = personalize(_draft("Exatamente! Mais peças é mais trabalho."), P, "ana")
    assert d.text.startswith("@ana ")


def test_paragrafo_unico_sem_quebra_de_linha():
    d = personalize(_draft("@ana Primeira linha.\nSegunda linha.\n\nTerceira."), P, "ana")
    assert "\n" not in d.text
    assert d.text == "@ana Primeira linha. Segunda linha. Terceira."


def test_emoji_no_final():
    # ❤️ = ❤ + U+FE0F (seletor de variação), então o final pode ter mais de um
    # code point. Aceita emoji seguido de eventuais seletores de variação.
    padrao = r"[🍑❤🎯✂👏\U0001F300-\U0001FAFF\U00002700-\U000027BF][\ufe0f\U0001F3FB-\U0001F3FF]*\s*$"
    for texto in EXEMPLOS_REAIS:
        d = personalize(_draft(texto), P, "pizolatojozelia")
        assert re.search(padrao, d.text), d.text


def test_sem_espacos_duplicados():
    d = personalize(_draft("@ana  Texto   com   espacos."), P, "ana")
    assert "  " not in d.text


def test_termina_com_pergunta_quando_puxa_conversa():
    d = personalize(
        _draft("@pizolatojozelia Você acha que a maior dificuldade da costureira "
               "é descobrir quanto cobrar ou ter coragem de manter o preço? 🎯"),
        P, "pizolatojozelia")
    assert "?" in d.text


# ---------------------------------------------------------- prompt da persona
def test_prompt_exige_mencao_e_paragrafo_unico():
    sp = P.system_prompt()
    assert "@handle <resposta>" in sp
    assert "quebra de linha" in sp.lower()
    assert "RESPOSTA do comentário" in sp


def test_prompt_inclui_cidade():
    assert "Ipatinga" in P.system_prompt()


def test_prompt_inclui_exemplos_reais_da_captura():
    sp = P.system_prompt()
    assert "importantíssima" in sp
    assert "manter o preço" in sp


def test_prompt_inclui_concordancia_curta():
    sp = P.system_prompt()
    assert "concordancia_curta" in sp
