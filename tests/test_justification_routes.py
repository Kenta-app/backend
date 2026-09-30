from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.justification_router import router


def test_public_justification_routes_are_read_only():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    generate = client.post(
        "/justifications/generate",
        json={"prediction_id": 1, "regenerate": True},
    )
    clear = client.delete("/justifications/cache")

    assert generate.status_code in {404, 405}
    assert clear.status_code in {404, 405}
    assert all(
        not (route.path == "/justifications/generate" and "POST" in route.methods)
        for route in app.routes
    )
    assert all(
        not (route.path == "/justifications/cache" and "DELETE" in route.methods)
        for route in app.routes
    )
