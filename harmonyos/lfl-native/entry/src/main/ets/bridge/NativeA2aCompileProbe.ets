import {
  createA2AServer, OnDataCallback, RequestContext, Server
} from '@kit.AgentFrameworkKit';

/**
 * SDK Release 26 native HMS A2A compiler proof only.
 *
 * Constructing this object is harmless. The method below is NEVER invoked
 * by the PoC UI. Calling it would create an A2A server and would require
 * separately qualified platform identity, backend Task CAS, an AgentCard,
 * runtime eligibility and explicit owner approval. No A2A server is started.
 */
export class NativeA2aCompileProbe {
  public createOnlyIfExplicitlyAuthorized(
    card: Parameters<typeof createA2AServer>[0]
  ): Server {
    const onData: OnDataCallback = (_method: string, _context: RequestContext): void => {
      // Intentionally NO real host request, Task dispatch or provider call.
    };
    return createA2AServer(card, onData);
  }
}
