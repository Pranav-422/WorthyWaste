"""The photo check (Step 2): does the photo show the material the collector selected?

Every test here uses the mock verifier, so nothing calls the network.
"""
import time

from app import adapters, fraud
from tests.conftest import (RAJU, broken_verifier, ids, new_request, photo, seen, verifier)


def send(client, cid, img, material="plastic", **extra):
    return new_request(client, cid, img, kg=12, material=material, **extra)


# ---------- The four verdicts ----------

def test_match_when_the_ai_agrees(client):
    collectors, _ = ids(client)
    with verifier(seen("plastic", 0.93, notes="Clear PET bottles", quantity="one full sack")):
        r = send(client, collectors["Sunita"]["id"], photo(101))
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["ai_verdict"] == "match"
    assert req["ai_material"] == "plastic" and req["ai_confidence"] == 0.93
    assert "one full sack" in req["ai_notes"]


def test_mismatch_warns_once_instead_of_sending(client):
    collectors, _ = ids(client)
    with verifier(seen("cardboard", 0.87)):
        r = send(client, collectors["Sunita"]["id"], photo(102))
    assert r.status_code == 409
    body = r.json()
    assert body["rule"] == "photo_mismatch"
    # The warning carries what the collector needs to hear: their choice and what the AI saw.
    assert body["evidence"]["chose"] == "plastic"
    assert body["evidence"]["material"] == "cardboard"
    assert body["evidence"]["confidence"] == 0.87
    assert body["evidence"]["chose_label_hi"] == "प्लास्टिक बोतल"


def test_low_confidence_is_uncertain_and_goes_through(client):
    collectors, _ = ids(client)
    with verifier(seen("cardboard", 0.55)):
        r = send(client, collectors["Sunita"]["id"], photo(103))
    assert r.status_code == 201, r.text
    assert r.json()["ai_verdict"] == "uncertain"


def test_mixed_load_is_uncertain_however_sure_the_ai_is(client):
    collectors, _ = ids(client)
    with verifier(seen("mixed", 0.99)):
        r = send(client, collectors["Sunita"]["id"], photo(104))
    assert r.status_code == 201, r.text
    assert r.json()["ai_verdict"] == "uncertain"


def test_no_verifier_means_unchecked(client):
    collectors, _ = ids(client)
    with verifier(None):
        r = send(client, collectors["Sunita"]["id"], photo(105))
    assert r.status_code == 201, r.text
    assert r.json()["ai_verdict"] == "unchecked" and r.json()["ai_material"] is None


def test_photo_of_a_screen_is_a_mismatch(client):
    collectors, _ = ids(client)
    with verifier(seen("plastic", 0.95, real_scene=False, notes="Looks like a phone screen")):
        r = send(client, collectors["Sunita"]["id"], photo(106))
    assert r.status_code == 409 and r.json()["rule"] == "photo_mismatch"
    assert r.json()["evidence"]["real_scene"] is False


def test_not_scrap_is_a_mismatch(client):
    collectors, _ = ids(client)
    with verifier(seen("not_scrap", 0.9)):
        r = send(client, collectors["Sunita"]["id"], photo(107))
    assert r.status_code == 409 and r.json()["rule"] == "photo_mismatch"


# ---------- Never hard-block a collector on an AI guess ----------

def test_send_anyway_records_the_mismatch_without_blocking(client):
    collectors, _ = ids(client)
    img = photo(108)
    with verifier(seen("cardboard", 0.91)):
        assert send(client, collectors["Lakshmi"]["id"], img).status_code == 409
        r = send(client, collectors["Lakshmi"]["id"], img, confirm_mismatch=True)
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["ai_verdict"] == "mismatch" and req["material"] == "plastic"
    assert req["ai_material"] == "cardboard"
    # One mismatch is recorded, not flagged.
    flags = [f for f in client.get("/api/flags").json()
             if f["rule"] == "photo_mismatch" and f["collector_id"] == collectors["Lakshmi"]["id"]]
    assert flags == []


