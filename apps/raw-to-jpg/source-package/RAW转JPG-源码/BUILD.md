# 开发与构建

本项目使用 Windows 自带的 C# 编译器和 .NET Framework 4.x WPF 图像组件，没有第三方运行库依赖。

## 环境

- Windows 10 / Windows 11（64 位）
- .NET Framework 4.8（系统自带）
- Windows 上的 PowerShell

## 构建

在源码目录打开 PowerShell：

```powershell
.\build.ps1
```

生成结果位于源码目录上一级的 `outputs\RAW转JPG.exe`。

## 运行测试

```powershell
.\test.ps1
```

测试会临时生成普通图片和带内嵌 JPEG 的模拟 RAW 文件，验证格式转换、缩放、重名策略、递归扫描以及 RAW 回退逻辑。

## 目录

- `src\Raw2JpgStudio.cs`：WinForms 界面、文件列表、预览和交互
- `src\ConversionCore.cs`：解码、方向修正、缩放、JPEG 编码和输出命名
- `src\app.manifest`：DPI 感知及兼容性设置
- `tests\ConversionCoreTests.cs`：无第三方依赖的自动测试
- `tools\make_icon.py`：重新生成应用图标的 Pillow 脚本
- `build\app.ico`：已生成的程序图标

## RAW 解码说明

完整 RAW 解码由 Windows Imaging Component（WIC）及系统安装的 RAW 编解码器完成。程序额外实现了内嵌 JPEG 扫描回退，因此即使系统没有某款相机的 RAW 解码器，也能从支持该结构的 RAW 文件中提取预览。
