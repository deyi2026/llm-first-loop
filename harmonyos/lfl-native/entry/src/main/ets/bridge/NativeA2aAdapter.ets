/**
 * Thin native wiring for the offline A2A adapter (compile-qualified only).
 *
 * The RequestContext-to-projection extraction is deliberately INJECTED: the
 * exact Task/identity surface of the installed HMS SDK must be qualified on
 * a real device before any default projector can be honest. The server
 * factory call stays behind explicit separate authorization; this class
 * never registers a live A2A server (A2A-QUALIFICATION hard gates).
 */

import type { RequestContext } from '@kit.AgentFrameworkKit';
import { A2aDispatchCoordinator } from './A2aDispatch';
import type { RequestContextProjection } from './A2aDispatch';

export type ContextProjector =
  (method: string, context: RequestContext) => RequestContextProjection;

/** Fail-closed default projector: no real SDK surface is qualified yet. */
export function refuseProjector(method: string, _context: RequestContext): RequestContextProjection {
  throw new Error('real_sdk_context_surface_not_qualified');
}

export class NativeA2aAdapter {
  private readonly coordinator: A2aDispatchCoordinator;
  private readonly projector: ContextProjector;

  constructor(coordinator: A2aDispatchCoordinator, projector: ContextProjector) {
    this.coordinator = coordinator;
    this.projector = projector;
  }

  /** Shape-compatible with the SDK OnDataCallback contract; never throws. */
  public readonly onData = (method: string, context: RequestContext): void => {
    let projection: RequestContextProjection;
    try {
      projection = this.projector(method, context);
    } catch (_err) {
      return; // Unqualified surface: fail closed without surfacing to the Kit.
    }
    this.coordinator.handle(projection).catch((_err: Error) => {
      // Dispatch outcomes are already fail-closed decisions.
    });
  };

  /**
   * Compile-only gate mirroring NativeA2aCompileProbe: an actual
   * createA2AServer call additionally requires device, signing, developer
   * eligibility and platform authorization receipts.
   */
  public compileOnlyServerFactoryProbe(authorized: boolean): void {
    if (authorized !== true) {
      throw new Error('a2a_server_registration_requires_separate_authorization');
    }
  }
}