def test_verifier_timeout_leaves_the_sale_unchecked(client):
    collectors, _ = ids(client)
    with broken_verifier(TimeoutError("read timed out")):
        r = send(client, collectors["Sunita"]["id"], photo(109))
    assert r.status_code == 201, r.text
    assert r.json()["ai_verdict"] == "unchecked"
    assert "TimeoutError" in r.json()["ai_notes"]


def test_verifier_crash_leaves_the_sale_unchecked(client):
    collectors, _ = ids(client)
    with broken_verifier(RuntimeError("provider exploded")):
        r = send(client, collectors["Sunita"]["id"], photo(110))
    assert r.status_code == 201, r.text
    assert r.json()["ai_verdict"] == "unchecked"


# ---------- Three mismatches in seven days hold eligibility ----------

def test_three_mismatches_in_seven_days_hold_the_loan(client):
    collectors, _ = ids(client)
    meena = collectors["Meena"]["id"]
    assert client.get(f"/api/collectors/{meena}").json()["eligibility"]["eligible"]
    with verifier(seen("cardboard", 0.9)):
        for i in range(3):
            r = send(client, meena, photo(120 + i), confirm_mismatch=True)
            assert r.status_code == 201, r.text
    assert fraud.PHOTO_MISMATCH_REPEATS == 3
    flags = [f for f in client.get("/api/flags?status=open").json()
             if f["rule"] == "photo_mismatch" and f["collector_id"] == meena]
    assert len(flags) == 1, flags
    assert "3 sales in 7 days" in flags[0]["detail"]
    assert flags[0]["evidence"]["photo_url"].startswith("/api/photos/")

    el = client.get(f"/api/collectors/{meena}").json()["eligibility"]
    review = next(c for c in el["checks"] if c["key"] == "review")
    assert not el["eligible"] and not review["ok"] and "photo mismatch" in review["detail"]


# ---------- The dealer has the last word on the material ----------

def test_dealer_override_changes_the_material_and_the_amount(client):
    collectors, dealers = ids(client)
    sunita, raju = collectors["Sunita"], dealers["Raju"]
    with verifier(seen("cardboard", 0.95)):
        req = send(client, sunita["id"], photo(130), confirm_mismatch=True).json()
    client.post(f"/api/requests/{req['id']}/accept",
                json={"dealer_id": raju["id"], "qr_token": sunita["qr_token"],
                      "lat": RAJU[0], "lng": RAJU[1]})
    w = client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]}).json()
    # Weighed as plastic (the collector's choice) at ₹12.4/kg…
    assert w["material"] == "plastic" and w["rate_per_kg"] == 12.4
    plastic_amount = w["amount"]

    # …but the dealer confirms cardboard at ₹9/kg, and that is what gets paid and recorded.
    a = client.post(f"/api/requests/{req['id']}/approve",
                    json={"dealer_id": raju["id"], "material": "cardboard"})
    assert a.status_code == 200, a.text
    cardboard_amount = a.json()["payment"]["amount"]
    assert cardboard_amount == round(w["scale_kg"] * 9.0)
    assert cardboard_amount < plastic_amount

    for _ in range(30):
        got = client.get(f"/api/requests/{req['id']}").json()
        if got["transaction"]:
            break
        time.sleep(0.1)
    tx = got["transaction"]
    assert tx["material"] == "cardboard" and tx["rate_per_kg"] == 9.0
    assert tx["amount"] == cardboard_amount
    assert got["request"]["dealer_material"] == "cardboard"

    # The batch the kilos went into is a cardboard batch, so the trace stays honest.
    batch = client.get(f"/api/dealers/{raju['id']}").json()["open_batches"]
    assert any(b["id"] == tx["batch_id"] and b["material"] == "cardboard" for b in batch)

    # And Satin gets a card about the disagreement, which holds the collector's eligibility.
    flag = next(f for f in client.get("/api/flags?status=open").json()
                if f["rule"] == "photo_mismatch" and f["evidence"].get("request_id") == req["id"])
    assert flag["evidence"]["chose"] == "plastic"
    assert flag["evidence"]["dealer_material"] == "cardboard"
    assert flag["evidence"]["ai_material"] == "cardboard"
    assert "not the plastic the collector chose" in flag["detail"]


