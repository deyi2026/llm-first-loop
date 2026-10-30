"""命令选项语义解析：getopt 的两种形态（短选项粘连簇 / 长选项唯一前缀缩写）.

第七轮独立审查 P1-1 的根因：选项识别只做 **token 精确匹配**，
漏掉 getopt 的两种形态：

- **粘连簇**：``sed -nf helper.sed in``（``-n`` 开关 + ``-f`` 取值）——
  只认精确 ``-f`` ⇒ 整个 token 被跳过 ⇒ 脚本文件不被扫（真实越界写被放行）。
- **长选项唯一前缀缩写**：``tar --extrac``（= ``--extract``）、
  ``curl --remote-name-a``（= ``--remote-name-all``）——只认完整长名 ⇒
  危险选项被跳过（真实越界写被放行）。

本模块按 **族（family）** 建模选项语义：一个族给出「规范长名 + 是否取值 +
短字母」的表；解析器把 argv 还原成选项事件（规范名 + 取值），并把**无法确定
归属**的 token 单列（``unresolved``），由调用方按族决定是否 fail-closed。

判定原则（fail-closed 方向）
----------------------------
1. **歧义按并集**：``--outp`` 可能匹配 ``--output`` 或 ``--output-dir`` ⇒
   两个候选都产出事件 ⇒ 调用方看到危险候选就按危险处理。
2. **取值候选优先**：候选里有取值型选项且 token 本身不带 ``=`` ⇒ 取下一个
   token 作为其值（可能多消费一个位置参数——宁可误判不可漏判）。
3. **未知短字母截断粘连簇**：未知字母可能自己就取值 ⇒ 其后的字母不能被
   认定为开关 ⇒ 该簇在此截断并记入 ``unresolved``（调用方按族决定是否 fail-closed）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class OptionEvent:
    """一次选项识别的结果."""

    name: str
    """规范名：长选项 ``--expression`` / 短选项 ``-f``."""
    value: str | None = None
    """取值型选项的值（``None`` = 开关型，或未取到值）."""
    ambiguous: bool = False
    """是否因候选不唯一而按并集产出."""


@dataclass(frozen=True)
class FamilyOptions:
    """一个命令族的选项语义模型（长选项表 + 短选项表）."""

    long_options: tuple[tuple[str, bool], ...] = ()
    """(规范长名, 是否取值) —— 用于长选项精确匹配与**唯一前缀缩写**."""
    short_options: tuple[tuple[str, bool], ...] = ()
    """(单字母, 是否取值) —— 用于粘连簇拆分."""

    def long_candidates(self, name: str) -> list[tuple[str, bool]]:
        """长选项名 → 候选列表.

        精确匹配优先；否则取**唯一前缀缩写**的候选（多个候选 = 歧义 ⇒ 并集）。
        """
        if not name.startswith("--"):
            return []
        exact = [entry for entry in self.long_options if entry[0] == name]
        if exact:
            return exact
        return [entry for entry in self.long_options if entry[0].startswith(name)]

    def short_spec(self, letter: str) -> tuple[str, bool] | None:
        """短字母 → (规范名, 是否取值)；未知字母返回 ``None``."""
        for entry in self.short_options:
            if entry[0] == letter:
                return f"-{letter}", entry[1]
        return None


@dataclass(frozen=True)
class OptionScan:
    """一次选项解析的结果."""

    events: tuple[OptionEvent, ...] = ()
    """已识别的选项事件（含歧义并集）."""
    unresolved: tuple[str, ...] = ()
    """无法确定归属的 token（未知长选项 / 未知短字母粘连簇）."""
    operands: tuple[str, ...] = ()
    """非选项 token（且未被当作选项值消费）."""

    def has(self, *names: str) -> bool:
        """是否出现指定选项（含歧义候选）."""
        return any(event.name in names for event in self.events)

    def value_of(self, *names: str) -> str | None:
        """取指定选项的值（第一个非空值）."""
        for event in self.events:
            if event.name in names and event.value is not None:
                return event.value
        return None


def scan_options(family: FamilyOptions, args: Sequence[str]) -> OptionScan:
    """按 getopt 语义解析 ``args`` 里的选项（粘连簇 + 唯一前缀缩写）."""
    events: list[OptionEvent] = []
    unresolved: list[str] = []
    operands: list[str] = []
    raw = [str(a) for a in args]
    index = 0
    while index < len(raw):
        token = raw[index]
        if token == "--":
            operands.extend(raw[index + 1 :])
            break
        if token.startswith("--"):
            index = _scan_long(family, raw, index, events, unresolved)
            continue
        if len(token) > 1 and token.startswith("-"):
            index = _scan_short(family, raw, index, events, unresolved, operands)
            continue
        operands.append(token)
        index += 1
    return OptionScan(tuple(events), tuple(unresolved), tuple(operands))


def _scan_long(
    family: FamilyOptions,
    raw: list[str],
    index: int,
    events: list[OptionEvent],
    unresolved: list[str],
) -> int:
    """长选项：精确匹配 / 唯一前缀缩写；``--name=value`` 内联取值."""
    token = raw[index]
    name, sep, inline = token.partition("=")
    candidates = family.long_candidates(name)
    if not candidates:
        unresolved.append(token)
        return index + 1
    value = inline if sep else None
    consumed = 1
    if not sep and any(takes for _name, takes in candidates) and index + 1 < len(raw):
        value = raw[index + 1]
        consumed = 2
    ambiguous = len(candidates) > 1
    for cname, takes in candidates:
        events.append(OptionEvent(cname, value if takes else None, ambiguous=ambiguous))
    return index + consumed


def _scan_short(
    family: FamilyOptions,
    raw: list[str],
    index: int,
    events: list[OptionEvent],
    unresolved: list[str],
    operands: list[str],
) -> int:
    """短选项粘连簇：``-nf``（``-n`` 开关 + ``-f`` 取值）.

    取值型字母若后面还有字母 ⇒ 其余字母就是内联值（getopt 语义）；
    若在簇尾 ⇒ 取下一个 token 作为值。未知字母 ⇒ 截断该簇并记 ``unresolved``。
    """
    token = raw[index]
    body = token[1:]
    if body.isdigit():
        # 负数参数不是选项（``tail -5``）
        operands.append(token)
        return index + 1
    for position, letter in enumerate(body):
        if letter == ".":
            # 后缀形态（``-i.bak`` / ``-pi.bak``）：点号之后不是开关。
            # 只有在**还没遇到取值型开关**时点号才是后缀——``-fhelper.sed`` 的
            # 值是 ``helper.sed``（getopt：取值型开关吃掉整个剩余 token）。
            return index + 1
        spec = family.short_spec(letter)
        if spec is None:
            unresolved.append(token)
            return index + 1
        name, takes = spec
        if not takes:
            events.append(OptionEvent(name, None))
            continue
        rest = body[position + 1 :]
        if rest:
            events.append(OptionEvent(name, rest))
            return index + 1
        if index + 1 < len(raw):
            events.append(OptionEvent(name, raw[index + 1]))
            return index + 2
        events.append(OptionEvent(name, None))
        return index + 1
    return index + 1


# ── 族模型 ────────────────────────────────────────────────────────────────
#
# 只列**判定相关**的选项（危险项必须全在表内；无害项按需补齐以免粘连簇
# 解析被未知字母截断）。表不完整 ⇒ 后果是「未识别的选项被跳过」，
# 而不是「误判为危险」⇒ 属于放行方向的残余，须在文档中显式声明。
#
# **第八轮独立审查 P1-5（unresolved 处置口径不一致）**：sed/perl 消费
# ``scan.unresolved``（fail-closed），而 curl/wget/tar/script 不消费 ⇒ 同一模块
# 内两套口径 ⇒ 与「判定原则（fail-closed 方向）」相矛盾。⇒ **统一为 fail-closed**：
# 各族表补齐常见选项后，未能识别的选项一律按「写目标无法静态定位」处理。
# 可用性代价（族表未收录的冷门选项会被拦）属 fail-closed 方向的已知代价，
# 已在 HANDOFF §10.12 登记为残余。

SED_OPTIONS = FamilyOptions(
    long_options=(
        ("--expression", True),
        ("--file", True),
        ("--in-place", False),
        ("--quiet", False),
        ("--silent", False),
        ("--regexp-extended", False),
        ("--separate", False),
        ("--null-data", False),
        ("--unbuffered", False),
        ("--posix", False),
        ("--sandbox", False),
        ("--debug", False),
        ("--verbose", False),
        ("--follow-symlinks", False),
    ),
    short_options=(
        ("e", True),
        ("f", True),
        ("i", False),
        ("n", False),
        ("r", False),
        ("E", False),
        ("s", False),
        ("z", False),
        ("u", False),
        ("I", False),
        ("p", False),
        ("l", False),
        ("M", False),
        ("t", False),
        ("w", False),
        ("b", False),
        ("T", False),
        ("D", False),
    ),
)

TAR_OPTIONS = FamilyOptions(
    long_options=(
        ("--extract", False),
        ("--get", False),
        ("--create", False),
        ("--list", False),
        ("--append", False),
        ("--update", False),
        ("--delete", False),
        ("--file", True),
        ("--directory", True),
        ("--one-top-level", True),
        ("--transform", True),
        ("--exclude", True),
        ("--exclude-from", True),
        ("--files-from", True),
        ("--strip-components", True),
        ("--checkpoint", True),
        ("--checkpoint-action", True),
        ("--occurrence", True),
        ("--mode", True),
        ("--owner", True),
        ("--group", True),
        ("--sort", True),
        ("--newer", True),
        ("--older", True),
        ("--after-date", True),
        ("--volno-file", True),
        ("--index-file", True),
        ("--label", True),
        ("--blocking-factor", True),
        ("--record-size", True),
        ("--use-compress-program", True),
        ("--warning", True),
        ("--to-stdout", False),
        ("--gzip", False),
        ("--gunzip", False),
        ("--bzip2", False),
        ("--xz", False),
        ("--zstd", False),
        ("--verbose", False),
        ("--version", False),
        ("--help", False),
        ("--anchored", False),
        ("--no-anchored", False),
        ("--wildcards", False),
        ("--no-wildcards", False),
        ("--preserve-permissions", False),
        ("--dereference", False),
        ("--hard-dereference", False),
        ("--overwrite-dir", False),
        ("--no-overwrite-dir", False),
        ("--keep-directory-files", False),
        ("--skip-old-files", False),
        ("--ignore-failed-read", False),
        ("--unquote", False),
        ("--quote-chars", False),
        ("--show-transformed-names", False),
        ("--full-time", False),
        # 第八轮 P1-2：``--incremental/--listed-incremental``（``-g``）**取值**
        # （快照文件）——tar 建档时把快照写进该文件 ⇒ 它是写目标，不是开关。
        ("--incremental", True),
        ("--listed-incremental", True),
        # 第八轮 P1-2：``-F/--info-script FILE`` 会**执行脚本** ⇒ 载荷不可静态定位。
        ("--info-script", True),
        ("--numeric-owner", False),
        ("--same-owner", False),
        ("--same-permissions", False),
        ("--no-same-permissions", False),
        ("--same-order", False),
        ("--acls", False),
        ("--xattrs", False),
        ("--selinux", False),
        ("--null", False),
        ("--verbatim-files-from", False),
        ("--sparse", False),
        ("--totals", False),
        ("--utc", False),
        # 第八轮 P1-5：统一 fail-closed 后，族表未收录的选项会被拦 ⇒ 补齐常见项。
        ("--absolute-names", False),
        ("--no-absolute-names", False),
        ("--add-file", True),
        ("--append-file", True),
        ("--atime-preserve", False),
        ("--clamp-mtime", False),
        ("--compress", False),
        ("--format", True),
        ("--ignore-case", False),
        ("--ignore-zeros", False),
        ("--lzma", False),
        ("--lzip", False),
        ("--lzop", False),
        ("--lrzip", False),
        ("--mtime", True),
        ("--newer-mtime", True),
        ("--no-acls", False),
        ("--no-recursion", False),
        ("--no-same-owner", False),
        ("--no-unquote", False),
        ("--no-xattrs", False),
        ("--pax-option", True),
        ("--posix", False),
        ("--quoting-style", True),
        ("--recursion", False),
        ("--sparse-version", False),
        ("--touch", False),
    ),
    short_options=(
        ("f", True),
        ("C", True),
        ("T", True),
        ("I", True),
        ("c", False),
        ("x", False),
        ("t", False),
        ("r", False),
        ("u", False),
        ("z", False),
        ("j", False),
        ("w", False),
        ("k", False),
        ("m", False),
        ("O", False),
        ("v", False),
        ("p", False),
        ("b", False),
        ("S", False),
        # 第八轮 P1-2：``-g`` 取值（快照文件，写目标），不是开关。
        ("g", True),
        ("L", False),
        ("M", False),
        ("N", False),
        ("P", False),
        # 第八轮 P1-5：补齐常见短字母（统一 fail-closed 后未收录会被拦）。
        ("B", False),
        ("F", True),
        ("H", True),
        ("K", True),
        ("U", False),
        ("V", True),
        ("X", True),
        ("Z", True),
        ("d", False),
        ("h", False),
        ("i", False),
        ("l", False),
        ("n", False),
        ("o", False),
        ("q", False),
    ),
)

# curl：危险项（写目标）= --output/--output-dir/--remote-name*/--remote-header-name/
# --dump-header/--trace*/--cookie-jar/--stderr/--libcurl/--etag-save/--json/
# --crt-file/--create-dirs；其余短字母为**粘连簇完整性**而列（值语义按 curl --help）。
CURL_OPTIONS = FamilyOptions(
    long_options=(
        ("--output", True),
        ("--output-dir", True),
        ("--remote-name", False),
        ("--remote-name-all", False),
        ("--remote-header-name", False),
        ("--dump-header", True),
        ("--trace", True),
        ("--trace-ascii", True),
        ("--cookie-jar", True),
        ("--stderr", True),
        ("--libcurl", True),
        ("--etag-save", True),
        ("--json", True),
        ("--crt-file", True),
        ("--create-dirs", False),
        ("--user-agent", True),
        ("--header", True),
        ("--data", True),
        ("--data-raw", True),
        ("--data-binary", True),
        ("--data-urlencode", True),
        ("--form", True),
        ("--form-string", True),
        ("--request", True),
        ("--max-time", True),
        ("--connect-timeout", True),
        ("--max-filesize", True),
        ("--limit-rate", True),
        ("--retry", True),
        ("--proxy", True),
        ("--proxy-user", True),
        ("--cert", True),
        ("--key", True),
        ("--cacert", True),
        ("--capath", True),
        ("--cookie", True),
        ("--netrc", True),
        ("--netrc-file", True),
        ("--range", True),
        ("--referer", True),
        ("--user", True),
        ("--url", True),
        ("--upload-file", True),
        ("--mail-from", True),
        ("--mail-rcpt", True),
        ("--tlsuser", True),
        ("--tlspassword", True),
        ("--cert-type", True),
        ("--key-type", True),
        ("--pass", True),
        ("--random-file", True),
        ("--egd-file", True),
        ("--engine", True),
        ("--ciphers", True),
        ("--proxy-ca", True),
        ("--proxy-cacert", True),
        ("--proxy-capath", True),
        ("--proxy-cert", True),
        ("--proxy-key", True),
        ("--proxy-ciphers", True),
        ("--aws-sigv4", True),
        ("--oauth2-bearer", True),
        ("--sasl-authzid", True),
        ("--service-name", True),
        ("--speed-limit", True),
        ("--speed-time", True),
        ("--keepalive-time", True),
        ("--interface", True),
        ("--dns-servers", True),
        ("--resolve", True),
        ("--write-out", True),
        ("--trace-config", True),
        # 第八轮 P1-5：curl 8.10+ 的 ``--log FILE`` 写日志文件 ⇒ 写目标。
        ("--log", True),
        ("--variable", True),
        ("--silent", False),
        ("--show-error", False),
        ("--location", False),
        ("--compressed", False),
        ("--fail", False),
        ("--fail-early", False),
        ("--insecure", False),
        ("--include", False),
        ("--head", False),
        ("--list-only", False),
        ("--remote-time", False),
        ("--verbose", False),
        ("--version", False),
        ("--help", False),
        ("--digest", False),
        ("--negotiate", False),
        ("--ntlm", False),
        ("--basic", False),
        ("--anyauth", False),
        ("--no-buffer", False),
        ("--raw", False),
        ("--globoff", False),
        ("--no-keepalive", False),
        ("--tcp-nodelay", False),
        ("--ipv4", False),
        ("--ipv6", False),
        ("--http1.0", False),
        ("--http1.1", False),
        ("--http2", False),
        ("--http2-prior-knowledge", False),
        ("--http3", False),
        ("--tlsv1", False),
        ("--tlsv1.0", False),
        ("--tlsv1.1", False),
        ("--tlsv1.2", False),
        ("--tlsv1.3", False),
        ("--tls13-ciphers", True),
        ("--styled-output", False),
        ("--use-ascii", False),
        ("--xattr", False),
        ("--trace-time", False),
        ("--trace-ids", False),
        ("--progress-bar", False),
        ("--no-progress-meter", False),
        ("--suppress-connect-headers", False),
        ("--proxy-anyauth", False),
        ("--proxy-basic", False),
        ("--proxy-digest", False),
        ("--proxy-negotiate", False),
        ("--proxy-ntlm", False),
        ("--proxy-header", True),
        ("--proxy-insecure", False),
        ("--proxy-tlsv1", False),
    ),
    short_options=(
        ("o", True),
        ("O", False),
        ("J", False),
        ("D", True),
        ("A", True),
        ("b", True),
        ("c", True),
        ("d", True),
        ("e", True),
        ("E", True),
        ("F", True),
        ("H", True),
        ("K", True),
        ("m", True),
        ("M", False),
        ("P", True),
        ("Q", True),
        ("r", True),
        ("T", True),
        ("t", True),
        ("u", True),
        ("U", True),
        ("w", True),
        ("x", True),
        ("X", True),
        ("y", True),
        ("Y", True),
        ("0", False),
        ("1", False),
        ("2", False),
        ("3", False),
        ("4", False),
        ("6", False),
        ("a", False),
        ("f", False),
        ("g", False),
        ("G", False),
        ("h", False),
        ("i", False),
        ("I", False),
        ("j", False),
        ("k", False),
        ("l", False),
        ("L", False),
        ("n", False),
        ("p", False),
        ("q", False),
        ("R", False),
        ("s", False),
        ("S", False),
        ("v", False),
        ("V", False),
        ("z", False),
        ("Z", False),
        ("B", False),
    ),
)

WGET_OPTIONS = FamilyOptions(
    long_options=(
        ("--output-document", True),
        ("--directory-prefix", True),
        ("--output-file", True),
        ("--backups", False),
        ("--content-on-error", False),
        ("--continue", False),
        ("--no-clobber", False),
        ("--timestamping", False),
        ("--spider", False),
        ("--user-agent", True),
        ("--header", True),
        ("--post-file", True),
        ("--post-data", True),
        ("--body-file", True),
        ("--body-data", True),
        ("--method", True),
        ("--execute", True),
        ("--reject-file", True),
        ("--input-file", True),
        ("--proxy", True),
        ("--timeout", True),
        ("--tries", True),
        ("--wait", True),
        ("--limit-rate", True),
        ("--bind-address", True),
        ("--ftp-user", True),
        ("--ftp-password", True),
        ("--level", True),
        # 第八轮 P1-5：``-a/--append-output FILE`` **取值**——追加下载日志的文件
        # （旧实现把 ``-a`` 当开关 ⇒ ``wget -a /outside/log URL`` 的写盘漏检）。
        ("--append-output", True),
        ("--quiet", False),
        ("--silent", False),
        ("--no-verbose", False),
        ("--server-response", False),
        ("--debug", False),
        ("--help", False),
        ("--version", False),
        # 第八轮 P1-5：统一 fail-closed 后未收录的选项会被拦 ⇒ 补齐常见项。
        ("--inet4-only", False),
        ("--inet6-only", False),
        ("--https-only", False),
        ("--no-http-keep-alive", False),
        ("--no-check-certificate", False),
        ("--check-certificate", False),
        ("--no-cookies", False),
        ("--no-dns-cache", False),
        ("--no-proxy", False),
        ("--proxy-user", True),
        ("--progress", True),
        ("--random-wait", False),
        ("--read-timeout", True),
        ("--recursive", False),
        ("--restrict-file-names", False),
        ("--retry-connrefused", False),
        ("--passive-ftp", False),
        ("--no-passive-ftp", False),
        ("--secure-protocol", True),
        ("--trust-server-names", False),
        ("--compression", False),
        ("--compression-level", True),
        ("--ignore-case", False),
        ("--hsts", False),
        ("--hsts-file", True),
        ("--max-redirect", True),
        ("--cut-dirs", True),
        ("--ca-certificate", True),
        ("--ca-directory", True),
        ("--certificate", True),
        ("--user", True),
        ("--no-parent", False),
    ),
    short_options=(
        ("O", True),
        ("P", True),
        ("o", True),
        ("i", True),
        ("r", True),
        ("l", True),
        ("t", True),
        ("T", True),
        ("U", True),
        ("w", True),
        ("e", True),
        ("H", True),
        # 第八轮 P1-5：``-a`` 取值（追加日志文件，写目标）。
        ("a", True),
        ("b", False),
        ("c", False),
        ("d", False),
        ("h", False),
        ("k", False),
        ("K", False),
        ("n", False),
        ("N", False),
        ("p", False),
        ("q", False),
        ("S", False),
        ("x", False),
        ("X", False),
        ("Y", False),
        # 第八轮 P1-5：补齐常见短字母。
        ("A", True),
        ("B", True),
        ("C", True),
        ("D", True),
        ("F", False),
        ("I", True),
        ("J", True),
        ("L", False),
        ("M", False),
        ("V", False),
        ("4", False),
        ("6", False),
    ),
)

# perl：短开关可**聚集**成单个 argv（``-pi`` / ``-lpie`` / ``-pain``），
# 取值型开关（``-e`` / ``-M`` / ``-I`` / ``-F`` / ``-D`` / ``-V``）在簇内会吃掉
# 其余字母（``-Mstrict`` ⇒ ``-M`` 的值是 ``strict``）。
# 注意 ``-f`` 是**开关**（不读 ~/.profilerc）——若误标成取值型，会把后面的
# ``-i`` 当成它的值吞掉 ⇒ 越界就地编辑被放行。
PERL_OPTIONS = FamilyOptions(
    long_options=(
        ("--version", False),
        ("--help", False),
        ("--man", False),
        ("--license", False),
    ),
    short_options=(
        ("e", True),
        ("E", True),
        ("I", True),
        ("M", True),
        ("F", True),
        ("D", True),
        ("V", True),
        ("f", False),
        ("a", False),
        ("c", False),
        ("d", False),
        ("g", False),
        ("G", False),
        ("h", False),
        ("i", False),
        ("l", False),
        ("n", False),
        ("p", False),
        ("s", False),
        ("S", False),
        ("t", False),
        ("T", False),
        ("u", False),
        ("U", False),
        ("v", False),
        ("w", False),
        ("W", False),
        ("x", False),
        ("X", False),
        ("z", False),
    ),
)

# script：``-c/--command`` 携带被执行的命令；``-L/--log-out`` 写会话日志文件。
SCRIPT_OPTIONS = FamilyOptions(
    long_options=(
        ("--command", True),
        ("--log-out", True),
        ("--log-timing", True),
        # 第八轮 P1-3：``--log-in/--log-io`` 与 ``--log-out/--log-timing`` 同类——
        # 都是 script 自己写的日志文件 ⇒ 写目标，必须逐个判定。
        ("--log-in", True),
        ("--log-io", True),
        ("--timeout", True),
        ("--return", False),
        ("--quiet", False),
        ("--flush", False),
        ("--append", False),
        ("--echo", False),
        ("--logging-format", True),
        ("--logging-interval", True),
        ("--version", False),
        ("--help", False),
    ),
    short_options=(
        ("c", True),
        ("L", True),
        ("T", True),
        ("B", True),
        ("I", True),
        ("t", True),
        ("e", False),
        ("f", False),
        ("q", False),
        ("a", False),
        ("E", False),
        ("V", False),
    ),
)

# git fast-export：``--export-marks=FILE`` 写 marks 文件（读子命令的写形态）。
GIT_EXPORT_OPTIONS = FamilyOptions(
    long_options=(
        ("--export-marks", True),
        ("--import-marks", True),
        ("--all", False),
        ("--reference-excluded-parents", False),
        ("--reencode", True),
        ("--no-data", False),
        ("--mark-tags", False),
        ("--signed-tags", False),
        ("--tag-of-filtered-object", True),
        ("--fake-missing-tagger", False),
        ("--use-done-feature", False),
        ("--full-tree", False),
        ("--progress", False),
        ("--incremental", False),
        ("--show-original-ids", False),
        ("--anonymize", False),
        ("--reflog", False),
    ),
)
