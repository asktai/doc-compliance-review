# 【已弃用】结构校验请改用： python scripts/check.py
#
# 弃用原因（安全）：原脚本须依赖 PowerShell 的执行策略绕过参数才能运行，
# 属策略绕过；且 .ps1 一旦被篡改即等于可执行任意代码。新的 check.py 为纯 Python 实现：
#   - 无需 PowerShell、不绕过任何执行策略
#   - 跨平台一致（Windows / macOS / Linux）
#   - 额外提供脚本完整性指纹校验（python check.py --verify / --sign）
#   - 额外提供缓存清理（python check.py --clean）
# 本文件仅为兼容旧文档中的引用而保留，不再包含任何执行体，也不会被自动调用。

Write-Host "[已弃用] check.ps1 已由 check.py 取代，请运行： python scripts/check.py"
exit 2
