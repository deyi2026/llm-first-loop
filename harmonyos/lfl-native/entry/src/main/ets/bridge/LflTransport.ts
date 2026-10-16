import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { artifactId, LflSseParser } from './StreamProtocol';
import type { LflEvent, LflHistory, LflStreamStatus } from './StreamProtocol';

export interface HttpReply {
  status: number;
  text: string;
  headers?: Record<string, string>;
}

export interface ArtifactVerification {
  sha256: string;
  sizeBytes: number;
}

export type EventReceiver = (event: LflEvent) => void;

/**
 * Thin HarmonyOS Network Kit adapter. Every request is scoped to an explicit
 * HTTPS origin, and the streaming request is never reused for stop/status.
 */
export class LflTransport {
  private activeStream: http.HttpRequest | null = null;

  public static origin(url: string): string {
    const value = url.trim().replace(/\/$/, '');
    // No implicit localhost/production origin and no userinfo in URLs.
    if (!/^https:\/\/[^\s/@?#:]+(?::[0-9]+)?$/.test(value)) {
      throw new Error('explicit_https_origin_required');
    }
    return value;
  }

  private headers(token: string): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };
    if (token.trim()) {
      headers['Authorization'] = 'Bearer ' + token.trim();
    }
    return headers;
  }

  public async json(
    origin: string, token: string, path: string, method: http.RequestMethod,
    body: string = ''
  ): Promise<HttpReply> {
    const request = http.createHttp();
    try {
      const reply = await request.request(LflTransport.origin(origin) + path, {
        method: method,
        header: this.headers(token),
        extraData: body,
        connectTimeout: 10000,
        readTimeout: 20000
      });
      return {
        status: reply.responseCode,
        text: reply.result.toString(),
        headers: reply.header as Record<string, string>
      };
    } finally {
      request.destroy();
    }
  }

  public async readStatus(origin: string, token: string, sid: string): Promise<LflStreamStatus> {
    const reply = await this.json(origin, token,
      '/api/v1/chat/stream/status?session_id=' + encodeURIComponent(sid),
      http.RequestMethod.GET);
    if (reply.status !== 200) {
      throw new Error('status_HTTP_' + reply.status.toString());
    }
    const result = JSON.parse(reply.text) as LflStreamStatus;
    if (typeof result.running !== 'boolean') {
      throw new Error('invalid_status_contract');
    }
    return result;
  }

  public async readHistory(origin: string, token: string, sid: string): Promise<LflHistory> {
    const reply = await this.json(origin, token,
      '/api/v1/sessions/' + encodeURIComponent(sid) + '/messages?limit=20&offset=0',
      http.RequestMethod.GET);
    if (reply.status !== 200) {
      throw new Error('history_HTTP_' + reply.status.toString());
    }
    const result = JSON.parse(reply.text) as LflHistory;
    if (result.session_id !== sid || !Array.isArray(result.messages)) {
      throw new Error('history_identity_mismatch');
    }
    return result;
  }

  public async cancel(origin: string, token: string, payload: string): Promise<HttpReply> {
    return this.json(origin, token, '/api/v1/chat/cancel',
      http.RequestMethod.POST, payload);
  }

  /**
   * Verified artifact hydration (CONTRACT "Artifact semantics"): calls the
   * authenticated backend endpoint and returns the receipted SHA256/size.
   * A 404 (unknown, foreign-scope or malformed) and a bad header contract
   * both fail closed; the caller keeps the unverified_ref label on failure.
   */
  public async verifyArtifact(origin: string, token: string, ref: string): Promise<ArtifactVerification> {
    const id: string = artifactId(ref);
    const reply: HttpReply = await this.json(origin, token,
      '/api/v1/artifacts/' + id, http.RequestMethod.GET);
    if (reply.status !== 200) {
      throw new Error('artifact_HTTP_' + reply.status.toString());
    }
    const headers: Record<string, string> = reply.headers ?? {};
    const sha256: string = String(headers['x-artifact-sha256'] ?? '');
    const sizeRaw: string = String(headers['x-artifact-size-bytes'] ?? '');
    const sizeBytes: number = Number(sizeRaw);
    if (!/^[0-9a-f]{64}$/.test(sha256) || !/^[0-9]+$/.test(sizeRaw) ||
      !Number.isFinite(sizeBytes) || sizeBytes < 0) {
      throw new Error('invalid_artifact_verification_headers');
    }
    return { sha256: sha256, sizeBytes: sizeBytes };
  }

  public disconnectSubscription(): void {
    // Only stops the local subscriber, not LFL's background Run.
    if (this.activeStream !== null) {
      this.activeStream.destroy();
    }
  }

  public async stream(
    origin: string, token: string, payload: string, receiver: EventReceiver
  ): Promise<void> {
    if (this.activeStream !== null) {
      throw new Error('subscriber_already_active');
    }
    const request: http.HttpRequest = http.createHttp();
    this.activeStream = request;
    const parser: LflSseParser = new LflSseParser();
    const decoder = util.TextDecoder.create('utf-8', { ignoreBOM: true });
    let ended: boolean = false;
    let decodingError: string = '';
    let signalEnd: () => void = () => {};
    const endSignal: Promise<void> = new Promise<void>((resolve) => {
      signalEnd = resolve;
    });
    const onData = (chunk: ArrayBuffer): void => {
      if (decodingError) {
        return;
      }
      try {
        const text = decoder.decodeToString(new Uint8Array(chunk), { stream: true });
        for (const event of parser.push(text)) {
          receiver(event);
        }
      } catch (_err) {
        decodingError = 'invalid_stream_frame';
        signalEnd();
      }
    };
    const onEnd = (): void => {
      ended = true;
      try {
        const tail = decoder.decodeToString(new Uint8Array(0), { stream: false });
        for (const event of parser.push(tail)) {
          receiver(event);
        }
      } catch (_err) {
        decodingError = 'invalid_final_frame';
      }
      signalEnd();
    };
    request.on('dataReceive', onData);
    request.on('dataEnd', onEnd);
    try {
      const statusCode: number = await request.requestInStream(
        LflTransport.origin(origin) + '/api/v1/chat/stream',
        {
          method: http.RequestMethod.POST,
          header: {
            ...this.headers(token),
            'Accept': 'text/event-stream'
          },
          extraData: payload,
          connectTimeout: 10000,
          readTimeout: 120000
        }
      );
      if (statusCode !== 200) {
        throw new Error('stream_HTTP_' + statusCode.toString());
      }
      // Some SDK versions resolve requestInStream when headers arrive;
      // wait for actual dataEnd instead of treating that as terminal.
      // Always clear the watchdog after dataEnd. A still-live timeout would
      // pin the host test process (and waste a device timer) for two minutes.
      let watchdog: number = -1;
      try {
        await Promise.race([
          endSignal,
          new Promise<void>((resolve) => {
            watchdog = setTimeout(resolve, 120000);
          })
        ]);
      } finally {
        if (watchdog !== -1) {
          clearTimeout(watchdog);
        }
      }
      if (decodingError) {
        throw new Error(decodingError);
      }
      if (!ended || !parser.hasTerminal()) {
        throw new Error('stream_ended_without_terminal_receipt');
      }
    } finally {
      request.off('dataReceive', onData);
      request.off('dataEnd', onEnd);
      request.destroy();
      this.activeStream = null;
    }
  }
}
