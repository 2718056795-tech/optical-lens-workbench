# 初始结构优化工作台 V10

Windows 光学初始结构设计工具。输入焦距、F 数、视场和镜片条件后，可选择 AutoLens 或 Optiland 生成并优化结构，也可载入 SEQ / ZMX 或既有结果档案。工作台提供光路、点列图、MTF、处方与指标对照，支持导出 ZMX、SEQ 和 JSON。

本版包含 V10 的参数布局与同行输入对齐修复。运行条件和玻璃目录准备步骤见 [部署说明](DEPLOY_FOR_AI.md)。

## 使用

1. 克隆仓库到可写的 Windows x64 目录，准备 Python 3.11 x64 和 Microsoft Edge WebView2 Runtime。
2. 按部署说明准备玻璃目录，运行 `deploy.ps1` 创建项目自己的环境。默认双内核模式要求兼容的 NVIDIA GPU；仅使用 Optiland 时可选择 CPU 模式。
3. 部署检查通过后运行 `start.cmd`。宿主是 `app/EXE/初始结构优化工作台-V10.0.0.exe`。

已有结果可先在原电脑用「保存全部结果」存到文件夹，再在新环境点击「读取档案」。

## 源码

- `app/web` 包含界面，`app` 下的 Python 文件包含工作台服务与分析、导入和导出适配。
- `app/EXE打包源码` 包含 Windows 宿主及构建脚本。重建宿主需要 Microsoft.Web.WebView2 SDK 1.0.4258.31，准备方法见部署说明。
- AutoLens 固定提交 `e58db32f3a0b07f25861b5839a45970f77b5c947`，保留上游许可证和源码校验清单。Optiland 0.6.3 随部署安装。

厂商玻璃目录、Python 环境和本机运行数据在部署机器上管理。
