---
method_id: convention-named-tool-failfast-error-names-deps-abd3e3c1ab7d
name: convention-named-tool-failfast-error-names-deps
description: 任务书同时钉死工件格式与指定工具套件目录时，不要先做全目录分页枚举、全盘 find、OS/apt 盘点或备用解释器栈探索：按套件命名约定（如 john 的 <fmt>2john）直接推导入口工具名并立即对工件首跑，让首次执行暴露唯一真实未知量——依赖可用性；报错点名的缺失模块（Can't locate X）就是确切安装清单，一次性装齐重跑即可。次级需求（解压器等）推迟到主未知量解决后再查再装。本集把约 15 轮环境探索压成『约定定位→首跑→装点名包→受限 keyspace 爆破→解压→cmp 校验』。
aliases: 7z破解直接跑7z2john别先盘点, john缺perl模块按报错apt装, Can't locate报错就是安装清单, X2john命名约定定位入口工具, 先跑一次让工具报错告诉你缺什么, 格式加套件钉死时跳过环境清点
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:tb-task:0:026587f0fdcaa994461b
evidence_refs: learning:learn:41cb76935729
created_at: 2026-10-23T12:51:41.823626+08:00
updated_at: 2026-10-23T12:51:41.823626+08:00
---
## Trigger
任务说明已明确给出目标工件的具体格式（扩展名/格式名）和指定工具套件及其所在目录（如『用 /app/john/run 里的 john 破解 secrets.7z，密码是 4 位数字』），需要走『套件入口工具→处理工件→下游动作』管线时。

## Discriminator
任务文本已同时钉死格式（.7z）与套件路径（john @ /app/john/run）；套件命名约定 <fmt>2john 唯一确定入口工具名，无需枚举即可定位。因此此刻唯一真实未知量是依赖可用性——只有直接执行该工具才能揭示，且其失败信息会权威地点名确切缺失依赖（如 Can't locate Compress::Raw::Lzma → libcompress-raw-lzma-perl），任何事先的环境盘点都无法替代这一步。

## Short path
- 由格式+套件命名约定推导入口工具名（7z → 7z2john.pl），用作用域受限 glob 确认存在（ls /app/john/run/*7z*），不做全目录分页枚举或全盘 find
- 立即对工件首跑该工具（perl 7z2john.pl /app/secrets.7z）：成功即得 $7z$ 哈希行；失败则报错本身点名缺失依赖
- 按报错点名一次性安装（apt install libcompress-raw-lzma-perl），重跑得哈希；不预查 py7zr/Crypto/cryptography 等替代栈
- 用任务已给的 keyspace 约束生成候选（0000–9999），john --format=7z 爆破 + --show 取密码
- 主未知量（密码）解决后才处理次级工具：which 7z || apt install p7zip-full，用 -p 密码解压
- 复制解出文件到任务指定路径，cmp 校验一致即停

## Stop conditions
- 转换器产出哈希且 john --show 确认密码后，不再做任何环境探索或备用方案枚举
- 解压产物与写入的 solution 文件 cmp 一致后立即停止，不再追加确认性读取

## Verification
- 首跑结果二择一均为权威下一步：要么哈希行、要么具名缺失模块报错
- 安装清单仅含报错点名的包，重跑即成功（不装无关备选依赖）
- john --show 得到的密码与 7z -p 实际解压成功互证；最终文件与解出文件 cmp 一致

## Counterexamples
- 套件中不存在该格式的约定名工具（无 <fmt>2john）→ 命名推导落空，此时 --list=formats 或目录枚举才是正当第一步
- 环境离线且首跑报缺依赖 → 安装路径不可行，才改为枚举替代实现（标准库/其他二进制）；且须先让安装尝试失败，而非预先枚举替代栈
- 任务目标本身就是环境审计/盘点 → 宽枚举即目标，本方法不适用
- 工件格式未被任务言明（只有一堆未知文件）→ 需先做签名/格式识别，无从约定推导入口工具
