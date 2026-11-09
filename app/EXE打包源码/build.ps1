param([string]$OutputName='初始结构优化工作台-V10.0.0.exe')
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$v2Root=Split-Path $root -Parent
$sdk=Join-Path $root 'vendor\WebView2'
$framework='C:\Windows\Microsoft.NET\Framework64\v4.0.30319'
$outDir=Join-Path $v2Root 'EXE'
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$exe=Join-Path $outDir $OutputName
$core=Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.Core.dll'
$forms=Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.WinForms.dll'
$loader=Join-Path $sdk 'runtimes\win-x64\native\WebView2Loader.dll'
$compilerArgs=@('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',('/out:'+$exe),('/win32manifest:'+(Join-Path $root 'source\app.manifest')),('/reference:'+$core),('/reference:'+$forms),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Core.dll','/reference:System.Net.Http.dll','/reference:System.Web.Extensions.dll','/reference:System.IO.Compression.dll',('/resource:'+$core+',Microsoft.Web.WebView2.Core.dll'),('/resource:'+$forms+',Microsoft.Web.WebView2.WinForms.dll'),('/resource:'+$loader+',WebView2Loader.dll'),('/resource:'+(Join-Path $sdk 'LICENSE.txt')+',LICENSE.txt'),('/resource:'+(Join-Path $sdk 'NOTICE.txt')+',NOTICE.txt'),(Join-Path $root 'source\Host.cs'))
& (Join-Path $framework 'csc.exe') @compilerArgs
if($LASTEXITCODE -ne 0){throw '编译失败'}
Get-Item -LiteralPath $exe | Select-Object Name,Length