def test_dealer_confirming_the_same_material_raises_nothing(client):
    collectors, dealers = ids(client)
    farida, raju = collectors["Farida"], dealers["Raju"]
    before = len([f for f in client.get("/api/flags").json() if f["rule"] == "photo_mismatch"])
    with verifier(seen("plastic", 0.9)):
        req = send(client, farida["id"], photo(140)).json()
    client.post(f"/api/requests/{req['id']}/accept",
                json={"dealer_id": raju["id"], "qr_token": farida["qr_token"],
                      "lat": RAJU[0], "lng": RAJU[1]})
    client.post(f"/api/requests/{req['id']}/weigh", json={"dealer_id": raju["id"]})
    client.post(f"/api/requests/{req['id']}/approve",
                json={"dealer_id": raju["id"], "material": "plastic"})
    for _ in range(30):
        if client.get(f"/api/requests/{req['id']}").json()["transaction"]:
            break
        time.sleep(0.1)
    after = len([f for f in client.get("/api/flags").json() if f["rule"] == "photo_mismatch"])
    assert after == before


# ---------- Verdict rules, without a database ----------

def test_verdict_table():
    v = lambda chose, check: fraud.photo_verdict(chose, check)["verdict"]  # noqa: E731
    assert v("plastic", seen("plastic", 0.80)) == "match"          # exactly at the threshold
    assert v("plastic", seen("plastic", 0.79)) == "uncertain"
    assert v("plastic", seen("cardboard", 0.80)) == "mismatch"
    assert v("plastic", seen("cardboard", 0.79)) == "uncertain"
    assert v("plastic", seen("mixed", 1.0)) == "uncertain"
    assert v("plastic", seen("not_scrap", 0.1)) == "mismatch"      # confidence doesn't rescue it
    assert v("plastic", seen("plastic", 1.0, real_scene=False)) == "mismatch"
    assert v("plastic", seen("plastic", 0.9, real_scene=None)) == "match"
    assert v("plastic", adapters.PhotoCheck.unavailable("no key")) == "unchecked"


def test_reencoding_drops_exif_gps():
    import io

    from PIL import Image

    buf = io.BytesIO()
    img = Image.new("RGB", (2000, 1200), (120, 140, 90))
    exif = Image.Exif()
    exif[0x010F] = "DemoPhone"                       # Make
    gps = exif.get_ifd(0x8825)                       # GPSInfo, as a phone camera writes it
    gps[1], gps[2] = "N", (28.0, 40.0, 0.0)
    img.save(buf, "JPEG", exif=exif)
    original = buf.getvalue()
    assert Image.open(io.BytesIO(original)).getexif(), "test fixture should carry EXIF"

    clean = adapters.reencode_jpeg(original)
    out = Image.open(io.BytesIO(clean))
    assert dict(out.getexif()) == {}
    assert max(out.size) == adapters.PHOTO_MAX_EDGE
    assert clean[:2] == bytes([0xFF, 0xD8])


def test_gemini_parsing_degrades_to_unchecked():
    parse = adapters.GeminiPhotoVerifier._parse
    good = parse({"steps": [{"content": [{"type": "text", "text":
        '{"material":"metal","confidence":0.72,"real_scene":true,"notes":"tin cans"}'}]}]})
    assert good.available and good.material == "metal" and good.confidence == 0.72
    assert parse({"interaction": {"output_text": '{"material":"paper","confidence":1,'
                                                 '"real_scene":true}'}}).material == "paper"
    assert not parse({"output_text": "Sorry, I cannot help with that."}).available
    assert not parse({"output_text": '{"material":"unobtainium","confidence":0.9}'}).available
    assert not parse({"output_text": '{"material":"paper","confidence":"very"}'}).available
    assert not parse({}).available
    # Out-of-range confidence is clamped rather than thrown away.
    assert parse({"output_text": '{"material":"glass","confidence":4,"real_scene":true}'}).confidence == 1.0
