# -*- coding: utf-8 -*-
"""Свойства CI и автодеплоя, которые не должны тихо разойтись (28.10.2026).

Разбор — тем же YAML, что у GitHub (pyyaml), а не поиском строк: «on» в YAML 1.1 читается
как True, и проверка подстрокой сказала бы «есть», не разобрав ничего.
"""
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, ".github", "workflows")


def _load(name):
    with open(os.path.join(WF, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_every_job_runs_on_a_pinned_image():
    #ubuntu-latest с 19.10.2026 переезжает на Ubuntu 26: CI покраснел бы без правки кода.
    for name in ("ci.yml", "uptime.yml"):
        for job, spec in _load(name)["jobs"].items():
            assert spec["runs-on"] != "ubuntu-latest", f"{name}:{job} на плавающем образе"


def test_deploy_waits_for_every_gate_and_only_for_release_pushes():
    jobs = _load("ci.yml")["jobs"]
    deploy = jobs["deploy"]
    #Новая проверка, добавленная в CI, обязана задерживать выкладку — иначе бой поедет
    #мимо неё. Исключение одно: SBOM — отчёт, а не проверка.
    gates = set(jobs) - {"deploy", "sbom"}
    assert gates <= set(deploy["needs"]), f"выкладка не ждёт: {gates - set(deploy['needs'])}"
    assert "push" in deploy["if"] and "Release-" in deploy["if"]
    assert deploy["environment"] == "production"
    assert deploy["concurrency"]["cancel-in-progress"] is False


def test_release_job_checks_the_stand_before_publishing_the_artifact():
    steps = _load("ci.yml")["jobs"]["release"]["steps"]
    runs = [s.get("run", "") for s in steps]
    stand = next(i for i, r in enumerate(runs) if "qa_stand.py --check" in r)
    upload = next(i for i, s in enumerate(steps) if "upload-artifact" in s.get("uses", ""))
    #Архив, который едет на бой, публикуется только после проверки ролей на стенде.
    assert stand < upload
