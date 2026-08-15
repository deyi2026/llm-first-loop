// 运行时编译 metal_tensor 模块测试（llama.cpp 张量 API 探针同款依赖）
import Metal
import Foundation

guard let dev = MTLCreateSystemDefaultDevice() else {
    print("FAIL: no default Metal device"); exit(1)
}
print("device: \(dev.name)")

func tryCompile(_ name: String, _ src: String) {
    do {
        let lib = try dev.makeLibrary(source: src, options: nil)
        print("OK: \(name) 编译成功")
    } catch {
        print("FAIL: \(name) -> \(error.localizedDescription)")
    }
}

// 1. metal_stdlib（对照组，应成功）
tryCompile("metal_stdlib", """
#include <metal_stdlib>
using namespace metal;
kernel void t(device float* o [[buffer(0)]], uint i [[thread_position_in_grid]]) { o[i] = 1.0; }
""")

// 2. metal_tensor 模块（llama.cpp 张量 API 需要）
tryCompile("metal_tensor", """
#include <metal_tensor>
using namespace metal;
kernel void t(device mtl_tensor* o [[buffer(0)]], uint i [[thread_position_in_grid]]) {
    // 最小张量操作
    mtl::tensor t1 = mtl::make_tensor(o, 0);
    t1[i] = 1.0f;
}
""")

// 3. metal_types 模块
tryCompile("metal_types", """
#include <metal_types>
kernel void t(device float* o [[buffer(0)]], uint i [[thread_position_in_grid]]) { o[i] = 1.0; }
""")
