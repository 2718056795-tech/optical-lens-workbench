using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Diagnostics;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("初始结构优化工作台")]
[assembly: AssemblyDescription("镜头初始结构自动设计 · 本地优化引擎 + WebView2 界面")]
[assembly: AssemblyVersion("10.0.0.0")]
[assembly: AssemblyFileVersion("10.0.0.0")]

internal static class Program
{
    internal static string StorageRoot;
    internal static string Assets;
    internal static string VerifyRoot;
    internal static int VerifyPort;
    internal static Process Engine;
    internal static bool AllowProcessCleanup;
    internal static int EnginePort = 8682;
    internal static string EngineUrl { get { return "http://127.0.0.1:" + EnginePort + "/"; } }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)]
    private static extern IntPtr LoadLibrary(string path);
    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] private static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    private static void EnableDpiAwareness(){try{if(SetProcessDpiAwarenessContext(new IntPtr(-4)))return;}catch(EntryPointNotFoundException){}SetProcessDPIAware();}

    [STAThread]
    private static void Main(string[] args)
    {
        foreach (string arg in args)
        {
            if (arg.StartsWith("--verify-root=")) VerifyRoot = Path.GetFullPath(arg.Substring(14));
            if (arg.StartsWith("--verify-port=")) int.TryParse(arg.Substring(14), out VerifyPort);
        }
        // An isolated validation instance must never attach to the user's backend.
        if (VerifyRoot != null)
            foreach (string arg in args)
                if (arg.StartsWith("--verify-engine-port="))
                {
                    int port;
                    if (int.TryParse(arg.Substring(21), out port) && port > 1024 && port < 65536) EnginePort = port;
                }
        EnableDpiAwareness();
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        try
        {
            StorageRoot = VerifyRoot ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LensOptWorkbenchV10");
            Directory.CreateDirectory(StorageRoot);
            Assets = Path.Combine(StorageRoot, "assets", Digest(ReadResource("WebView2Loader.dll")).Substring(0,16));
            Directory.CreateDirectory(Assets);
            Extract("LICENSE.txt", Path.Combine(Assets,"LICENSE.txt"));
            Extract("NOTICE.txt", Path.Combine(Assets,"NOTICE.txt"));
            Extract("WebView2Loader.dll", Path.Combine(Assets,"WebView2Loader.dll"));
            if (LoadLibrary(Path.Combine(Assets,"WebView2Loader.dll")) == IntPtr.Zero)
                throw new InvalidOperationException("无法载入窗口组件，错误码："+Marshal.GetLastWin32Error());
            AppDomain.CurrentDomain.AssemblyResolve += ResolveEmbeddedAssembly;
            Application.ApplicationExit += delegate { StopEngine(); };
            RunWindow();
        }
        catch(Exception ex) { ReportError(ex); }
    }
    private static Assembly ResolveEmbeddedAssembly(object sender, ResolveEventArgs args)
    {
        string name = new AssemblyName(args.Name).Name;
        if (name=="Microsoft.Web.WebView2.Core" || name=="Microsoft.Web.WebView2.WinForms")
            return Assembly.Load(ReadResource(name+".dll"));
        return null;
    }
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void RunWindow() { Application.Run(new ToolWindow()); }
    internal static void StopEngine()
    {
        try
        {
            if (!AllowProcessCleanup || Engine==null || Engine.HasExited) return;
            // Kill the python engine together with its optimization child processes.
            try { Process.Start(new ProcessStartInfo("taskkill","/PID "+Engine.Id+" /T /F"){CreateNoWindow=true,UseShellExecute=false}); } catch {}
            try { if(!Engine.WaitForExit(4000)) Engine.Kill(); } catch {}
        }
        catch {}
    }
    private static byte[] ReadResource(string name)
    {
        using(Stream stream=Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
        {
            if(stream==null) throw new FileNotFoundException("程序内部文件缺失："+name);
            using(var memory=new MemoryStream()){stream.CopyTo(memory);return memory.ToArray();}
        }
    }
    private static string Digest(byte[] bytes)
    {
        using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
    }
    private static void Extract(string name,string destination)
    {
        byte[] bytes=ReadResource(name);
        if(File.Exists(destination)&&Digest(File.ReadAllBytes(destination))==Digest(bytes))return;
        try {File.WriteAllBytes(destination,bytes);}
        catch(IOException) {if(!File.Exists(destination)||Digest(File.ReadAllBytes(destination))!=Digest(bytes))throw;}
    }
    internal static void ReportError(Exception error)
    {
        string detail=error.ToString();
        if(StorageRoot!=null) try {File.WriteAllText(Path.Combine(StorageRoot,"startup-error.txt"),detail);}catch{}
        if(VerifyRoot!=null) {Environment.ExitCode=1;return;}
        string message=error.GetType().Name == "WebView2RuntimeNotFoundException"
            ? "这台电脑尚未安装 Microsoft Edge WebView2 Runtime。\n\n安装该微软组件后即可打开本工具。\n下载页面：https://developer.microsoft.com/microsoft-edge/webview2/\n\n程序没有自动安装或修改系统组件。"
            : "工具未能启动："+error.Message+"\n\n详细信息已记录到："+StorageRoot;
        MessageBox.Show(message,"初始结构优化工作台",MessageBoxButtons.OK,MessageBoxIcon.Information);
    }
}

