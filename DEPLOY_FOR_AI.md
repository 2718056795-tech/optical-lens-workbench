# 在另一台电脑部署 V10.0.0

在 Windows 10/11 x64 的可写目录克隆本仓库或完整解压。保留 app 目录结构。需要 Python 3.11 x64（记录版本 3.11.9）、.NET Framework 4.6.2 或以上、WebView2 Runtime，建议为依赖及运行档案预留 10 GB。运行库由目标电脑安装，首次部署需联网。仓库省略了历史镜头、用户提供的资料、本机路径和环境缓存。

## 补齐玻璃目录

从用户授权的 V10 原目录复制以下文件至克隆目录的对应位置。需要时先创建父目录，保留文件原始字节。

| 目标路径 | 来源 |
| --- | --- |
| app/data/catalogs/CDGM202609.AGF | 原 V10 的 data/catalogs/CDGM202609.AGF，或从成都光明下载 CDGM-ZEMAX202609.AGF 后按目标名保存 |
| app/data/supplier_reference/CDGM202609.xlsx | 原 V10 的 data/supplier_reference/CDGM202609.xlsx，或从成都光明下载同名 Excel |
| app/data/catalogs/CDGM202609_metadata.json | 原 V10 的 data/catalogs/CDGM202609_metadata.json，或用配套 AGF 和 Excel 生成 |
| app/data/catalogs/legacy/CDGM.AGF | 原 V10 的 data/catalogs/legacy/CDGM.AGF，或从本仓库 app/vendor/AutoLens-e58db32f3a0b07f25861b5839a45970f77b5c947/deeplens/material/CDGM.AGF 原样复制 |
| app/data/catalogs/legacy/SCHOTT.AGF | 原 V10 的 data/catalogs/legacy/SCHOTT.AGF |
| app/data/catalogs/legacy/materials_data.json | 原 V10 的 data/catalogs/legacy/materials_data.json |

成都光明的同一页面提供 202609 版 AGF 和 Excel。下载安装后用 Get-FileHash -Algorithm SHA256 核对 environment_snapshot.json 的 required_catalog_files。若厂商文件更新导致 SHA 不同，请从已授权的 V10 原目录取冻结文件。legacy/SCHOTT.AGF 和 legacy/materials_data.json 与本包 AutoLens 内的同名文件字节不同。肖特官网可查玻璃目录，当前 V10 预检需要上表的冻结版本。 [成都光明配套下载页](https://www.cdgmgd.com/go.htm?k=di_ruan_hua_dian_yu_zhi_jian&url=goods) · [肖特光学玻璃](https://www.schott.com/en-us/products/optical-glass)

如果已有配套 AGF 和 Excel，但缺 metadata JSON，在仓库根目录用 Python 3.11 运行以下命令。脚本读两个源文件，写入本地 JSON，完成后仍需核对快照的 SHA。

~~~powershell
& 'C:\实际路径\python.exe' -B .\app\prepare_cdgm_metadata.py
~~~

## 部署与启动

默认 both 模式使用 PyTorch 2.6.0+cu118，需要兼容 NVIDIA GPU 与驱动。只需要 Optiland CPU 时，显式选择 optiland-cpu 模式，使用 PyTorch 2.6.0+cpu。

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1 -PythonExe 'C:\实际路径\python.exe' -Mode both
# 仅验证 Optiland CPU 时
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1 -PythonExe 'C:\实际路径\python.exe' -Mode optiland-cpu
~~~

脚本在仓库根目录建立 .venv，按 requirements-baseline.txt 安装全局运行库，在 app/vendor/native_runtime 安装私有 SciPy 1.16.3，在 app/vendor/analysis_runtime 安装 PyVista 0.46.4 和 Scooby 0.10.2。-ConfigureOnly 跳过依赖安装，仍运行预检。

预检核对系统组件、版本、玻璃目录 SHA 和官方源码完整性，在独立进程检查私有 SciPy 来源、CPU 数学与 Optiland 非优化追迹。both 模式还要通过 AutoLens 独立导入和真实 GPU 运算。查看 deployment_check.json 和退出码。status 为 ready 时运行根目录 start.cmd。启动检查会重查版本、系统、玻璃目录和源文件，复用上次成功的计算探针。环境或驱动变更后请再运行 deploy.ps1。出现不可获得的锁定版本或依赖冲突时，记录具体错误再评估版本，避免自动升级内核。

入口为 app/EXE/初始结构优化工作台-V10.0.0.exe，监听 127.0.0.1:8682，WebView2 宿主存储目录为本机 LocalAppData 下的 LensOptWorkbenchV10。部署通过后生成指向本机 .venv 的 app/python.path。历史结果用旧电脑的“保存全部结果”导出，再在新电脑“读取档案”。

本地就绪探针覆盖上述能力。需要继续验证真实优化、分析和导出时，单独用短预算示例检查。原生 3D 仍需实测。冻结组合的 VTK 9.7.1 超出 PyVista 0.46.4 声明的兼容上限，预检将其标为未实测。

## 源码与安装入口

- AutoLens 固定提交 e58db32f3a0b07f25861b5839a45970f77b5c947，随仓库的 88 文件按上游 manifest 核验。Optiland 固定 0.6.3，安装后核验 wheel 中的源码记录。 [AutoLens 固定提交](https://github.com/AI4Optics/AutoLens/tree/e58db32f3a0b07f25861b5839a45970f77b5c947) · [Optiland 0.6.3](https://pypi.org/project/optiland/0.6.3/)
- 如需重建 EXE，使用 app/EXE打包源码/build.ps1。该脚本使用 Windows .NET Framework 64 位 csc，并从同目录 vendor/WebView2 读取固定 SDK 1.0.4258.31 的 lib/net462、runtimes/win-x64/native、LICENSE.txt 与 NOTICE.txt。SDK 和目标机器运行所需的 Evergreen Runtime 各自独立。 [WebView2 SDK 1.0.4258.31](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4258.31) · [微软 WebView2 Runtime 部署](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution)
- [Python 3.11.9](https://www.python.org/downloads/release/python-3119/) · [PyTorch cu118 索引](https://download.pytorch.org/whl/cu118/) · [PyTorch CPU 索引](https://download.pytorch.org/whl/cpu/) · [Microsoft VC++ Runtime](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist) · [NVIDIA 驱动](https://www.nvidia.com/Download/index.aspx)
