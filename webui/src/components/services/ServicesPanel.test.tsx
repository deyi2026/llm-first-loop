import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { ServicesPanel } from "./ServicesPanel";
import { fetchServicesStatus, type ServicesStatusInfo } from "../../core/api";

vi.mock("../../core/api", () => ({ fetchServicesStatus: vi.fn() }));

const HEAD = "7ad21715d0c34523414091fab9518c80463b3486";
const fakeStatus = (options: { stableGen?: number | null; restartRequired?: boolean; stableMatches?: boolean } = {}): ServicesStatusInfo => {
  const stableGen = options.stableGen === undefined ? 315 : options.stableGen;
  const restartRequired = options.restartRequired ?? false;
  const stableMatches = options.stableMatches ?? (stableGen === 319);
  return {
    deployment: { generation: 319, git_head: HEAD, code_root: "/release", runtime_root: "/runtime", deployment_id: "demo", webui_artifact_sha256: "hash" },
    services: {
      feishu: {
        live: { manifest_present: true, pid: 91278, pid_alive: true, git_head: restartRequired ? "old-head" : HEAD, started_at: "2026-10-25T08:33:01Z" },
        stable: stableGen === null ? null : { action_id: "svc-example", target: "feishu", generation: stableGen, succeeded_at: "2026-10-24T23:51:40Z", git_head: stableMatches ? HEAD : null, matches_desired_generation: stableMatches },
        restart_required: restartRequired,
        reasons: restartRequired ? ["live_git_head_mismatch"] : [],
      },
    },
    server_tz_offset_minutes: 480,
  };
};

describe("ServicesPanel distinguishes live identity from stable receipt", () => {
  beforeEach(() => vi.mocked(fetchServicesStatus).mockReset());
  afterEach(() => cleanup());

  it("319 desired + 315 stable: green live identity, amber receipt lag, no forced restart", async () => {
    vi.mocked(fetchServicesStatus).mockResolvedValue(fakeStatus());
    render(<ServicesPanel />);
    const card = await screen.findByTestId("service-card-feishu");
    expect(within(card).getByText(/✓ 运行代码与 desired 一致/)).toBeInTheDocument();
    expect(within(card).getByTestId("stable-lag-feishu")).toHaveTextContent("差 4 代");
    expect(within(card).getByTestId("stable-lag-feishu")).toHaveTextContent("无需仅为追平代次重启");
    expect(within(card).queryByText(/⚠ 运行身份需核验\/重启/)).not.toBeInTheDocument();
    expect(within(card).getByText(/不声明 git 身份/)).toBeInTheDocument();
  });

  it("stable reaches desired: explicitly confirms receipt convergence", async () => {
    vi.mocked(fetchServicesStatus).mockResolvedValue(fakeStatus({ stableGen: 319 }));
    render(<ServicesPanel />);
    const card = await screen.findByTestId("service-card-feishu");
    expect(within(card).getByText(/✓ 稳定回执已追平 desired/)).toBeInTheDocument();
    expect(within(card).queryByTestId("stable-lag-feishu")).not.toBeInTheDocument();
  });

  it("stale live and stale receipt: does not recommend ignoring runtime mismatch", async () => {
    vi.mocked(fetchServicesStatus).mockResolvedValue(fakeStatus({ restartRequired: true }));
    render(<ServicesPanel />);
    const card = await screen.findByTestId("service-card-feishu");
    expect(within(card).getByText(/⚠ 运行身份需核验\/重启/)).toBeInTheDocument();
    expect(within(card).getByTestId("stable-lag-feishu")).toHaveTextContent("运行身份需单独核验");
    expect(within(card).queryByText(/无需仅为追平代次重启/)).not.toBeInTheDocument();
  });

  it("missing stable receipt: no false converged badge", async () => {
    vi.mocked(fetchServicesStatus).mockResolvedValue(fakeStatus({ stableGen: null }));
    render(<ServicesPanel />);
    const card = await screen.findByTestId("service-card-feishu");
    await waitFor(() => expect(within(card).getByText(/尚无成功重启回执/)).toBeInTheDocument());
    expect(within(card).queryByText(/✓ 稳定回执已追平 desired/)).not.toBeInTheDocument();
  });

  it("shows wheel identities for all three services without claiming a Git revision", async () => {
    const data = fakeStatus({ stableGen: 319 });
    data.deployment = { generation: 319, runtime_root: "/lfl", deployment_id: "wheel-deploy",
      artifact_kind: "wheel_release", version: "0.6.42", wheel_sha256: "abcdef012345".repeat(5) + "abcd",
      release_dir: "/lfl/releases/LFL-0.6.42", webui_artifact_sha256: "hash" };
    const service = data.services.feishu;
    service.live = { manifest_present: true, pid: 123, release_version: "0.6.42",
      wheel_sha256: data.deployment.wheel_sha256, git_head: "unknown" };
    service.stable = { action_id: "actual-success", target: "all", generation: 319,
      succeeded_at: "2026-11-08T11:44:36Z", git_head: null, matches_desired_generation: true,
      artifact_kind: "wheel_release", version: "0.6.42", wheel_sha256: data.deployment.wheel_sha256 };
    data.services = { web: service, feishu: service, learning: service };
    vi.mocked(fetchServicesStatus).mockResolvedValue(data);
    render(<ServicesPanel />);
    for (const name of ["web", "feishu", "learning"]) {
      const card = await screen.findByTestId("service-card-" + name);
      expect(within(card).getAllByText(/wheel 0.6.42 · SHA abcdef012345/).length).toBeGreaterThan(0);
      expect(within(card).queryByText(/unknown/)).not.toBeInTheDocument();
    }
  });

  it("renders server clock independently of browser timezone", async () => {
    const offset = vi.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(-480);
    try {
      const data = fakeStatus();
      data.services.feishu.live.started_at = "2026-11-08T11:44:36Z";
      vi.mocked(fetchServicesStatus).mockResolvedValue(data);
      render(<ServicesPanel />);
      const card = await screen.findByTestId("service-card-feishu");
      expect(within(card).getByText(/19:44:36/)).toBeInTheDocument();
    } finally {
      offset.mockRestore();
    }
  });
});