internal static class WindowSizing
{
    internal static Size Initial(Size available,double dpi){double scale=Math.Max(1,dpi/96.0);return new Size(Math.Max(1,Math.Min((int)Math.Round(1516*scale),(int)(available.Width*.92))),Math.Max(1,Math.Min((int)Math.Round(1000*scale),(int)(available.Height*.92))));}
    internal static Size Minimum(Size available,double dpi){double scale=Math.Max(1,dpi/96.0);return new Size(Math.Max(1,Math.Min((int)Math.Round(900*scale),(int)(available.Width*.85))),Math.Max(1,Math.Min((int)Math.Round(580*scale),(int)(available.Height*.85))));}
}

internal sealed class ToolWindow : Form
{
    private bool useRoundedRegion;
    [DllImport("user32.dll")]private static extern uint GetDpiForWindow(IntPtr hwnd);
    private double WindowDpi(){try{uint dpi=GetDpiForWindow(Handle);if(dpi>0)return dpi;}catch(EntryPointNotFoundException){}using(var g=Graphics.FromHwnd(Handle))return g.DpiX;}
    protected override void OnLoad(EventArgs e){base.OnLoad(e);Rectangle work=Screen.FromControl(this).WorkingArea;double dpi=WindowDpi();MinimumSize=WindowSizing.Minimum(work.Size,dpi);Size=WindowSizing.Initial(work.Size,dpi);Location=new Point(work.Left+(work.Width-Width)/2,work.Top+(work.Height-Height)/2);if(Program.VerifyRoot!=null)File.WriteAllText(Path.Combine(Program.VerifyRoot,"window-bounds.txt"),"dpi="+dpi+";work="+work+";bounds="+Bounds+";minimum="+MinimumSize);}
    protected override void WndProc(ref Message m)
    {
        if(m.Msg==0x02E0&&m.LParam!=IntPtr.Zero){int[] box=new int[4];Marshal.Copy(m.LParam,box,0,4);var next=Rectangle.FromLTRB(box[0],box[1],box[2],box[3]);double dpi=((long)m.WParam)&0xffff;var work=Screen.FromRectangle(next).WorkingArea;base.WndProc(ref m);MinimumSize=WindowSizing.Minimum(work.Size,dpi);if(WindowState==FormWindowState.Normal)Bounds=next;UpdateWindowRegion();return;}base.WndProc(ref m);
    }
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window,int attribute,ref int value,int size);
    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try
        {
            int corner=2,caption=0xFAF9F8,text=0x2C2420,border=0xE9E3E0,dark=0;
            int result=DwmSetWindowAttribute(Handle,33,ref corner,4);
            DwmSetWindowAttribute(Handle,20,ref dark,4);
            DwmSetWindowAttribute(Handle,35,ref caption,4);
            DwmSetWindowAttribute(Handle,36,ref text,4);
            DwmSetWindowAttribute(Handle,34,ref border,4);
            useRoundedRegion=result!=0;
            UpdateWindowRegion();
        }
        catch(DllNotFoundException){}
        catch(EntryPointNotFoundException){}
    }
    protected override void OnSizeChanged(EventArgs e)
    {
        base.OnSizeChanged(e);UpdateWindowRegion();
    }
    private void UpdateWindowRegion()
    {
        if(!useRoundedRegion || Width<40 || Height<40 || IsDisposed)return;
        Region previous=Region;
        if(WindowState==FormWindowState.Maximized)Region=null;
        else using(var outline=LoadingScreen.RoundedRectangle(new RectangleF(0,0,Width,Height),14))Region=new Region(outline);
        if(previous!=null)previous.Dispose();
    }
    private WebView2 web;
    private LoadingScreen loading;
    private readonly Stopwatch startup=Stopwatch.StartNew();
    private bool closeApproved,closingPending;
    private static bool Flag(Dictionary<string,object> value,string key){object field;return value.TryGetValue(key,out field)&&field is bool&&(bool)field;}
    private static bool Busy(Dictionary<string,object> value){return Flag(value,"running")||Flag(value,"analysis_running")||Flag(value,"file_operation_running");}
    private async Task<Dictionary<string,object>> ReadState(HttpClient http)
    {
        return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(await http.GetStringAsync(Program.EngineUrl+"api/state"));
    }
    private async void CloseSafely(object sender,FormClosingEventArgs e)
    {
        if(closeApproved)return;
        e.Cancel=true;if(closingPending)return;closingPending=true;
        try
        {
            if(Program.Engine==null||Program.Engine.HasExited||web.Source==null){Program.AllowProcessCleanup=true;closeApproved=true;Close();return;}
            using(var http=new HttpClient{Timeout=TimeSpan.FromSeconds(8)})
            {
                var state=await ReadState(http);
                if(Busy(state))
                {
                    if(MessageBox.Show(this,"当前仍有计算或档案读写。确定安全停止、等待保存完成后退出吗？","退出工作台",MessageBoxButtons.OKCancel,MessageBoxIcon.Question)!=DialogResult.OK)return;
                    if(Flag(state,"running"))
                    {
                        object id;state.TryGetValue("run_id",out id);
                        var json=new JavaScriptSerializer().Serialize(new {run_id=id});
                        await http.PostAsync(Program.EngineUrl+"api/stop",new StringContent(json,System.Text.Encoding.UTF8,"application/json"));
                    }
                    // Manual analyses may be cancelled; optimization is never force-killed.
                    if(Flag(state,"analysis_running"))
                    {
                        var cancel=await http.PostAsync(Program.EngineUrl+"api/host-cancel-analysis",new StringContent("{}",System.Text.Encoding.UTF8,"application/json"));
                        if(!cancel.IsSuccessStatusCode)throw new InvalidOperationException("分析尚未结束，请稍后再退出。");
                    }
                    var wait=Stopwatch.StartNew();Text="正在安全停止并保存…";
                    while(Busy(state))
                    {
                        if(wait.Elapsed>TimeSpan.FromSeconds(120))throw new InvalidOperationException("仍在等待安全保存，窗口保持打开。请稍后再次退出，不会强制终止优化。");
                        await Task.Delay(400);state=await ReadState(http);
                    }
                }
                var request=new JavaScriptSerializer().Serialize(new {backend_pid=Program.Engine.Id});
                var response=await http.PostAsync(Program.EngineUrl+"api/host-exit",new StringContent(request,System.Text.Encoding.UTF8,"application/json"));
                if(!response.IsSuccessStatusCode)throw new InvalidOperationException("后台尚未完成保存，未退出。请稍后重试。");
            }
            Program.AllowProcessCleanup=true;closeApproved=true;Close();
        }
        catch(Exception error)
        {
            if(Program.Engine!=null&&Program.Engine.HasExited){closeApproved=true;Close();return;}
            Text="初始结构优化工作台 · V10.0.0";
            MessageBox.Show(this,error.Message,"暂未退出",MessageBoxButtons.OK,MessageBoxIcon.Information);
        }
        finally{closingPending=false;}
    }
    internal ToolWindow()
    {
        Text="初始结构优化工作台 · V10.0.0";
        AutoScaleMode=AutoScaleMode.None;
        Rectangle startArea=Screen.FromPoint(Cursor.Position).WorkingArea;
        Size=WindowSizing.Initial(startArea.Size,96);MinimumSize=WindowSizing.Minimum(startArea.Size,96);
        StartPosition=FormStartPosition.Manual;Location=new Point(startArea.Left+(startArea.Width-Width)/2,startArea.Top+(startArea.Height-Height)/2);
        BackColor=Color.FromArgb(245,245,247);
        FormClosing+=CloseSafely;
        web=new WebView2 {Dock=DockStyle.Fill,Visible=false,DefaultBackgroundColor=BackColor};
        loading=new LoadingScreen {Dock=DockStyle.Fill};
        Controls.Add(web);
        Controls.Add(loading);
        loading.BringToFront();
        Shown+=async delegate
        {
            try
            {
                loading.Refresh();
                var options=new CoreWebView2EnvironmentOptions();
                if(Program.VerifyPort>0) options.AdditionalBrowserArguments="--remote-debugging-address=127.0.0.1 --remote-debugging-port="+Program.VerifyPort;
                var env=await CoreWebView2Environment.CreateAsync(null,Path.Combine(Program.StorageRoot,"profile"),options);
                await web.EnsureCoreWebView2Async(env);
                if(IsDisposed || Disposing)return;
                web.CoreWebView2.Settings.AreDevToolsEnabled=Program.VerifyRoot!=null;
                web.CoreWebView2.Settings.IsStatusBarEnabled=false;
                web.CoreWebView2.Settings.IsZoomControlEnabled=false;
                web.CoreWebView2.Settings.AreDefaultContextMenusEnabled=false;
                web.CoreWebView2.WebMessageReceived+=delegate(object sender,CoreWebView2WebMessageReceivedEventArgs message)
                {
                    Uri origin;
                    if(!Uri.TryCreate(message.Source,UriKind.Absolute,out origin)||origin.Scheme!="http"||origin.Host!="127.0.0.1"||origin.Port!=Program.EnginePort)return;
                    string request;
                    try{request=message.TryGetWebMessageAsString();}catch{return;}
                    const string prefix="choose-results-folder|";
                    if(request==null||!request.StartsWith(prefix))return;
                    string[] parts=request.Substring(prefix.Length).Split('|');
                    string id=parts[0],mode=parts.Length>1?parts[1]:"save",folder=null,error=null;
                    if(mode!="save"&&mode!="open")return;
                    if(id.Length>80||id.Any(c=>!char.IsLetterOrDigit(c)&&c!='-'))return;
                    web.CoreWebView2.PostWebMessageAsJson(new JavaScriptSerializer().Serialize(new {type="results-folder-opened",request_id=id}));
                    try
                    {
                        if(Program.VerifyRoot!=null)
                        {
                            if(mode=="open")folder=File.ReadAllText(Path.Combine(Program.VerifyRoot,"archive-folder.path")).Trim();
                            else{folder=Path.Combine(Program.VerifyRoot,"saved-results");Directory.CreateDirectory(folder);}
                        }
                        else using(var picker=new FolderBrowserDialog{Description=mode=="open"?"选择之前保存的光学优化结果档案文件夹":"选择保存优化结果的位置（会自动建立独立子文件夹）",ShowNewFolderButton=mode!="open"})
                            if(picker.ShowDialog(this)==DialogResult.OK)folder=picker.SelectedPath;
                    }
                    catch(Exception exc){error=exc.Message;}
                    web.CoreWebView2.PostWebMessageAsJson(new JavaScriptSerializer().Serialize(new {type="results-folder",request_id=id,path=folder,error=error}));
                };
                web.ZoomFactor=1.0;
                web.CoreWebView2.NavigationStarting+=delegate(object sender,CoreWebView2NavigationStartingEventArgs e)
                {
                    Uri uri;
                    if(Uri.TryCreate(e.Uri,UriKind.Absolute,out uri)&&uri.Host!="127.0.0.1"&&e.Uri!="about:blank"&&!e.Uri.StartsWith("blob:"+Program.EngineUrl))e.Cancel=true;
                };
                web.CoreWebView2.NewWindowRequested+=delegate(object sender,CoreWebView2NewWindowRequestedEventArgs e){e.Handled=true;};
                web.CoreWebView2.DownloadStarting+=delegate(object sender,CoreWebView2DownloadStartingEventArgs e)
                {
                    try
                    {
                        string name=Path.GetFileName(e.ResultFilePath);
                        if(string.IsNullOrWhiteSpace(name))name="lens.dat";
                        string path;
                        if(Program.VerifyRoot!=null){string dir=Path.Combine(Program.VerifyRoot,"downloads");Directory.CreateDirectory(dir);path=Path.Combine(dir,name);}
                        else using(var save=new SaveFileDialog{FileName=name,Filter="光学与数据文件|*.seq;*.zmx;*.json;*.csv;*.npz;*.png;*.log|所有文件|*.*",OverwritePrompt=true})
                        {
                            if(save.ShowDialog(this)!=DialogResult.OK){e.Cancel=true;e.Handled=true;return;}
                            path=save.FileName;
                        }
                        e.ResultFilePath=path;e.Handled=true;
                        var operation=e.DownloadOperation;
                        operation.StateChanged+=delegate
                        {
                            if(operation.State==CoreWebView2DownloadState.Completed)
                            {
                                if(Program.VerifyRoot!=null)File.AppendAllText(Path.Combine(Program.VerifyRoot,"download-events.log"),"Completed:"+path+Environment.NewLine);
                                if(!IsDisposed)web.CoreWebView2.PostWebMessageAsJson("{\"type\":\"download\",\"message\":\"文件保存完成\",\"failed\":false}");
                            }
                            else if(operation.State==CoreWebView2DownloadState.Interrupted)
                            {
                                if(Program.VerifyRoot!=null)File.AppendAllText(Path.Combine(Program.VerifyRoot,"download-events.log"),"Interrupted:"+operation.InterruptReason+Environment.NewLine);
                                if(!IsDisposed)web.CoreWebView2.PostWebMessageAsJson("{\"type\":\"download\",\"message\":\"保存未完成，请重试或选择其他位置\",\"failed\":true}");
                            }
                        };
                    }
                    catch(Exception error){e.Cancel=true;e.Handled=true;try{File.AppendAllText(Path.Combine(Program.StorageRoot,"download-error.log"),error.ToString());}catch{}}
                };
                // Start the local optimization engine, then navigate to it.
                bool ready=await Task.Run(new Func<bool>(WaitForEngine));
                if(IsDisposed || Disposing)return;
                if(!ready){Program.ReportError(new InvalidOperationException("优化引擎未能及时启动，详见引擎日志。"));Close();return;}
                web.Visible=true;
                web.SendToBack();
                loading.BringToFront();
                web.Source=new Uri(Program.EngineUrl);
                web.CoreWebView2.NavigationCompleted+=delegate(object sender,CoreWebView2NavigationCompletedEventArgs e2)
                {
                    if(IsDisposed || Disposing)return;
                    if(!e2.IsSuccess)
                    {
                        // Downloads cancel their navigation by design. A page error must not kill the application or its worker.
                        if(e2.WebErrorStatus!=CoreWebView2WebErrorStatus.OperationCanceled)
                            try{File.AppendAllText(Path.Combine(Program.StorageRoot,"navigation.log"),e2.WebErrorStatus+Environment.NewLine);}catch{}
                        loading.Visible=false;return;
                    }
                    loading.Visible=false;
                    BackColor=Color.FromArgb(245,245,247);
                };
            }
            catch(Exception ex){if(!IsDisposed && !Disposing){Program.ReportError(ex);Close();}}
        };
    }
    private bool WaitForEngine()
    {
        loading.Message="正在启动优化引擎…";
        StartEngine();
        using(var http=new HttpClient())
        {
            var deadline=DateTime.Now.AddSeconds(90);
            while(DateTime.Now<deadline)
            {
                try
                {
                    var response=http.GetAsync(Program.EngineUrl+"api/state").Result;
                    if(response.IsSuccessStatusCode)
                    {
                        var protocol=http.GetAsync(Program.EngineUrl+"api/analysis-protocol").Result;
                        if(!protocol.IsSuccessStatusCode || !protocol.Content.ReadAsStringAsync().Result.Contains("10.0.0"))
                            throw new InvalidOperationException("检测到旧版后台仍占用端口。请先结束任务并关闭旧版窗口，再打开 V10.0.0；不会替你终止旧任务。");
                        var details=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(protocol.Content.ReadAsStringAsync().Result);
                        object backend;
                        if(!details.TryGetValue("backend_pid",out backend)||Convert.ToInt32(backend)!=Program.Engine.Id)
                            throw new InvalidOperationException("V10已在另一窗口运行，请使用原窗口；未操作其任务。");
                        return true;
                    }
                }
                catch(InvalidOperationException){throw;}
                catch {}
                if(Program.Engine!=null && Program.Engine.HasExited)
                {
                    // Engine process died: a stale server may still answer later; keep polling a bit.
                    loading.Message="正在等待优化引擎…";
                }
                System.Threading.Thread.Sleep(400);
            }
        }
        return false;
    }
    private void StartEngine()
    {
        string exeDir=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string v2Root=Path.GetFullPath(Path.Combine(exeDir,".."));
        string appPy=Path.Combine(v2Root,"app.py");
        if(!File.Exists(appPy)) throw new FileNotFoundException("未找到优化服务 app.py："+appPy);
        string python=null;
        string preferred=Path.Combine(v2Root,"python.path");
        if(File.Exists(preferred)) python=File.ReadAllText(preferred).Trim();
        if(string.IsNullOrEmpty(python)||!File.Exists(python))
        {
            foreach(string cand in new[]{"D:\\python311\\python.exe","D:\\python\\python.exe",Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","Python","Python39","python.exe")})
                if(File.Exists(cand)){python=cand;break;}
        }
        if(string.IsNullOrEmpty(python)||!File.Exists(python))
        {
            // Last resort: python on PATH.
            python="python";
        }
        string logPath=Path.Combine(Program.StorageRoot,"engine.log");
        var psi=new ProcessStartInfo
        {
            FileName=python,
            Arguments="-B \""+appPy+"\" --no-browser --port "+Program.EnginePort,
            WorkingDirectory=v2Root,
            UseShellExecute=false,
            CreateNoWindow=true,
            RedirectStandardOutput=true,
            RedirectStandardError=true,
            StandardOutputEncoding=System.Text.Encoding.UTF8,
            StandardErrorEncoding=System.Text.Encoding.UTF8,
        };
        psi.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]="1";
        var proc=new Process {StartInfo=psi,EnableRaisingEvents=true};
        proc.OutputDataReceived+=delegate(object s,DataReceivedEventArgs e){if(e.Data==null)return;try{File.AppendAllText(logPath,e.Data+Environment.NewLine);}catch{}};
        proc.ErrorDataReceived+=delegate(object s,DataReceivedEventArgs e){if(e.Data==null)return;try{File.AppendAllText(logPath,e.Data+Environment.NewLine);}catch{}};
        proc.Start();
        proc.BeginOutputReadLine();
        proc.BeginErrorReadLine();
        Program.Engine=proc;
    }
}

