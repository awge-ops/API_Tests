import os
import re
import time
import requests
import pytest
from jsonschema import validate

BASE_URL = os.getenv("BASE_URL", "https://hr-challenge.dev.tapyou.com")
TIMEOUT = 10

users_schema = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "errorCode": {"type": "integer"},
        "errorMessage": {"anyOf": [{"type": "null"}, {"type": "string"}]},
        "result": {"type": "array", "items": {"type": "integer"}}
    },
    "required": ["success", "errorCode", "errorMessage", "result"]
}

user_schema = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "errorCode": {"type": "integer"},
        "errorMessage": {"anyOf": [{"type": "null"}, {"type": "string"}]},
        "result": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "gender": {"type": "string"},
                "age": {"type": "integer"},
                "city": {"type": "string"},
                "registrationDate": {"type": "string"}
            },
            "required": ["id", "name", "gender", "age", "city", "registrationDate"]
        }
    },
    "required": ["success", "errorCode", "errorMessage", "result"]
}


def _normalize(j):
    if "result" not in j and "idList" in j:
        return {
            "success": j.get("isSuccess", True),
            "errorCode": j.get("errorCode", 0),
            "errorMessage": j.get("errorMessage"),
            "result": j.get("idList"),
        }
    return j


def _normalize_user(j):
    if "result" not in j and "user" in j:
        return {
            "success": j.get("isSuccess", True),
            "errorCode": j.get("errorCode", 0),
            "errorMessage": j.get("errorMessage"),
            "result": j.get("user"),
        }
    return j


@pytest.fixture(scope="session")
def session():
    return requests.Session()


@pytest.fixture(scope="session")
def valid_ids(session):
    res_m = session.get(f"{BASE_URL}/api/test/users", params={"gender": "male"}, timeout=TIMEOUT)
    res_f = session.get(f"{BASE_URL}/api/test/users", params={"gender": "female"}, timeout=TIMEOUT)
    if res_m.status_code != 200 and res_f.status_code != 200:
        pytest.skip("Could not fetch user ids")
    ids = {"male": [], "female": []}
    if res_m.status_code == 200:
        ids["male"] = _normalize(res_m.json()).get("result") or []
    if res_f.status_code == 200:
        ids["female"] = _normalize(res_f.json()).get("result") or []
    return ids


@pytest.fixture(scope="session")
def any_valid_id(valid_ids):
    for gender in ("male", "female"):
        if valid_ids.get(gender):
            return valid_ids[gender][0]
    pytest.skip("No valid user ids available")


def test_users_male_ok(session):
    r = session.get(f"{BASE_URL}/api/test/users", params={"gender": "male"}, timeout=TIMEOUT)
    assert r.status_code == 200
    j = _normalize(r.json())
    validate(instance=j, schema=users_schema)
    assert j["success"] is True
    assert j["errorCode"] == 0
    assert j["errorMessage"] is None
    assert all(isinstance(i, int) and i >= 1 for i in j["result"])


def test_users_female_ok(session):
    r = session.get(f"{BASE_URL}/api/test/users", params={"gender": "female"}, timeout=TIMEOUT)
    assert r.status_code == 200
    j = _normalize(r.json())
    validate(instance=j, schema=users_schema)
    assert j["success"] is True
    assert j["errorCode"] == 0
    assert j["errorMessage"] is None
    assert all(isinstance(i, int) and i >= 1 for i in j["result"])


def test_users_no_gender(session):
    r = session.get(f"{BASE_URL}/api/test/users", timeout=TIMEOUT)
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        validate(instance=_normalize(r.json()), schema=users_schema)


def test_users_invalid_gender(session):
    r = session.get(f"{BASE_URL}/api/test/users", params={"gender": "abc"}, timeout=TIMEOUT)
    assert 400 <= r.status_code < 500


def test_users_case_and_trim(session):
    for value in ("Male", "MALE", " female "):
        r = session.get(f"{BASE_URL}/api/test/users", params={"gender": value}, timeout=TIMEOUT)
        assert r.status_code < 500


