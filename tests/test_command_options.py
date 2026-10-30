"""命令选项语义解析（getopt 两种形态）的单元测试。

第七轮独立审查 P1-1 的根因修复：选项识别不能只做 **token 精确匹配**，
必须按 getopt 语义处理**粘连簇**与**长选项唯一前缀缩写**。
"""

from __future__ import annotations

from llm_loop.core.command_options import (
    CURL_OPTIONS,
    PERL_OPTIONS,
    SED_OPTIONS,
    TAR_OPTIONS,
    scan_options,
)


def test_short_cluster_splits_flags_and_value_option() -> None:
    """``-nf`` = ``-n``（开关）+ ``-f``（取值，值是下一个 token）。"""
    scan = scan_options(SED_OPTIONS, ["-nf", "helper.sed", "in"])
    assert scan.has("-n")
    assert scan.value_of("-f") == "helper.sed"
    assert scan.operands == ("in",)


def test_short_cluster_attached_value() -> None:
    """``-fFILE`` = ``-f`` 取内联值（getopt 语义）。"""
    scan = scan_options(SED_OPTIONS, ["-fhelper.sed", "in"])
    assert scan.value_of("-f") == "helper.sed"
    assert scan.operands == ("in",)


def test_long_option_unique_prefix_is_resolved() -> None:
    """``--fi`` 是 ``--file`` 的唯一前缀缩写。"""
    scan = scan_options(SED_OPTIONS, ["--fi", "helper.sed", "in"])
    assert scan.has("--file")
    assert scan.value_of("--file") == "helper.sed"


def test_ambiguous_prefix_yields_union_of_candidates() -> None:
    """``--f`` 同时是 ``--file`` / ``--follow-symlinks`` 的前缀 ⇒ 两个候选都产出。"""
    scan = scan_options(SED_OPTIONS, ["--f", "helper.sed", "in"])
    assert scan.has("--file")
    assert scan.has("--follow-symlinks")
    assert any(event.ambiguous for event in scan.events)


def test_inline_value_is_used_without_consuming_next_token() -> None:
    """``--expression=CMD`` 的值内联，不消费下一个 token。"""
    scan = scan_options(SED_OPTIONS, ["--expression=CMD", "in"])
    assert scan.value_of("--expression") == "CMD"
    assert scan.operands == ("in",)


def test_tar_prefix_resolves_to_extract_mode() -> None:
    """``--extrac`` 解析成 ``--extract``（tar 的解包模式）。"""
    scan = scan_options(TAR_OPTIONS, ["--extrac", "-f", "a.tar"])
    assert scan.has("--extract")
    assert scan.value_of("-f") == "a.tar"


def test_curl_remote_name_all_prefix_is_dangerous() -> None:
    """``--remote-name-a`` 解析成 ``--remote-name-all``（按远端名落盘）。"""
    scan = scan_options(CURL_OPTIONS, ["--remote-name-a", "https://x/y"])
    assert scan.has("--remote-name-all")
    assert not scan.has("--remote-name")


def test_perl_cluster_finds_inplace_switch() -> None:
    """``-lpie`` 里含 ``-i``（就地编辑）——perl 的短开关可任意聚集。"""
    scan = scan_options(PERL_OPTIONS, ["-lpie", "s/a/b/", "/outside/x"])
    assert scan.has("-i")
    assert scan.operands == ("/outside/x",)


def test_perl_value_switch_eats_rest_of_cluster() -> None:
    """``-Mstrict`` = ``-M`` 取值 ``strict`` ⇒ 簇里没有别的开关。"""
    scan = scan_options(PERL_OPTIONS, ["-Mstrict", "-e", "print 1"])
    assert scan.value_of("-M") == "strict"
    assert not scan.has("-i")


def test_unknown_short_letter_is_unresolved_and_truncates_cluster() -> None:
    """未知字母 ⇒ 该簇在此截断并记 ``unresolved``（调用方据此 fail-closed）。"""
    scan = scan_options(SED_OPTIONS, ["-Zf", "helper.sed"])
    assert scan.unresolved == ("-Zf",)
    assert not scan.has("-f")


def test_negative_number_argument_is_not_an_option() -> None:
    """``-5`` 是参数不是选项（不产生 unresolved）。"""
    scan = scan_options(SED_OPTIONS, ["-5"])
    assert scan.unresolved == ()
    assert scan.operands == ("-5",)
