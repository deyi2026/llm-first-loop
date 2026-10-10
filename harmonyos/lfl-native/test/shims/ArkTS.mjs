export const util = {
  TextDecoder: {
    create(encoding, options) {
      const decoder = new TextDecoder(encoding, options);
      return { decodeToString(bytes, opts) { return decoder.decode(bytes, opts); } };
    }
  }
};
