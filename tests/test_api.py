from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_and_metadata():
    home = client.get("/")
    assert home.status_code == 200
    assert "Virus Spillover Simulator" in home.text
    assert 'id="b0Input"' in home.text
    assert 'id="d0Input"' in home.text

    meta = client.get("/api/model")
    assert meta.status_code == 200
    payload = meta.json()
    assert payload["defaults"]["beta0"] == 5e-8
    assert payload["defaults"]["b0"] == 0.5
    assert payload["defaults"]["d0"] == 0.3
    assert payload["defaults"]["duration"] == 50.0
    assert payload["fixed"]["birth_rate_form"] == "b(theta) = b0"


def test_static_layer_png():
    response = client.get("/api/layer/Ks.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_simulate_default_payload():
    meta = client.get("/api/model").json()
    d = meta["defaults"]
    response = client.post(
        "/api/simulate",
        json={
            "D": d["D"],
            "beta0": d["beta0"],
            "beta1": d["beta1"],
            "b0": d["b0"],
            "d0": d["d0"],
            "optimum": d["optimum"],
            "duration": d["duration"],
            "frames": d["frames"],
            "seed": d["seed"],
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert len(result["frame_times"]) == d["frames"]
    assert result["poisson"]["realized_spillovers"] == len(result["clusters"])
    assert result["parameters"]["b0"] == d["b0"]
    assert result["parameters"]["d0"] == d["d0"]


def test_validation_errors_are_human_readable_strings():
    response = client.post(
        "/api/simulate",
        json={"duration": 60, "beta0": 2e-6},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "Duration" in detail
    assert "beta0" in detail
    assert "[object Object]" not in detail
