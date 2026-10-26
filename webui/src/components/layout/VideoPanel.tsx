import { useCallback, useEffect, useRef, useState } from "react";
import { videoApi, videoJson, type VideoConfig, type VideoJob, type VideoStatus } from "../../core/video-api";
import "./video-panel.css";

const labels: Record<VideoJob["status"], string> = {
  queued: "等待启动", running: "正在生成", done: "已生成", failed: "生成失败", cancelled: "已取消", interrupted: "执行中断",
};
const active = (job: VideoJob) => job.status === "queued" || job.status === "running";

export function VideoPanel() {
  const [status, setStatus] = useState<VideoStatus | null>(null);
  const [config, setConfig] = useState<VideoConfig | null>(null);
  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState("640x384");
  const [frames, setFrames] = useState(56);
  const [steps, setSteps] = useState(8);
  const [seed, setSeed] = useState(-1);
  const [refs, setRefs] = useState<Array<{ id: string; name: string }>>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  const refresh = useCallback(async (initial = false) => {
    try {
      const next = await videoApi<VideoStatus>("", { cache: "no-store" });
      if (!next.config || !Array.isArray(next.missing) || !Array.isArray(next.jobs)) throw new Error("视频管理入口尚未就绪，请更新 Web 服务。");
      if (!mounted.current) return;
      setStatus(next);
      if (initial) setConfig(next.config);
      setError("");
    } catch (exc) {
      if (mounted.current) setError(String(exc instanceof Error ? exc.message : exc));
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh(true);
    return () => { mounted.current = false; };
  }, [refresh]);
  const running = status?.jobs.some(active) ?? false;
  const dirty = !!config && !!status && JSON.stringify(config) !== JSON.stringify(status.config);
  useEffect(() => {
    if (!running) return;
    // Schedule the next poll after completion, so slow requests cannot overlap.
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      await refresh();
      if (!stopped) timer = setTimeout(() => void tick(), 2500);
    };
    timer = setTimeout(() => void tick(), 2500);
    return () => { stopped = true; clearTimeout(timer); };
  }, [running, refresh]);

  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  }

  const patchConfig = (patch: Partial<VideoConfig>) => setConfig((current) => current ? { ...current, ...patch } : current);
  return (
    <section className="v2-video-panel" aria-label="MiniMax H3 视频生成">
      <div className="v2-provider-subhead"><strong>MiniMax H3 · 本地视频</strong><button type="button" className="v2-btn ghost" disabled={busy} onClick={() => void refresh(true)}>刷新</button></div>
      <p>输入描述，可添加参考图。生成的视频包含原生音频，任务在后台继续执行。</p>
      {error && <div className="v2-panel-error" role="alert">{error}</div>}
      {message && <div className="v2-provider-ok" role="status">{message}</div>}
      {!status || !config ? <p>正在读取视频配置…</p> : <>
        {status.missing.length > 0 && <div className="v2-video-missing">尚缺少：{status.missing.join("、")}。补齐后刷新即可。</div>}
        <details open={!status.prerequisites_ready}>
          <summary>模型与运行配置</summary>
          <p>填写模型目录内的组件路径。H3 编码器与普通聊天模型不同。</p>
          {([
            ["diffusion_model", "H3 视频权重（Ref2VA）"], ["text_encoder", "H3 专用文本编码器"],
            ["video_vae", "视频 VAE"], ["audio_vae", "音频 VAE"],
          ] as const).map(([key, label]) => <label key={key}>{label}<input value={config[key]} onChange={(event) => patchConfig({ [key]: event.target.value })} /></label>)}
          <label className="v2-video-check"><input type="checkbox" checked={config.text_encoder_cpu} onChange={(event) => patchConfig({ text_encoder_cpu: event.target.checked })} />文本编码器使用 CPU</label>
          <label className="v2-video-check"><input type="checkbox" checked={config.offload_to_cpu} onChange={(event) => patchConfig({ offload_to_cpu: event.target.checked })} />允许后端按需卸载到 CPU</label>
          <label>超时（秒）<input type="number" min={60} max={86400} value={config.timeout_s} onChange={(event) => patchConfig({ timeout_s: Number(event.target.value) })} /></label>
          <button type="button" className="v2-btn ghost" disabled={busy} onClick={() => void perform(async () => {
            const next = await videoApi<VideoStatus>("/config", videoJson("PUT", { expected_version: status.version, config }));
            setStatus(next); setConfig(next.config); setMessage("视频配置已保存，新任务使用该配置。");
          })}>保存视频配置</button>
        </details>
        <form onSubmit={(event) => {
          event.preventDefault();
          void perform(async () => {
            const [width, height] = size.split("x").map(Number);
            const job = await videoApi<VideoJob>("/jobs", videoJson("POST", { prompt, width, height, frames, steps, seed, references: refs.map((ref) => ref.id) }));
            setStatus((current) => current ? { ...current, jobs: [job, ...current.jobs.filter((item) => item.id !== job.id)] } : current);
            setMessage("视频任务已启动。"); await refresh();
          });
        }}>
          <label>视频模型<select defaultValue="minimax-h3"><option value="minimax-h3">MiniMax H3 · 本地视频 / 原生音频</option></select></label>
          <label>视频描述<textarea rows={3} maxLength={16000} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="描述人物、动作、镜头和声音；参考图可用 <Picture 1> 指代" /></label>
          <div className="v2-video-grid">
            <label>画面<select value={size} onChange={(event) => setSize(event.target.value)}><option value="256x256">256 × 256 预览</option><option value="640x384">640 × 384 横屏</option><option value="384x640">384 × 640 竖屏</option><option value="960x544">960 × 544 横屏</option><option value="544x960">544 × 960 竖屏</option></select></label>
            <label>时长（24 fps）<select value={frames} onChange={(event) => setFrames(Number(event.target.value))}><option value={22}>约 0.9 秒预览</option><option value={56}>约 2.3 秒</option><option value={124}>约 5.2 秒</option><option value={243}>约 10.1 秒</option><option value={345}>约 14.4 秒</option></select></label>
            <label>采样步数<input type="number" min={1} max={100} value={steps} onChange={(event) => setSteps(Number(event.target.value))} /></label>
            <label>种子（-1 随机）<input type="number" min={-1} max={2147483647} value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
          </div>
          <label>参考图片（最多 9 张）<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy || refs.length >= 9} onChange={(event) => {
            const file = event.target.files?.[0]; event.target.value = "";
            if (!file) return;
            void perform(async () => {
              const data = new FormData(); data.append("file", file);
              const uploaded = await videoApi<{ id: string }>("/references", { method: "POST", body: data });
              setRefs((current) => [...current, { id: uploaded.id, name: file.name }]);
            });
          }} /></label>
          {refs.map((ref, index) => <div className="v2-video-reference" key={ref.id}>Picture {index + 1} · {ref.name}<button type="button" className="v2-btn ghost" onClick={() => setRefs((current) => current.filter((item) => item.id !== ref.id))}>移除</button></div>)}
          {dirty && <p role="status">配置已修改，请先保存视频配置。</p>}
          <button className="v2-btn ghost" type="button" disabled={busy} onClick={() => { setSize("256x256"); setFrames(22); setSteps(4); }}>使用低分辨率预览参数</button>
          <button className="v2-btn" type="submit" disabled={busy || running || dirty || !status.prerequisites_ready || !prompt.trim()}>生成视频</button>
          <p className="v2-video-note">首次建议短片、低分辨率。视频会与聊天模型共享内存，生成时间取决于本机负载。</p>
        </form>
        <div aria-live="polite">{status.jobs.map((job) => <article className="v2-video-job" key={job.id}>
          <strong>{labels[job.status]}</strong><p>{job.request.prompt}</p>
          {job.error && <p role="alert">{job.error}</p>}
          {active(job) && <button type="button" className="v2-btn ghost" disabled={busy} onClick={() => void perform(async () => {
            await videoApi(`/jobs/${job.id}/cancel`, { method: "POST" }); setMessage("已请求取消，正在等待后端退出。"); await refresh();
          })}>取消生成</button>}
          {job.status === "done" && <><video controls playsInline preload="metadata" src={`/api/v1/video/jobs/${job.id}/files/output`} /><a href={`/api/v1/video/jobs/${job.id}/files/output`} download={`minimax-h3-${job.id}.mp4`}>下载视频</a></>}
          <div className="v2-video-links"><a href={`/api/v1/video/jobs/${job.id}/files/request`} target="_blank" rel="noreferrer">生成参数与回执</a><a href={`/api/v1/video/jobs/${job.id}/files/log`} target="_blank" rel="noreferrer">完整日志</a></div>
        </article>)}</div>
      </>}
    </section>
  );
}
