"""Web provider/model management routes.

Mutating endpoints are included under the same Web router, so public deployments inherit
existing authentication and exact-Origin CSRF middleware from ``llm_loop.web``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from .provider_admin import (
    ProviderAdminError,
    _ref_hosts_default,
    discover_models,
    generated_api_key_env,
    merge_model_unknown,
    merge_provider_unknown,
    mutate,
    patch_provider,
    reload_registry,
    set_credential,
    set_default_model,
    snapshot,
    test_provider,
    validate_provider_raw,
)
from .schemas import (
    ProviderCreateRequest,
    ProviderCredentialRequest,
    ProviderDefaultModelRequest,
    ProviderDiscoverRequest,
    ProviderModelMutationRequest,
    ProviderPatchRequest,
    ProviderReplaceRequest,
    ProviderTestRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()
UTF8JSONResponse = JSONResponse


def _engine_from(request: Request) -> Any:
    return request.app.state.engine

def _provider_admin_error(exc: Exception) -> Response:
    if isinstance(exc, ProviderAdminError):
        # model-admin design §6.1.4/§7.2: 错误体保留 error code、detail 与附件事实
        # （冲突附带 current_version），供 UI 显示字段路径/原因/当前 revision。
        content: dict[str, Any] = {"error": exc.code, "detail": exc.detail}
        if exc.extra:
            content.update(exc.extra)
        return UTF8JSONResponse(status_code=exc.status_code, content=content)
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
    try:
        return UTF8JSONResponse(content=snapshot(_engine_from(request)))
    except Exception as exc:  # noqa: BLE001 - mapped to bounded admin error
        return _provider_admin_error(exc)


@router.post("/api/v1/providers")
def provider_admin_create(body: ProviderCreateRequest, request: Request) -> Response:
    engine = _engine_from(request)
    pid, raw = _provider_input_to_raw(body.provider)
    secret = body.api_key.get_secret_value() if body.api_key is not None else None
    if secret is not None and not raw.get("api_key_env"):
        raw["api_key_env"] = generated_api_key_env(pid)
    try:
        def _create(config: dict[str, Any]) -> None:
            if pid in config:
                raise ProviderAdminError(
                    "provider_exists", f"Provider 已存在：{pid}", status_code=409
                )
            config[pid] = raw

        result = mutate(
            engine, expected_version=body.expected_version, change=_create
        )
        # Credential write is intentionally separate from provider JSON. If it fails,
        # the provider remains truthfully visible as credential missing and the error
        # is returned; no secret ever enters provider JSON.
        if secret is not None:
            result = set_credential(engine, pid, secret)
        return UTF8JSONResponse(content=result, status_code=201)
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.put("/api/v1/providers/{provider_id}")
def provider_admin_replace(
    provider_id: str, body: ProviderReplaceRequest, request: Request
) -> Response:
    engine = _engine_from(request)
    pid, raw = _provider_input_to_raw(body.provider)
    if pid != provider_id:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "provider_id_mismatch", "detail": "路径 provider_id 与 body.id 必须一致。"},
        )
    try:
        if not bool(raw.get("enabled", True)) and _ref_hosts_default(engine, provider_id):
            # model-admin design §6.2.3-4/§7.7：配置默认与运行默认任一命中都拒绝停用。
            raise ProviderAdminError(
                "default_provider_cannot_disable",
                "该 Provider 当前承载默认模型（配置或运行默认）；请先切换默认模型。",
                status_code=409,
            )

        def _replace(config: dict[str, Any]) -> None:
            if provider_id not in config:
                raise ProviderAdminError(
                    "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
                )
            # design §7.3：整包替换不得绕过默认模型停用/删除保护（与模型级 PUT/DELETE 同口径）。
            existing = config[provider_id] if isinstance(config[provider_id], dict) else {}
            # 单次取值再 isinstance 收窄：重复调用 existing.get(...)/raw.get(...) 时
            # 类型检查器无法把两次调用关联起来，会把结果仍当 Optional 而报成员访问错误。
            prev_models_raw = existing.get("models")
            prev_models = prev_models_raw if isinstance(prev_models_raw, dict) else {}
            next_models_raw = raw.get("models")
            next_models = next_models_raw if isinstance(next_models_raw, dict) else {}
            for model_id, prev in prev_models.items():
                prev_enabled = bool(prev.get("enabled", True)) if isinstance(prev, dict) else True
                nxt = next_models.get(model_id)
                still_enabled = isinstance(nxt, dict) and bool(nxt.get("enabled", True))
                if (
                    prev_enabled
                    and not still_enabled
                    and _ref_hosts_default(engine, provider_id, model_id)
                ):
                    raise ProviderAdminError(
                        "default_model_cannot_disable",
                        f"模型 {provider_id}/{model_id} 承载默认模型（配置或运行默认）；请先切换默认模型。",
                        status_code=409,
                    )
            # design FR-13/§8.1：整包替换也保留 schema 外的未知字段（含旧模型条目内）。
            config[provider_id] = merge_provider_unknown(config[provider_id], raw)

        return UTF8JSONResponse(
            content=mutate(
                engine, expected_version=body.expected_version, change=_replace
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.patch("/api/v1/providers/{provider_id}")
def provider_admin_patch(
    provider_id: str, body: ProviderPatchRequest, request: Request
) -> Response:
    """行级 PATCH（model-admin design §6.1.3/§7.2）：enabled/default_model/display_name 等子集."""
    engine = _engine_from(request)
    fields = {
        key: value
        for key, value in body.model_dump(
            exclude={"expected_version"}, exclude_none=True
        ).items()
    }
    try:
        return UTF8JSONResponse(
            content=patch_provider(
                engine, provider_id, body.expected_version, fields
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
    if not confirm:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "confirm_required", "detail": "删除 Provider 需 confirm=true。"},
        )
    engine = _engine_from(request)
    try:
        if _ref_hosts_default(engine, provider_id):
            raise ProviderAdminError(
                "default_provider_cannot_delete",
                "该 Provider 承载当前默认模型（配置或运行默认）；请先切换默认模型。",
                status_code=409,
            )

        def _delete(config: dict[str, Any]) -> None:
            if provider_id not in config:
                raise ProviderAdminError(
                    "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
                )
            del config[provider_id]

        result = mutate(
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
    try:
        return UTF8JSONResponse(
            content=set_credential(
                _engine_from(request), provider_id, body.api_key.get_secret_value()
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/{provider_id}/models")
def provider_admin_add_model(
    provider_id: str, body: ProviderModelMutationRequest, request: Request
) -> Response:
    engine = _engine_from(request)
    mid, model_raw = _model_input_to_raw(body.model)
    try:
        def _add(config: dict[str, Any]) -> None:
            provider = config.get(provider_id)
            if not isinstance(provider, dict):
                raise ProviderAdminError(
                    "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
                )
            models = provider.setdefault("models", {})
            if not isinstance(models, dict):
                raise ProviderAdminError("provider_config_invalid", "models 不是 object。", status_code=409)
            if mid in models:
                raise ProviderAdminError("model_exists", f"模型已存在：{mid}", status_code=409)
            models[mid] = model_raw
            if not provider.get("default_model"):
                provider["default_model"] = mid
            validate_provider_raw(provider_id, provider)

        return UTF8JSONResponse(
            content=mutate(engine, expected_version=body.expected_version, change=_add),
            status_code=201,
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.put("/api/v1/providers/{provider_id}/models/{model_id:path}")
def provider_admin_replace_model(
    provider_id: str, model_id: str, body: ProviderModelMutationRequest, request: Request
) -> Response:
    engine = _engine_from(request)
    new_mid, model_raw = _model_input_to_raw(body.model)
    try:
        hosts_default = _ref_hosts_default(engine, provider_id, model_id)
        if hosts_default and new_mid != model_id:
            raise ProviderAdminError(
                "default_model_cannot_rename",
                "该模型是全局默认模型（配置或运行默认）；请先切换默认模型再重命名。",
                status_code=409,
            )
        if hosts_default and model_raw.get("enabled") is False:
            raise ProviderAdminError(
                "default_model_cannot_disable",
                "该模型是全局默认模型（配置或运行默认）；请先切换默认模型再停用。",
                status_code=409,
            )

        def _replace(config: dict[str, Any]) -> None:
            provider = config.get(provider_id)
            if not isinstance(provider, dict):
                raise ProviderAdminError("provider_not_found", f"Provider 不存在：{provider_id}", status_code=404)
            models = provider.get("models")
            if not isinstance(models, dict) or model_id not in models:
                raise ProviderAdminError("model_not_found", f"模型不存在：{model_id}", status_code=404)
            if new_mid != model_id and new_mid in models:
                raise ProviderAdminError("model_exists", f"模型已存在：{new_mid}", status_code=409)
            # design FR-13/§9.2-5：改名/替换保留未展示字段（note 之外的手写 extra 也保留）。
            merged_model = merge_model_unknown(models.get(model_id), model_raw)
            if provider.get("default_model") == model_id:
                provider["default_model"] = new_mid
            del models[model_id]
            models[new_mid] = merged_model
            validate_provider_raw(provider_id, provider)

        return UTF8JSONResponse(
            content=mutate(engine, expected_version=body.expected_version, change=_replace)
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
    if not confirm:
        return UTF8JSONResponse(status_code=409, content={"error": "confirm_required", "detail": "删除模型需 confirm=true。"})
    engine = _engine_from(request)
    try:
        if _ref_hosts_default(engine, provider_id, model_id):
            raise ProviderAdminError(
                "default_model_cannot_delete", "该模型是全局默认模型（配置或运行默认）；请先切换默认模型。", status_code=409
            )

        def _delete(config: dict[str, Any]) -> None:
            provider = config.get(provider_id)
            if not isinstance(provider, dict):
                raise ProviderAdminError("provider_not_found", f"Provider 不存在：{provider_id}", status_code=404)
            models = provider.get("models")
            if not isinstance(models, dict) or model_id not in models:
                raise ProviderAdminError("model_not_found", f"模型不存在：{model_id}", status_code=404)
            if provider.get("default_model") == model_id:
                raise ProviderAdminError(
                    "provider_default_model_cannot_delete", "该模型是 Provider 默认模型；请先修改 Provider 默认模型。", status_code=409
                )
            del models[model_id]
            if bool(provider.get("enabled", True)) and not any(
                bool(v.get("enabled", True)) for v in models.values() if isinstance(v, dict)
            ):
                raise ProviderAdminError(
                    "provider_requires_model", "启用的 Provider 至少需要一个启用模型。", status_code=409
                )

        return UTF8JSONResponse(
            content=mutate(engine, expected_version=expected_version, change=_delete)
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/default-model")
def provider_admin_set_default(body: ProviderDefaultModelRequest, request: Request) -> Response:
    try:
        return UTF8JSONResponse(content=set_default_model(_engine_from(request), body.model))
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/discover-models")
def provider_admin_discover_models(body: ProviderDiscoverRequest, request: Request) -> Response:
    """模型发现（model-admin design §6.3.1/§7.5）：只返回候选，不写配置."""
    try:
        return UTF8JSONResponse(
            content=discover_models(
                _engine_from(request),
                base_url=body.base_url,
                wire_protocol=body.wire_protocol,
                api_key=body.api_key.get_secret_value() if body.api_key is not None else None,
                provider_id=body.provider_id,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/discover")
def provider_admin_discover_alias(body: ProviderDiscoverRequest, request: Request) -> Response:
    """discover-models 的短路径别名（委派任务口径）；行为与 design §6.3.1 完全一致."""
    return provider_admin_discover_models(body, request)


@router.post("/api/v1/providers/reload")
def provider_admin_reload(request: Request) -> Response:
    try:
        return UTF8JSONResponse(content=reload_registry(_engine_from(request)))
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)


@router.post("/api/v1/providers/{provider_id}/test")
def provider_admin_test(
    provider_id: str, body: ProviderTestRequest, request: Request
) -> Response:
    try:
        return UTF8JSONResponse(
            content=test_provider(_engine_from(request), provider_id, body.model)
        )
    except Exception as exc:  # noqa: BLE001
        return _provider_admin_error(exc)
