"""回归钉：三个 fail-closed 异常穿过 contextlib 类上下文管理器后必须原样传播（错误码不丢）。

缺陷背景：它们曾是 frozen dataclass；冻结生成的 __setattr__ 会拦下 __traceback__ 的赋值，
异常穿过 @contextlib.contextmanager 的 with 块时被 FrozenInstanceError 顶替，
精确捕获（except ContractError 等）随之失效。
"""

from __future__ import annotations

import contextlib

import pytest

from ctp_contract.errors import ContractError
from ctp_reader.errors import ReaderError
from ctp_registry.record import RegistryError

ERRORS = (ContractError, RegistryError, ReaderError)


@contextlib.contextmanager
def guard():
    try:
        yield
    finally:
        pass


def _sample(error_type):
    return error_type("stable_code", "field", "detail")


@pytest.mark.parametrize("error_type", ERRORS)
def test_error_crosses_a_contextlib_context_manager_intact(error_type):
    with pytest.raises(error_type) as excinfo:
        with guard():
            raise _sample(error_type)
    assert excinfo.value.code == "stable_code"
    assert excinfo.value.path == "field"
    assert str(excinfo.value).startswith("stable_code @ field")


@pytest.mark.parametrize("error_type", ERRORS)
def test_error_crosses_an_exit_stack_and_raise_from(error_type):
    with pytest.raises(error_type) as excinfo:
        with contextlib.ExitStack() as stack:
            stack.enter_context(guard())
            try:
                raise ValueError("cause")
            except ValueError as cause:
                raise _sample(error_type) from cause
    assert excinfo.value.code == "stable_code"
    assert isinstance(excinfo.value.__cause__, ValueError)


@pytest.mark.parametrize("error_type", ERRORS)
def test_fields_stay_read_only_after_construction(error_type):
    error = _sample(error_type)
    with pytest.raises(AttributeError):
        error.code = "tampered"
    assert error.code == "stable_code"


@pytest.mark.parametrize("error_type", ERRORS)
def test_errors_remain_hashable_and_compare_by_fields(error_type):
    assert _sample(error_type) == _sample(error_type)
    assert len({_sample(error_type), _sample(error_type)}) == 1
