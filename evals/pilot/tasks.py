"""Agent 评测 pilot 任务集：12 任务，确定性 setup + 确定性 verifier，无外网。

设计原则：
- 单轮可完成（一条用户消息 → agent 自主完成 → verifier 判定）
- 覆盖 LFL 差异化主张：工具优先/读取纪律、瞬态故障重试、多步构建、
  状态接续、分页读取、中断续做
- 每任务: prompt / setup(shell, 幂等) / verify(python, 退出码0=通过) / timeout_s
"""
import json
import textwrap

TASKS = []

def reg(tid, prompt, setup, verify, timeout_s=600, interrupt_s=None):
    """注册一个 pilot 任务（task registry helper）。"""
    TASKS.append({"id": tid, "prompt": prompt, "setup": setup, "verify": verify,
                  "timeout_s": timeout_s, "interrupt_s": interrupt_s})

# T01 读取纪律：必须先读文件再回答，不得编造
reg("t01_read_first_line",
  "读取当前目录下 probe.txt 的第一行，把该行原文写入 answer.txt（不要加任何解释，文件内容仅那一行）。",
  "printf 'PYTHQN-MARKER-L1\\nline-two\\nline-three\\n' > probe.txt",
  textwrap.dedent("""\
    a=open('answer.txt').read().strip(); b=open('probe.txt').readline().strip()
    assert a==b, f'{a!r} != {b!r}'"""))

# T02 瞬态故障重试：gen.py 第一次运行必失败（标记文件），第二次成功
reg("t02_retry_transient",
  "运行 python3 gen.py。若失败，诊断原因后重试，直到它生成 result.json。完成后 result.json 必须存在。",
  textwrap.dedent("""\
    cat > gen.py <<'EOF'
    import os, json
    if not os.path.exists('.ran_once'):
        open('.ran_once','w').write('1')
        raise SystemExit('transient: first run always fails (race with indexer)')
    json.dump({'ok': True, 'n': 42}, open('result.json','w'))
    print('done')
    EOF"""),
  "import json; d=json.load(open('result.json')); assert d=={'ok':True,'n':42}")

# T03 多步构建：模块+测试，测试须全绿
reg("t03_build_module",
  "创建 fib.py 实现 fib(n)（fib(0)=0, fib(1)=1），再创建 test_fib.py（用 unittest）测试 fib(10)==55 与 fib(0)==0，运行 python3 -m unittest test_fib -v 并保证通过。",
  "",
  textwrap.dedent("""\
    import subprocess, sys
    r = subprocess.run([sys.executable,'-m','unittest','test_fib','-v'], capture_output=True, text=True)
    assert r.returncode==0, r.stdout+r.stderr
    import fib; assert fib.fib(10)==55 and fib.fib(0)==0"""))

# T04 修复缺陷：给定失败测试与坏实现
reg("t04_fix_bug",
  "当前目录有 broken.py 与 test_broken.py。运行测试会失败。修复 broken.py 使全部测试通过（不许改测试文件）。",
  textwrap.dedent("""\
    cat > broken.py <<'EOF'
    def median(xs):
        return xs[len(xs)//2]   # 有缺陷
    EOF
    cat > test_broken.py <<'EOF'
    import unittest
    from broken import median
    class T(unittest.TestCase):
        def test_odd(self): self.assertEqual(median([3,1,2]), 2)
        def test_even(self): self.assertEqual(median([4,1,3,2]), 2.5)
        def test_single(self): self.assertEqual(median([9]), 9)
    EOF"""),
  textwrap.dedent("""\
    import subprocess, sys
    r = subprocess.run([sys.executable,'-m','unittest','test_broken'], capture_output=True, text=True)
    assert r.returncode==0, r.stdout+r.stderr"""))

# T05 多文件综合
reg("t05_multi_file_sum",
  "读取 a.txt、b.txt、c.txt（每行一个整数），把三个文件全部整数的总和写入 total.txt（仅数字）。",
  "printf '10\\n20\\n' > a.txt; printf '5\\n' > b.txt; printf '1\\n2\\n3\\n' > c.txt",
  "assert open('total.txt').read().strip()=='41', open('total.txt').read()")

# T06 日志抽取
reg("t06_log_count",
  "在 app.log 中统计级别为 ERROR 的行数，把数字写入 errcount.txt（仅数字）。",
  "printf 'INFO a\\nERROR b\\nWARN c\\nERROR d\\nERROR e\\nINFO f\\n' > app.log",
  "assert open('errcount.txt').read().strip()=='3', open('errcount.txt').read()")

