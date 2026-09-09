"""Web provider/model management routes.

Mutating endpoints are included under the same Web router, so public deployments inherit
existing authentication and exact-Origin CSRF middleware from ``llm_loop.web``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from .schemas import (
    ProviderCreateRequest,
    ProviderCredentialRequest,
    ProviderDefaultModelRequest,
    ProviderModelMutationRequest,
    ProviderReplaceRequest,
    ProviderTestRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()
UTF8JSONResponse = JSONResponse


def _engine_from(request: Request) -> Any:
    return request.app.state.engine

def _provider_admin_error(exc: Exception) -> Response:
    from .provider_admin import ProviderAdminError

    if isinstance(exc, ProviderAdminError):
        return UTF8JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "detail": exc.detail},
        )
    logger.exception("provider admin unexpected failure")
    return UTF8JSONResponse(
        status_code=500,
        content={"error": "provider_admin_failed", "detail": f"Provider 管理失败：{type(exc).__name__}"},
    )


def _provider_input_to_raw(provider: Any) -> tuple[str, dict[str, Any]]:
    payload = provider.model_dump(exclude_none=True)
    pid = str(payload.pop("id"))
    models = payload.pop("models", [])
    model_map: dict[str, Any] = {}
    for model in models:
        item = dict(model)
        mid = str(item.pop("id"))
        model_map[mid] = item
    payload["models"] = model_map
    return pid, payload


def _model_input_to_raw(model: Any) -> tuple[str, dict[str, Any]]:
    payload = model.model_dump(exclude_none=True)
    mid = str(payload.pop("id"))
    return mid, payload


@router.get("/api/v1/providers")
def provider_admin_list(request: Request) -> Response:
    """Return provider/model config facts without credential plaintext."""
    from . import provider_admin

    try:
        return UTF8JSONResponse(content=provider_admin.snapshot(_engine_from(request)))
    except Exception as exc:  # noqa: BLE001 - mapped to bounded admin error
        return _provider_admin_error(exc)


@router.post("/api/v1/providers")
def provider_admin_create(body: ProviderCreateRequest, request: Request) -> Response:
    from . import provider_admin

    engine = _engine_from(request)
    pid, raw = _provider_input_to_raw(body.provider)
    secret = body.api_key.get_secret_value() if body.api_key is not None else None
    if secret is not None and not raw.get("api_key_env"):
        raw["api_key_env"] = provider_admin.generated_api_key_env(pid)
    try:
        def _create(config: dict[str, Any]) -> None:
            if pid in config:
                raise provider_admin.ProviderAdminError(
                    "provider_exists", f"Provider 已存在：{pid}", status_code=409
                )
            config[pid] = raw

        result = provider_admin.mutate(
            engine, expected_version=body.expected_version, change=_create
        )
        # Credential write is intentionally separate from provider JSON. If it fails,
        # the provider remains truthfully visible as credential missing and the error
        # is returned; no secret ever enters provider JSON.
        if secret is not None:
            result = provider_admin.set_credential(engine, pid, secret)
        return UTF8JSONResponse(content=result, status_code=201)
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.put("/api/v1/providers/{provider_id}")
def provider_admin_replace(
    provider_id: str, body: ProviderReplaceRequest, request: Request
) -> Response:
    from . import provider_admin

    engine = _engine_from(request)
    pid, raw = _provider_input_to_raw(body.provider)
    if pid != provider_id:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "provider_id_mismatch", "detail": "路径 provider_id 与 body.id 必须一致。"},
        )
    try:
        configured = provider_admin.snapshot(engine).get("configured_default_model", "")
        if not bool(raw.get("enabled", True)) and str(configured).startswith(provider_id + "/"):
            raise provider_admin.ProviderAdminError(
                "default_provider_cannot_disable",
                "该 Provider 当前被配置为全局默认模型来源；请先切换默认模型。",
                status_code=409,
            )

        def _replace(config: dict[str, Any]) -> None:
            if provider_id not in config:
                raise provider_admin.ProviderAdminError(
                    "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
                )
            config[provider_id] = raw

        return UTF8JSONResponse(
            content=provider_admin.mutate(
                engine, expected_version=body.expected_version, change=_replace
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.delete("/api/v1/providers/{provider_id}")
def provider_admin_delete(
    provider_id: str,
    request: Request,
    expected_version: str = Query(min_length=1, max_length=128),
    confirm: bool = Query(default=False),
) -> Response:
    from . import provider_admin

    if not confirm:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "confirm_required", "detail": "删除 Provider 需 confirm=true。"},
        )
    engine = _engine_from(request)
    try:
        configured = str(provider_admin.snapshot(engine).get("configured_default_model", "") or "")
        if configured.startswith(provider_id + "/"):
            raise provider_admin.ProviderAdminError(
                "default_provider_cannot_delete",
                "该 Provider 承载当前配置默认模型；请先切换默认模型。",
                status_code=409,
            )

        def _delete(config: dict[str, Any]) -> None:
            if provider_id not in config:
                raise provider_admin.ProviderAdminError(
                    "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
                )
            del config[provider_id]

        result = provider_admin.mutate(
            engine, expected_version=expected_version, change=_delete
        )
        result["credential_retained"] = True
        return UTF8JSONResponse(content=result)
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.put("/api/v1/providers/{provider_id}/credential")
def provider_admin_credential(
    provider_id: str, body: ProviderCredentialRequest, request: Request
) -> Response:
    from . import provider_admin

    try:
        return UTF8JSONResponse(
            content=provider_admin.set_credential(
                _engine_from(request), provider_id, body.api_key.get_secret_value()
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/{provider_id}/models")
def provider_admin_add_model(
    provider_id: str, body: ProviderModelMutationRequest, request: Request
) -> Response:
    from . import provider_admin

    engine = _engine_from(request)
    mid, model_raw = _model_input_to_raw(body.model)
    try:
        def _add(config: dict[str, Any]) -> None:
            provider = config.get(provider_id)
            if not isinstance(provider, dict):
                raise provider_admin.ProviderAdminError(
                    "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
                )
            models = provider.setdefault("models", {})
            if not isinstance(models, dict):
                raise provider_admin.ProviderAdminError("provider_config_invalid", "models 不是 object。", status_code=409)
            if mid in models:
                raise provider_admin.ProviderAdminError("model_exists", f"模型已存在：{mid}", status_code=409)
            models[mid] = model_raw
            if not provider.get("default_model"):
                provider["default_model"] = mid

        return UTF8JSONResponse(
            content=provider_admin.mutate(engine, expected_version=body.expected_version, change=_add),
            status_code=201,
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.put("/api/v1/providers/{provider_id}/models/{model_id:path}")
def provider_admin_replace_model(
    provider_id: str, model_id: str, body: ProviderModelMutationRequest, request: Request
) -> Response:
    from . import provider_admin

    engine = _engine_from(request)
    new_mid, model_raw = _model_input_to_raw(body.model)
    try:
        configured = str(provider_admin.snapshot(engine).get("configured_default_model", "") or "")
        if configured == f"{provider_id}/{model_id}" and new_mid != model_id:
            raise provider_admin.ProviderAdminError(
                "default_model_cannot_rename",
                "该模型是全局配置默认模型；请先切换默认模型再重命名。",
                status_code=409,
            )

        def _replace(config: dict[str, Any]) -> None:
            provider = config.get(provider_id)
            if not isinstance(provider, dict):
                raise provider_admin.ProviderAdminError("provider_not_found", f"Provider 不存在：{provider_id}", status_code=404)
            models = provider.get("models")
            if not isinstance(models, dict) or model_id not in models:
                raise provider_admin.ProviderAdminError("model_not_found", f"模型不存在：{model_id}", status_code=404)
            if new_mid != model_id and new_mid in models:
                raise provider_admin.ProviderAdminError("model_exists", f"模型已存在：{new_mid}", status_code=409)
            del models[model_id]
            models[new_mid] = model_raw
            if provider.get("default_model") == model_id:
                provider["default_model"] = new_mid

        return UTF8JSONResponse(
            content=provider_admin.mutate(engine, expected_version=body.expected_version, change=_replace)
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.delete("/api/v1/providers/{provider_id}/models/{model_id:path}")
def provider_admin_delete_model(
    provider_id: str,
    model_id: str,
    request: Request,
    expected_version: str = Query(min_length=1, max_length=128),
    confirm: bool = Query(default=False),
) -> Response:
    from . import provider_admin

    if not confirm:
        return UTF8JSONResponse(status_code=409, content={"error": "confirm_required", "detail": "删除模型需 confirm=true。"})
    engine = _engine_from(request)
    try:
        configured = str(provider_admin.snapshot(engine).get("configured_default_model", "") or "")
        if configured == f"{provider_id}/{model_id}":
            raise provider_admin.ProviderAdminError(
                "default_model_cannot_delete", "该模型是全局配置默认模型；请先切换默认模型。", status_code=409
            )

        def _delete(config: dict[str, Any]) -> None:
            provider = config.get(provider_id)
            if not isinstance(provider, dict):
                raise provider_admin.ProviderAdminError("provider_not_found", f"Provider 不存在：{provider_id}", status_code=404)
            models = provider.get("models")
            if not isinstance(models, dict) or model_id not in models:
                raise provider_admin.ProviderAdminError("model_not_found", f"模型不存在：{model_id}", status_code=404)
            if provider.get("default_model") == model_id:
                raise provider_admin.ProviderAdminError(
                    "provider_default_model_cannot_delete", "该模型是 Provider 默认模型；请先修改 Provider 默认模型。", status_code=409
                )
            del models[model_id]
            if bool(provider.get("enabled", True)) and not any(
                bool(v.get("enabled", True)) for v in models.values() if isinstance(v, dict)
            ):
                raise provider_admin.ProviderAdminError(
                    "provider_requires_model", "启用的 Provider 至少需要一个启用模型。", status_code=409
                )

        return UTF8JSONResponse(
            content=provider_admin.mutate(engine, expected_version=expected_version, change=_delete)
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/default-model")
def provider_admin_set_default(body: ProviderDefaultModelRequest, request: Request) -> Response:
    from . import provider_admin

    try:
        return UTF8JSONResponse(content=provider_admin.set_default_model(_engine_from(request), body.model))
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/reload")
def provider_admin_reload(request: Request) -> Response:
    from . import provider_admin

    try:
        return UTF8JSONResponse(content=provider_admin.reload_registry(_engine_from(request)))
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/{provider_id}/test")
def provider_admin_test(
    provider_id: str, body: ProviderTestRequest, request: Request
) -> Response:
    from . import provider_admin

    try:
        return UTF8JSONResponse(
            content=provider_admin.test_provider(_engine_from(request), provider_id, body.model)
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)
