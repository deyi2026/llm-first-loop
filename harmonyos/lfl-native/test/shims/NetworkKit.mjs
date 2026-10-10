const scenarios = [];
export const observed = [];
export function queueScenario(s) { scenarios.push(s); }
export const http = {
  RequestMethod: { POST: 'POST', GET: 'GET' },
  createHttp() {
    const scenario = scenarios.shift() ?? {};
    const handlers = new Map();
    let destroyed = false;
    return {
      on(name, cb) { handlers.set(name, cb); },
      off(name, _cb) { handlers.delete(name); },
      destroy() { destroyed = true; },
      async request(url, opts) {
        observed.push({url, opts, mode:'json'});
        return {responseCode:scenario.code ?? 200, result:scenario.body ?? '{}'};
      },
      async requestInStream(url, opts) {
        observed.push({url, opts, mode:'stream'});
        if (scenario.throw) throw new Error('fixture_connection_failed');
        for (const bytes of (scenario.chunks ?? [])) {
          await Promise.resolve();
          if (destroyed) break;
          handlers.get('dataReceive')?.(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
        }
        if (!destroyed && scenario.end !== false) handlers.get('dataEnd')?.();
        return scenario.code ?? 200;
      }
    };
  }
};
