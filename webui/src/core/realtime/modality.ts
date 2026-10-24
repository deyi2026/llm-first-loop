// M3：可访问性与降级模式（`T-M3-3`，RTM-A11Y-01/02/05、CAP-03、CAP-09、CAP-13）。
//
// - 桌面与移动端均可操作；麦克风/共享不可用时**降级为文字/截图入口**（不静默失效）；
// - 界面须**标明实际采用的链路**（原生实时 vs 级联）；「观察项」不得当作已支持能力；
// - 移动端**未实测**时不得承诺后台连续音频（RTM-A11Y-05）。

export type ModalityMode = "voice_full" | "voice_text_fallback" | "screenshot_fallback";

export interface AvailabilityFacts {
  mic: boolean;
  screenShare: boolean;
}

export function resolveModality(facts: AvailabilityFacts): ModalityMode {
  if (facts.mic && facts.screenShare) {
    return "voice_full";
  }
  if (facts.mic) {
    return "voice_text_fallback";
  }
  return "screenshot_fallback";
}

export interface ChainDisclosure {
  /** 实际采用的链路：原生实时 / 级联（ASR→LLM→TTS）。 */
  cascade: boolean;
  label: string;
  mobileBackgroundContinuous: boolean;
}

/** 链路声明：按**实测能力**判定并界面标明；观察项不标为已支持（CAP-09/13）。 */
export function chainDisclosure(options: {
  cascade: boolean;
  mobileBackgroundMeasured?: boolean;
}): ChainDisclosure {
  const label = options.cascade ? "级联语音链路（ASR→LLM→TTS）" : "原生实时语音链路";
  return {
    cascade: options.cascade,
    label,
    mobileBackgroundContinuous: options.mobileBackgroundMeasured === true,
  };
}

/** 首次价值提示（可访问性：键盘可达的降级入口说明）。 */
export const FALLBACK_HINT =
  "语音不可用时，可继续使用文字输入或上传截图；键盘用户可按 Ctrl/⌘+Shift+V 切换语音。";