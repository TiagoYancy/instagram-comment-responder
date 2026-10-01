"""Testes de vocativo em casos difíceis observados na saída real do LLM.

Histórico de bugs encontrados rodando o pipeline de verdade:
  - "@admiradora Que bom que fez sentido, Admiradora!"  (handle = elogio)
  - "@cliente_dificil Dificil, me chama no direct"      (handle = adjetivo)
  - "@joana.lima Lima, que relato importante!"          (pegou o sobrenome)
  - "@costureira_ana Costureira, ..."                   (pegou o papel)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.generator import _primeiro_nome


@pytest.mark.parametrize("handle,esperado", [
    # nome próprio no início
    ("joana.lima", "Joana"),
    ("ana_paula", "Ana"),
    ("rosa.m_costuras_", "Rosa"),
    # prefixo de ateliê: o nome vem depois
    ("atelie_maria", "Maria"),
    ("costureira_ana", "Ana"),
    ("atelie_da_jo", "Jo"),
    ("atelier_rosa", "Rosa"),
    # handles que NÃO contêm nome próprio -> sem vocativo
    ("cliente_dificil", ""),
    ("admiradora", ""),
    ("cliente_chateada", ""),
    ("nova_costureira", ""),
    ("promo_br", ""),
    ("atelie", ""),
    ("costura_e_arte", ""),
    ("lais82185", "Lais"),
])
def test_vocativo_casos_reais(handle, esperado):
    assert _primeiro_nome(handle) == esperado


def test_handle_com_sobrenome_nao_pega_sobrenome():
    """'joana.lima' deve virar 'Joana', nunca 'Lima'."""
    assert _primeiro_nome("joana.lima") == "Joana"
    assert _primeiro_nome("mariadaconceicao.santana.5203") == "Mariadaconceicao"


def test_prefixo_atelie_pula_para_o_nome():
    assert _primeiro_nome("atelie_maria") == "Maria"
    assert _primeiro_nome("costureira_ana") == "Ana"


def test_sem_nome_proprio_retorna_vazio():
    """Melhor sem vocativo do que inventar um nome que soa robótico."""
    for h in ["cliente_dificil", "admiradora", "nova_costureira", "costura_e_arte"]:
        assert _primeiro_nome(h) == "", h
