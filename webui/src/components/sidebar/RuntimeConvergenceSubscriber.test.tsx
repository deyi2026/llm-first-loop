import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RuntimeConvergenceSubscriber, type RuntimeConvergenceSnapshot } from "./RuntimeConvergenceStrip";

const mocks = vi.hoisted(() => ({ subscribe: vi.fn(), fetch: vi.fn(), unsubscribe: vi.fn() }));
vi.mock("../../core/coordinationBoard", () => ({ subscribeCoordinationBoard: mocks.subscribe, fetchCoordinationBoard: mocks.fetch }));
vi.mock("../../core/authSession", () => ({ isAuthRequired: () => false, subscribeAuthRequired: () => () => {} }));
afterEach(cleanup);
it("subscribes to the existing board poller without an independent request", () => {
  let listener: (body: { runtime_convergence: RuntimeConvergenceSnapshot } | null) => void = () => {};
  mocks.subscribe.mockImplementation(fn => { listener = fn; return mocks.unsubscribe; });
  const view = render(<RuntimeConvergenceSubscriber />);
  act(() => listener({ runtime_convergence: { desired_generation: 7, desired_git_head: "aaaaaaa", desired_version: null,
    services: {}, cli: { state: "not_running", processes: [], uncertain: 0 } } }));
  expect(screen.getByText(/gen 7/)).toBeTruthy();
  expect(mocks.fetch).not.toHaveBeenCalled();
  act(() => listener(null));
  expect(screen.getByText(/数据待刷新/)).toBeTruthy();
  view.unmount();
  expect(mocks.unsubscribe).toHaveBeenCalledOnce();
});
