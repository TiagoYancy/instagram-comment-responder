"""Testes da interface de linha de comando.

Bug real: `--mode` só era aceito ANTES do subcomando (`--mode auto demo`),
mas o natural é escrever `demo --mode auto`. Isso dava "unrecognized arguments".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.cli import main


def _roda(argv, capsys=None):
    try:
        return main(argv)
    except SystemExit as e:  # argparse erra assim
        return e.code


@pytest.mark.parametrize("argv", [
    ["--mode", "dry_run", "demo"],
    ["demo", "--mode", "dry_run"],
    ["demo", "--mode", "auto"],
    ["demo"],
])
def test_mode_aceito_nas_duas_posicoes(argv):
    """`demo --mode X` deve funcionar tanto quanto `--mode X demo`."""
    rc = _roda(argv)
    assert rc == 0, f"falhou para {argv}"


def test_mode_invalido_recusado():
    rc = _roda(["demo", "--mode", "banana"])
    assert rc != 0


def test_doctor_roda_sem_credencial():
    """Sem credencial, doctor deve sair com 1 (não explodir)."""
    rc = _roda(["doctor"])
    assert rc == 1


def test_doctor_aceita_mode():
    rc = _roda(["doctor", "--mode", "approve"])
    assert rc == 1


def test_comando_inexistente_falha():
    rc = _roda(["comando_que_nao_existe"])
    assert rc != 0


def test_sem_comando_falha():
    rc = _roda([])
    assert rc != 0


def test_queue_com_banco_vazio(tmp_path, monkeypatch):
    from ig_responder.config import Settings
    s = Settings.load()
    s.db_path = tmp_path / "vazio.sqlite3"
    monkeypatch.setattr(Settings, "load",
                        classmethod(lambda cls, env_file=None: s))
    rc = _roda(["queue"])
    assert rc == 0


def test_stats_com_banco_vazio(tmp_path, monkeypatch):
    from ig_responder.config import Settings
    s = Settings.load()
    s.db_path = tmp_path / "vazio2.sqlite3"
    monkeypatch.setattr(Settings, "load",
                        classmethod(lambda cls, env_file=None: s))
    rc = _roda(["stats"])
    assert rc == 0


def test_help_lista_todos_os_comandos(capsys):
    rc = _roda(["--help"])
    assert rc == 0
    saida = capsys.readouterr().out
    for cmd in ["doctor", "learn", "scan", "queue", "approve", "reject",
                "mode", "stats", "demo"]:
        assert cmd in saida, f"comando {cmd} não aparece no help"
