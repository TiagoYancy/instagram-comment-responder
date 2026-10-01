"""Testes da precedência do modo de aprovação.

Bug real: `mode approve` gravava no banco, mas `scan` lia do .env e rodava em
`dry_run` — o usuário achava que estava aprovando e nada era publicado.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.cli import _load_settings
from ig_responder.config import Settings
from ig_responder.store import Store


def _ns(mode=None):
    return argparse.Namespace(mode=mode)


def test_modo_do_banco_vence_o_env(tmp_path, monkeypatch):
    s = Settings.load()
    s.db_path = tmp_path / "t.sqlite3"
    Store(s.db_path).set_setting("approval_mode", "approve")

    monkeypatch.setattr(Settings, "load",
                        classmethod(lambda cls, env_file=None: s))

    efetivo = _load_settings(_ns())
    assert efetivo.approval_mode == "approve", (
        "scan ignorou o modo salvo com `mode approve`")


def test_flag_mode_vence_o_banco(tmp_path, monkeypatch):
    s = Settings.load()
    s.db_path = tmp_path / "t.sqlite3"
    Store(s.db_path).set_setting("approval_mode", "approve")

    monkeypatch.setattr(Settings, "load",
                        classmethod(lambda cls, env_file=None: s))

    assert _load_settings(_ns("auto")).approval_mode == "auto"
    assert _load_settings(_ns("dry_run")).approval_mode == "dry_run"


def test_sem_modo_no_banco_usa_o_env(tmp_path, monkeypatch):
    s = Settings.load()
    s.db_path = tmp_path / "vazio.sqlite3"
    s.approval_mode = "dry_run"

    monkeypatch.setattr(Settings, "load",
                        classmethod(lambda cls, env_file=None: s))

    assert _load_settings(_ns()).approval_mode == "dry_run"


def test_modo_invalido_no_banco_nao_explode(tmp_path, monkeypatch):
    """Um valor corrompido no banco deve cair no padrão, não derrubar o scan."""
    s = Settings.load()
    s.db_path = tmp_path / "t2.sqlite3"
    s.approval_mode = "dry_run"
    Store(s.db_path).set_setting("approval_mode", "banana")

    monkeypatch.setattr(Settings, "load",
                        classmethod(lambda cls, env_file=None: s))

    with pytest.raises(ValueError):
        _load_settings(_ns())


def test_ciclo_mode_grava_e_le(tmp_path):
    s = Settings.load()
    s.db_path = tmp_path / "c.sqlite3"
    st = Store(s.db_path)

    from ig_responder.runner import Responder

    class Fake:
        configured = False

    r = Responder(s, store=st, client=Fake())
    ok, _ = r.set_mode("approve")
    assert ok
    assert st.get_setting("approval_mode") == "approve"
    assert r.s.approval_mode == "approve"
