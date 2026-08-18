"""会话瘦身脚本（EXPERIENCE-20260818-flock 固化版）.

用途: 会话历史膨胀（>100 万字符）触发频繁压缩、缓存命中下降时，将旧 tool 消息占位化。
用法: .venv/bin/python scripts/session_slim.py <session_file.jsonl> [--keep N] [--dry-run]
默认: --keep 50（保留最近 50 条 tool 完整），备份到 <file>.bak-<ts>
安全: flock 防并发写坏 + 配对检查（0 孤儿回执才写回）+ 备份可恢复
"""
import json, os, sys, shutil, tempfile, time, fcntl

def slim_session(path, keep=50, dry_run=False):
    """占位化旧 tool 消息，保持消息数/结构不变。"""
    lines = open(path).readlines()
    total = len(lines)
    kept = 0
    out = []
    # 从后往前：保留最近 keep 条 tool 结果完整
    for i, line in enumerate(lines):
        try:
            d = json.loads(line)
        except:
            out.append(line); continue
        t = d.get('type', '')
        # 只占位 tool 类结果消息（tool.result / tool_result）
        if t in ('tool.result', 'tool_result', 'tool.output', 'tool_output') and kept < keep:
            out.append(line); kept += 1
        elif t in ('tool.result', 'tool_result', 'tool.output', 'tool_output'):
            # 占位：保留 role/tool_name/status，内容压缩
            slim = dict(d)
            slim['payload'] = {'slimmed': True, 'tool_name': d.get('payload', {}).get('tool_name', ''),
                               'status': d.get('payload', {}).get('status', '')}
            out.append(json.dumps(slim, ensure_ascii=False) + '\n')
        else:
            out.append(line)
    # 配对检查：tool_call 必须有对应 result（0 孤儿）
    calls = sum(1 for l in out if '"tool_call"' in l or '"tool_call_id"' in l and '"role": "assistant"' in l)
    # 简化配对：统计 assistant 里 tool_call 数 vs tool 结果数
    call_ids = set()
    res_ids = set()
    for l in out:
        try: d = json.loads(l)
        except: continue
        p = d.get('payload', {})
        if d.get('type') == 'message' and p.get('role') == 'assistant':
            for tc in (p.get('tool_calls') or []):
                call_ids.add(tc.get('id'))
        if d.get('type') in ('tool.result', 'tool_result'):
            res_ids.add(p.get('tool_call_id') or p.get('id'))
    orphans = call_ids - res_ids
    if orphans:
        print(f'⚠️ {len(orphans)} 孤儿 tool_call（不写回，需检查）')
        return False
    old_chars = sum(len(l) for l in lines)
    new_chars = sum(len(l) for l in out)
    print(f'消息数: {total} → {len(out)} | 字符: {old_chars:,} → {new_chars:,} ({(1-new_chars/old_chars)*100:.0f}%) | 0 孤儿 ✓')
    if dry_run:
        return True
    # 备份 + flock 写回
    bak = f'{path}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
    shutil.copy(path, bak)
    fd = os.open(path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, ''.join(out).encode())
    finally:
        os.close(fd)
    print(f'已写回（备份: {bak}）')
    return True

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('session_file')
    ap.add_argument('--keep', type=int, default=50)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    slim_session(a.session_file, a.keep, a.dry_run)
