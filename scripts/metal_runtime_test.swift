// Metal 运行时编译测试: 直接调 newLibraryWithSource (llama.cpp 同款 API)
import Metal
import Foundation

guard let dev = MTLCreateSystemDefaultDevice() else {
    print("FAIL: no default Metal device")
    exit(1)
}
print("device: \(dev.name) | families: \(dev.supportsFamily(.apple9) ? "apple9" : "") \(dev.supportsFamily(.apple8) ? "apple8" : "") \(dev.supportsFamily(.apple7) ? "apple7" : "") | maxWorkingSet: \(dev.recommendedMaxWorkingSetSize / 1073741824)GB")

let src = """
#include <metal_stdlib>
using namespace metal;
kernel void add_one(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]]) {
    out[i] = 1.0;
}
"""
do {
    let lib = try dev.makeLibrary(source: src, options: nil)
    print("OK: newLibraryWithSource 编译成功")
    let fn = lib.makeFunction(name: "add_one")!
    let pipeline = try dev.makeComputePipelineState(function: fn)
    let buf = dev.makeBuffer(length: 4, options: .storageModeShared)!
    let cq = dev.makeCommandQueue()!
    let cb = cq.makeCommandBuffer()!
    let enc = cb.makeComputeCommandEncoder()!
    enc.setComputePipelineState(pipeline)
    enc.setBuffer(buf, offset: 0, index: 0)
    enc.dispatchThreads(MTLSize(width: 1, height: 1, depth: 1), threadsPerThreadgroup: MTLSize(width: 1, height: 1, depth: 1))
    enc.endEncoding()
    cb.commit()
    cb.waitUntilCompleted()
    let v = buf.contents().load(as: Float.self)
    print(v == 1.0 ? "OK: kernel 执行成功 (result=1.0)" : "FAIL: kernel 结果 \(v)")
} catch {
    print("FAIL: newLibraryWithSource 抛错: \(error)")
    exit(1)
}
