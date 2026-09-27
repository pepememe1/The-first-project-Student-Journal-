"""
test_ota_signing.py — подпись OTA-бандла (аудит 22.09.2026, находка F-24).

Держится:
  • подпись и проверка `tools/sign_ota.py` сходятся, подмена версии или суммы — отказ;
  • общий образец (`web/tests/fixtures/ota-sig-fixture.json`) проверяется и здесь, и в JS —
    формула подписи одна на обе стороны;
  • `verify` судит ключами, ВШИТЫМИ в приложение: подпись другим ключом не проходит;
  • манифест с меткой BOM (его пишет PowerShell) читается;
  • ключ приложения соответствует закрытому ключу на машине выкладки — иначе выкладка
    подписывала бы тем, чего телефоны не примут. Пропуск — по отсутствию ПРЕДМЕТА: в CI и
    у Влада закрытого ключа нет и быть не должно.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: `verify_payload`, всегда отвечающий True, — краснеют
«подмена» и «чужой ключ»; чтение манифеста без utf-8-sig — краснеет «BOM».
"""
import base64
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sign_ota  # noqa: E402


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())
    spki = base64.b64encode(k.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    return pem, spki


def test_sign_and_verify_roundtrip_and_tampering():
    pem, spki = _keypair()
    sig = sign_ota.sign_payload(sign_ota.ota_payload("1.260927.1200", "AB" * 32), pem)
    assert sign_ota.verify_payload(sign_ota.ota_payload("1.260927.1200", "ab" * 32), sig, [spki])
    assert not sign_ota.verify_payload(sign_ota.ota_payload("1.260927.1201", "ab" * 32), sig, [spki])
    assert not sign_ota.verify_payload(sign_ota.ota_payload("1.260927.1200", "cd" * 32), sig, [spki])
    _pem2, other = _keypair()
    assert not sign_ota.verify_payload(sign_ota.ota_payload("1.260927.1200", "ab" * 32), sig, [other])


def test_shared_fixture_verifies_in_python_too():
    with open(os.path.join(ROOT, "web", "tests", "fixtures", "ota-sig-fixture.json"),
              encoding="utf-8") as fh:
        fx = json.load(fh)
    assert sign_ota.verify_payload(sign_ota.ota_payload(fx["version"], fx["checksum"]),
                                   fx["sig"], [fx["spki"]])


def test_manifest_written_by_powershell_with_bom_is_read(tmp_path):
    p = tmp_path / "latest.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"version": "1.2.3", "checksum": "aa"}).encode())
    assert sign_ota._read_manifest(str(p))["version"] == "1.2.3"


def test_app_key_list_rejects_a_foreign_signature(tmp_path):
    pem, _spki = _keypair()
    m = {"version": "1.260927.1200", "file": "x.zip", "checksum": "ab" * 32,
         "sig": sign_ota.sign_payload(sign_ota.ota_payload("1.260927.1200", "ab" * 32), pem)}
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    assert sign_ota.main(["sign_ota.py", "verify", str(p)]) == 1, \
        "манифест, подписанный чужим ключом, прошёл ворота выкладки"


def test_app_key_matches_the_private_key_on_the_release_machine():
    if not os.path.isfile(sign_ota.PRIVATE_KEY):
        pytest.skip("закрытого ключа OTA на этой машине нет (CI, чужая машина) — сверять не с чем")
    with open(sign_ota.PRIVATE_KEY, "rb") as fh:
        sig = sign_ota.sign_payload(b"probe", fh.read())
    assert sign_ota.verify_payload(b"probe", sig, sign_ota.public_keys()), \
        "ключ в web/src/config/ota-public-keys.json не от закрытого ключа машины выкладки"