def test_user_valid(session, any_valid_id):
    r = session.get(f"{BASE_URL}/api/test/user/{any_valid_id}", timeout=TIMEOUT)
    assert r.status_code == 200
    j = _normalize_user(r.json())
    validate(instance=j, schema=user_schema)
    res = j["result"]
    assert res["id"] == any_valid_id
    assert res["name"].strip() != ""
    assert res["gender"].lower() in ("male", "female")
    assert res["age"] > 0


def test_user_nonexistent(session):
    r = session.get(f"{BASE_URL}/api/test/user/999999", timeout=TIMEOUT)
    assert 400 <= r.status_code < 500


def test_user_invalid_id(session):
    r = session.get(f"{BASE_URL}/api/test/user/abc", timeout=TIMEOUT)
    assert 400 <= r.status_code < 500


def test_user_edge_ids(session):
    for eid in ("0", "-1", "999999999"):
        r = session.get(f"{BASE_URL}/api/test/user/{eid}", timeout=TIMEOUT)
        assert r.status_code < 500


def test_registration_date_format(session, any_valid_id):
    r = session.get(f"{BASE_URL}/api/test/user/{any_valid_id}", timeout=TIMEOUT)
    j = _normalize_user(r.json())
    rd = j["result"]["registrationDate"]
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
    assert re.match(pattern, rd), f"Unexpected date format: {rd}"


def test_age_and_id_types(session, any_valid_id):
    r = session.get(f"{BASE_URL}/api/test/user/{any_valid_id}", timeout=TIMEOUT)
    j = _normalize_user(r.json())
    assert isinstance(j["result"]["id"], int)
    assert isinstance(j["result"]["age"], int) and j["result"]["age"] > 0


def test_cross_check_gender(session, valid_ids):
    if not valid_ids.get("female"):
        pytest.skip("No female ids available")
    for sid in valid_ids["female"][:5]:
        r = session.get(f"{BASE_URL}/api/test/user/{sid}", timeout=TIMEOUT)
        if r.status_code == 200:
            j = _normalize_user(r.json())
            assert j["result"]["gender"].lower() == "female"


def test_content_type_header(session):
    r = session.get(f"{BASE_URL}/api/test/users", params={"gender": "male"}, timeout=TIMEOUT)
    assert "application/json" in r.headers.get("Content-Type", "")


def test_response_time(session):
    times = []
    for _ in range(5):
        start = time.time()
        session.get(f"{BASE_URL}/api/test/users", params={"gender": "male"}, timeout=TIMEOUT)
        times.append(time.time() - start)
    assert max(times) < 5, f"Slow response: {max(times):.2f}s"


def test_sqli_xss_resilience(session):
    payloads = ["1;DROP TABLE users", "<script>alert(1)</script>", "' OR '1'='1"]
    for p in payloads:
        r1 = session.get(f"{BASE_URL}/api/test/user/{p}", timeout=TIMEOUT)
        r2 = session.get(f"{BASE_URL}/api/test/users", params={"gender": p}, timeout=TIMEOUT)
        assert r1.status_code < 500
        assert r2.status_code < 500


def test_json_schema_full(session):
    r = session.get(f"{BASE_URL}/api/test/users", params={"gender": "male"}, timeout=TIMEOUT)
    j = _normalize(r.json())
    validate(instance=j, schema=users_schema)
    if j["result"]:
        r2 = session.get(f"{BASE_URL}/api/test/user/{j['result'][0]}", timeout=TIMEOUT)
        validate(instance=_normalize_user(r2.json()), schema=user_schema)


def test_rate_limit_behavior(session):
    codes = [
        session.get(f"{BASE_URL}/api/test/users", params={"gender": "male"}, timeout=TIMEOUT).status_code
        for _ in range(20)
    ]
    assert all(c < 500 for c in codes)