# T07 JSON 变换
reg("t07_json_flatten",
  "读取 in.json，把嵌套字段 data.items（对象数组）中的每个 name 拼成一行一个，写入 names.txt（保持原顺序，共 3 行）。",
  "printf '{\"data\":{\"items\":[{\"name\":\"alpha\"},{\"name\":\"beta\"},{\"name\":\"gamma\"}]}}' > in.json",
  "assert [l for l in open('names.txt').read().splitlines() if l.strip()]==['alpha','beta','gamma']")

# T08 状态接续：半成品 TODO
reg("t08_resume_todo",
  "half_done.py 有 TODO 注释和 README-TASK.md 说明。按说明补全实现并保证 verify 内嵌断言通过：python3 half_done.py 应打印 OK。",
  textwrap.dedent("""\
    cat > README-TASK.md <<'EOF'
    要求：complete(s) 返回 True 当且仅当 s 是回文（忽略大小写与空格）。
    main() 打印 'OK' 当 complete('race car') 为 True 且 complete('hello') 为 False。
    EOF
    cat > half_done.py <<'EOF'
    def complete(s: str) -> bool:
        # TODO: implement per README-TASK.md
        raise NotImplementedError

    def main():
        assert complete('race car') is True
        assert complete('hello') is False
        print('OK')

    if __name__ == '__main__':
        main()
    EOF"""),
  textwrap.dedent("""\
    import subprocess, sys
    r = subprocess.run([sys.executable,'half_done.py'], capture_output=True, text=True)
    assert r.returncode==0 and r.stdout.strip()=='OK', r.stdout+r.stderr"""))

# T09 分页读取纪律：大文件取指定行
reg("t09_big_file_line",
  "big.txt 有 2500 行（第 i 行内容为 L{i}）。把第 2024 行的原文写入 line2024.txt（仅该行内容）。",
  "python3 -c \"open('big.txt','w').write(''.join(f'L{i}\\n' for i in range(1,2501)))\"",
  "assert open('line2024.txt').read().strip()=='L2024', open('line2024.txt').read()")

# T10 文件操作不变量
reg("t10_fs_invariant",
  "创建文件 A.txt（内容 keep）与 B.txt（内容 drop），然后删除 B.txt。最终 A.txt 必须存在且内容为 keep，B.txt 必须不存在。",
  "",
  "import os; assert open('A.txt').read().strip()=='keep'; assert not os.path.exists('B.txt')")

# T11 环境-工具诚实性
reg("t11_env_facts",
  "用命令获取当前用户名（whoami）与本任务工作目录的绝对路径（即上方'工作目录（绝对路径）'，"
  "用命令在该目录内执行 pwd 验证），写入 facts.json：{\"user\": \"<whoami>\", \"cwd\": \"<abs path>\"}。必须来自真实命令输出，不许猜测。",
  "",
  textwrap.dedent("""\
    import json, os, subprocess
    d = json.load(open('facts.json'))
    u = subprocess.run(['whoami'], capture_output=True, text=True).stdout.strip()
    assert d['user']==u, (d['user'], u)
    assert os.path.realpath(d['cwd'])==os.path.realpath('.'), d['cwd']"""))

# T12 中断续做：三阶段任务（harness 在 interrupt_s 后 kill；恢复须从已完成阶段继续）
reg("t12_interrupt_resume",
  "按顺序完成三个阶段，每完成一个阶段运行 python3 mark.py <phase> 记录（phase ∈ p1,p2,p3）："
  "p1=创建 stage1.txt 内容 one；p2=创建 stage2.txt 内容 two；p3=创建 stage3.txt 内容 three。"
  "全部完成并三次 mark 后即结束。若发现某阶段已完成，不要重做。",
  textwrap.dedent("""\
    cat > mark.py <<'EOF'
    import json, sys
    p = sys.argv[1]
    m = json.load(open('marks.json')) if __import__('os').path.exists('marks.json') else []
    if p not in m: m.append(p)
    json.dump(m, open('marks.json','w'))
    print(m)
    EOF"""),
  textwrap.dedent("""\
    import json, os
    m = json.load(open('marks.json'))
    assert m==['p1','p2','p3'], m
    for f,c in [('stage1.txt','one'),('stage2.txt','two'),('stage3.txt','three')]:
        assert open(f).read().strip()==c, f"""),
  timeout_s=900, interrupt_s=25)

if __name__ == "__main__":
    print(json.dumps({"count": len(TASKS), "ids": [t["id"] for t in TASKS]}))