// Native loading cover shown while the python optimization engine starts.
internal sealed class LoadingScreen : Control
{
    private readonly System.Windows.Forms.Timer animation;
    private float angle;
    private string message="正在启动光学工作台…";
    internal string Message {get{return message;}set{message=value;Invalidate();}}
    internal LoadingScreen()
    {
        BackColor=Color.FromArgb(245,245,247);
        SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.ResizeRedraw|ControlStyles.Opaque,true);
        animation=new System.Windows.Forms.Timer {Interval=30};
        animation.Tick+=delegate{angle=(angle+7)%360;Invalidate();};
    }
    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        if(animation==null)return;
        if(Visible)animation.Start();else animation.Stop();
    }
    internal static GraphicsPath RoundedRectangle(RectangleF r,float radius)
    {
        var p=new GraphicsPath();float d=radius*2;
        p.AddArc(r.Left,r.Top,d,d,180,90);p.AddArc(r.Right-d,r.Top,d,d,270,90);
        p.AddArc(r.Right-d,r.Bottom-d,d,d,0,90);p.AddArc(r.Left,r.Bottom-d,d,d,90,90);p.CloseFigure();return p;
    }
    protected override void OnPaintBackground(PaintEventArgs e){e.Graphics.Clear(BackColor);}
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);var g=e.Graphics;g.Clear(BackColor);g.SmoothingMode=SmoothingMode.AntiAlias;
        int cx=ClientSize.Width/2,cy=ClientSize.Height/2;
        using(var shadow=RoundedRectangle(new RectangleF(cx-230,cy-195,460,400),28))
        using(var card=RoundedRectangle(new RectangleF(cx-230,cy-205,460,400),28))
        using(var shade=new SolidBrush(Color.FromArgb(8,0,0,0)))
        using(var fill=new SolidBrush(Color.White))
        using(var stroke=new Pen(Color.FromArgb(224,227,233),1))
        {g.FillPath(shade,shadow);g.FillPath(fill,card);g.DrawPath(stroke,card);}
        var blue=Color.FromArgb(0,122,255);var muted=Color.FromArgb(110,119,133);
        using(var brand=new Font("Segoe UI",11,FontStyle.Regular,GraphicsUnit.Pixel))
        using(var title=new Font("Microsoft YaHei",26,FontStyle.Bold,GraphicsUnit.Pixel))
        using(var body=new Font("Microsoft YaHei",14,FontStyle.Regular,GraphicsUnit.Pixel))
        using(var note=new Font("Microsoft YaHei",12,FontStyle.Regular,GraphicsUnit.Pixel))
        using(var faint=new Pen(Color.FromArgb(211,222,237),2))
        using(var accent=new Pen(blue,3))
        using(var bluePen=new Pen(Color.FromArgb(0,122,255),2))
        using(var amber=new Pen(Color.FromArgb(255,149,0),2))
        {
            TextRenderer.DrawText(g,"OPTICAL WORKBENCH / LENS V10",brand,new Rectangle(0,cy-158,Width,24),blue,TextFormatFlags.HorizontalCenter|TextFormatFlags.NoPadding);
            // Simple lens glyph: two bent surfaces and two rays.
            g.DrawLine(faint,cx-58,cy-62,cx+58,cy-62);
            g.DrawArc(bluePen,cx-52,cy-118,26,112,300,60);
            g.DrawArc(bluePen,cx+26,cy-118,26,112,120,60);
            g.DrawLine(bluePen,cx-38,cy-109,cx+38,cy-109);
            g.DrawLine(amber,cx-40,cy-95,cx+40,cy-95);
            TextRenderer.DrawText(g,"初始结构优化工作台",title,new Rectangle(0,cy-33,Width,42),Color.FromArgb(32,36,44),TextFormatFlags.HorizontalCenter|TextFormatFlags.NoPadding);
            TextRenderer.DrawText(g,"双内核优化 · 多视图光学分析",note,new Rectangle(0,cy+13,Width,26),muted,TextFormatFlags.HorizontalCenter|TextFormatFlags.NoPadding);
            int textWidth=TextRenderer.MeasureText(message,body).Width,start=cx-(textWidth+40)/2;
            g.DrawEllipse(faint,start,cy+62,22,22);accent.StartCap=LineCap.Round;accent.EndCap=LineCap.Round;g.DrawArc(accent,start,cy+62,22,22,angle,105);
            TextRenderer.DrawText(g,message,body,new Point(start+36,cy+62),muted,TextFormatFlags.NoPadding);
            TextRenderer.DrawText(g,"完全离线运行 · 本机 Python 优化引擎",note,new Rectangle(0,Height-48,Width,24),muted,TextFormatFlags.HorizontalCenter|TextFormatFlags.NoPadding);
        }
    }
    protected override void Dispose(bool disposing)
    {
        if(disposing){animation.Stop();animation.Dispose();}
        base.Dispose(disposing);
    }
}
