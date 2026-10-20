import pytest

from rankloom import security

# RFC 6238 appendix B, SHA-1 key "12345678901234567890"; the 8-digit codes cut to 6.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
RFC_VECTORS = [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
]


@pytest.mark.parametrize(("at", "code"), RFC_VECTORS)
def test_totp_matches_rfc_6238(at, code):
    assert security.hotp(RFC_SECRET, security.totp_step(at)) == code
    assert security.verify_totp(RFC_SECRET, code, at=at) == security.totp_step(at)


def test_totp_accepts_one_step_of_clock_drift_and_no_more():
    at = 1_700_000_000
    step = security.totp_step(at)
    assert security.verify_totp(RFC_SECRET, security.hotp(RFC_SECRET, step - 1), at=at)
    assert security.verify_totp(RFC_SECRET, security.hotp(RFC_SECRET, step + 1), at=at)
    assert security.verify_totp(RFC_SECRET, security.hotp(RFC_SECRET, step - 2), at=at) is None


def test_totp_refuses_a_replayed_code():
    at = 1_700_000_000
    code = security.hotp(RFC_SECRET, security.totp_step(at))
    used = security.verify_totp(RFC_SECRET, code, at=at)
    assert used is not None
    assert security.verify_totp(RFC_SECRET, code, last_step=used, at=at) is None


def test_totp_ignores_spaces_and_rejects_short_codes():
    at = 59
    assert security.verify_totp(RFC_SECRET, "287 082", at=at)
    assert security.verify_totp(RFC_SECRET, "28708", at=at) is None


def test_password_round_trip_and_unique_salts():
    a = security.hash_password("correct horse battery")
    b = security.hash_password("correct horse battery")
    assert a != b
    assert security.verify_password("correct horse battery", a)
    assert not security.verify_password("correct horse batterz", a)
    assert not security.verify_password("x", "not-a-hash")


@pytest.mark.parametrize(
    ("pw", "email", "refused"),
    [
        ("short", "", True),
        ("password123", "", True),
        ("aaaaaaaaaaaa", "", True),
        ("hammas-is-great", "hammas@example.com", True),
        ("diegoreviewer1", "diego.reviewer@example.com", True),
        ("Diego-Reviewer!", "diego.reviewer@example.com", True),
        ("tall-orange-river-42", "a@b.co", False),
    ],
)
def test_password_policy(pw, email, refused):
    assert (security.password_problem(pw, email) is not None) is refused


def test_sealed_box_round_trip_and_tamper_detection():
    box = security.SealedBox(b"k" * 32)
    blob = box.seal("ghp_secret_token_value")
    assert b"ghp_secret" not in blob
    assert box.open(blob) == "ghp_secret_token_value"
    flipped = blob[:20] + bytes([blob[20] ^ 1]) + blob[21:]
    with pytest.raises(ValueError):
        box.open(flipped)
    with pytest.raises(ValueError):
        security.SealedBox(b"q" * 32).open(blob)


def test_sealing_twice_gives_different_ciphertexts():
    box = security.SealedBox(b"k" * 32)
    assert box.seal("same") != box.seal("same")


def test_recovery_codes_are_unique_and_hash_case_insensitively():
    codes = security.new_recovery_codes()
    assert len(set(codes)) == 10
    assert security.recovery_hash(codes[0].upper()) == security.recovery_hash(codes[0])


def test_otpauth_uri_names_issuer_and_account():
    uri = security.otpauth_uri("ABC", "me@example.com")
    assert uri.startswith("otpauth://totp/Rankloom%3Ame%40example.com?secret=ABC")
    assert "issuer=Rankloom" in uri
