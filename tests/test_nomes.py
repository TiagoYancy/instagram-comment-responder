"""Testes de extração de nome/vocativo a partir de handles do Instagram."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.generator import _primeiro_nome


@pytest.mark.parametrize("handle,esperado", [
    # nome primeiro, sobrenome depois
    ("joana.lima", "Joana"),
    ("rosa.m_costuras_", "Rosa"),
    ("maria.silva", "Maria"),
    ("ana", "Ana"),
    # palavra de ateliê primeiro, nome depois
    ("atelie_maria", "Maria"),
    ("costureira_ana", "Ana"),
    ("atelierajustapramim", "Atelierajustapramim"),
    # com @ e dígitos
    ("@joana.lima1268", "Joana"),
    ("dianalima2022_", "Dianalima"),
    ("mariadaconceicao.santana.5203", "Mariadaconceicao"),
    # só genérico -> sem vocativo (melhor não inventar nome)
    ("atelie", ""),
    ("admiradora", ""),
    ("seguidora", ""),
    ("cliente", ""),
    ("", ""),
    ("___", ""),
])
def test_primeiro_nome(handle, esperado):
    assert _primeiro_nome(handle) == esperado


@pytest.mark.parametrize("handle", [
    "admiradora", "seguidora", "cliente", "amiga", "querida", "linda",
    "top", "perfeita", "gente",
])
def test_elogio_nao_vira_vocativo(handle):
    """'@admiradora Que bom, Admiradora!' soa robótico — não deve acontecer."""
    assert _primeiro_nome(handle) == ""


def test_template_sem_nome_nao_deixa_espaco_orfao():
    from ig_responder.generator import _formata
    tpl = "Obrigado, {nome}! Você entendeu a mensagem. ✂️"
    assert _formata(tpl, "Ana") == "Obrigado, Ana! Você entendeu a mensagem. ✂️"
    out = _formata(tpl, "")
    assert "{" not in out and "!" in out
    assert "  " not in out
    assert not out.startswith(",")


def test_primeiro_nome_nunca_quebra():
    """Nenhum handle plausível deve derrubar a função."""
    for h in ["@a", "1", "..", "a.b.c", "@@@", "x" * 300, "😀_ana"]:
        _primeiro_nome(h)  # não deve lançar
