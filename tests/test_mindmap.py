"""Mind-map AI protocol and route regression tests."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from toolbox.api import api

mindmap = importlib.import_module("toolbox.tools.mindmap.router")

client = TestClient(api)


@pytest.fixture(autouse=True)
def _fresh_rate_limit_bucket():
    storage = getattr(mindmap.limiter, "_storage", None)
    if storage is not None:
        storage.reset()
    yield


def _body(**overrides):
    body = {
        "prompt": "整理一个发布计划",
        "operation": "replace",
        "template": "project-plan",
        "direction": "right",
        "compact": False,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "test-key-not-real",
    }
    body.update(overrides)
    return body


def test_templates_are_public_and_stable():
    response = client.get("/tools/mindmap/templates")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} >= {"project-plan", "swot", "course-outline"}


def test_replace_returns_safe_mind_elixir_data(monkeypatch):
    monkeypatch.setattr(
        mindmap,
        "_call_text_model",
        lambda *_args: json.dumps(
            {
                "title": "发布计划",
                "children": [
                    {"title": "准备", "tags": ["本周"]},
                    {"title": "上线", "note": "确认回滚方案"},
                ],
            }
        ),
    )

    response = client.post("/tools/mindmap/generate", json=_body())

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["direction"] == 1
    assert data["nodeData"]["topic"] == "发布计划"
    assert len(data["nodeData"]["children"]) == 2
    assert data["nodeData"]["children"][0]["id"].startswith("ai-")
    assert response.json()["node_count"] == 3


def test_append_only_adds_children_to_selected_node(monkeypatch):
    monkeypatch.setattr(
        mindmap,
        "_call_text_model",
        lambda *_args: '{"title":"新增内容","children":[{"title":"验收"}]}',
    )
    current = {
        "nodeData": {
            "id": "root",
            "topic": "项目",
            "children": [{"id": "tasks", "topic": "任务"}],
        }
    }

    response = client.post(
        "/tools/mindmap/generate",
        json=_body(operation="append", current_data=current, selected_node_id="tasks"),
    )

    assert response.status_code == 200, response.text
    root = response.json()["data"]["nodeData"]
    target = root["children"][0]
    assert target["id"] == "tasks"
    assert [child["topic"] for child in target["children"]] == ["验收"]
    assert root["id"] == "root"


def test_model_output_does_not_allow_arbitrary_fields(monkeypatch):
    monkeypatch.setattr(
        mindmap,
        "_call_text_model",
        lambda *_args: '{"title":"x","children":[],"style":{"color":"red"}}',
    )

    response = client.post("/tools/mindmap/generate", json=_body())

    assert response.status_code == 502
    assert "协议" in response.json()["detail"]


def test_model_output_fence_is_supported_but_invalid_json_is_not(monkeypatch):
    monkeypatch.setattr(mindmap, "_call_text_model", lambda *_args: "```json\nnot-json\n```")

    response = client.post("/tools/mindmap/generate", json=_body())

    assert response.status_code == 502
    assert "协议" in response.json()["detail"]


def test_append_requires_selected_node():
    response = client.post(
        "/tools/mindmap/generate",
        json=_body(
            operation="append",
            current_data={"nodeData": {"id": "root", "topic": "项目"}},
        ),
    )

    assert response.status_code == 422
    assert "selected_node_id" in response.json()["detail"]


def test_invalid_current_data_is_rejected_before_model_call(monkeypatch):
    called = False

    def should_not_run(*_args):
        nonlocal called
        called = True
        return '{"title":"x"}'

    monkeypatch.setattr(mindmap, "_call_text_model", should_not_run)
    response = client.post(
        "/tools/mindmap/generate",
        json=_body(operation="refine", current_data={"nodeData": {"id": "root", "topic": "<bad>"}}),
    )

    assert response.status_code == 422
    assert called is False


def test_api_key_is_not_in_upstream_error(monkeypatch):
    def fail(*_args):
        raise mindmap.HTTPException(502, "模型服务暂时不可用，请稍后重试。")

    monkeypatch.setattr(mindmap, "_call_text_model", fail)
    secret = "sk-test-secret-that-must-not-return"
    response = client.post("/tools/mindmap/generate", json=_body(api_key=secret))

    assert response.status_code == 502
    assert secret not in response.text
