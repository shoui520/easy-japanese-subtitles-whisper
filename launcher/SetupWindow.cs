using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class SetupWindow : Form
{
    private readonly string root, logPath;
    private readonly Label stage = new Label(), detail = new Label();
    private readonly ProgressBar progress = new ProgressBar();
    private readonly Button retry = new Button(), cancel = new Button(), logButton = new Button();
    private readonly ComboBox compute = new ComboBox();
    private readonly TextBox liveLog = new TextBox();
    private CancellationTokenSource cancellation;
    internal Func<string,Action<string>,CancellationToken,Task<string>> PrepareRuntime;
    private bool running, cancelled;
    private string setupError;
    internal static readonly string[] Profiles = {"cu128", "xpu", "rocm", "cpu"};
    private ProcessJob job;
    private readonly object logLock = new object();

    public SetupWindow(string project) {
        root = project;
        PrepareRuntime=(profile,report,token)=>RuntimeBootstrap.Prepare(root,profile,report,token);
        Directory.CreateDirectory(Path.Combine(root, ".app-data", "logs"));
        logPath = Path.Combine(root, ".app-data", "logs", "setup-" + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + ".log");
        Text = "Setting up Easy Japanese Subtitles";
        Font = new Font("Meiryo", 10);
        ClientSize = new Size(720, 560);
        BackColor = Color.FromArgb(244,245,240);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        stage.SetBounds(24,24,520,32); stage.Text = "Preparing your app";
        stage.Font = new Font(Font, FontStyle.Bold);
        detail.SetBounds(24,65,520,95);
        detail.Text = "Required components will be downloaded into the app folder. This window closes when setup finishes.";
        progress.SetBounds(24,175,520,18); progress.Style = ProgressBarStyle.Continuous;
        compute.SetBounds(24,215,290,32); compute.DropDownStyle = ComboBoxStyle.DropDownList;
        compute.Items.AddRange(new object[]{"CUDA (NVIDIA)", "XPU (Intel)", "ROCm / HIP (AMD)", "CPU"}); compute.SelectedIndex = 0;
        compute.SelectedIndexChanged += (s,e) => {
            if(!running) detail.Text = compute.SelectedIndex==2
                ? "AMD ROCm 7.2.1 requires Windows 11, a supported Radeon/Ryzen GPU and AMD's compatible driver (26.2.2). Setup installs its own Python 3.12 and AMD libraries."
                : compute.SelectedIndex==1
                ? "Intel XPU requires a supported Intel Arc/Core Ultra GPU and an up-to-date Intel graphics driver. Setup downloads the matching runtime; no separate toolkit is needed."
                : "Required components will be downloaded into the app folder. This window closes when setup finishes.";
        };
        try {
            var ready=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(root,".runtime","ready.json")));
            object selected;
            if(ready.TryGetValue("compute",out selected)) {
                int index=Array.IndexOf(Profiles,Convert.ToString(selected));
                if(index>=0)compute.SelectedIndex=index;
            }
        } catch(IOException) {} catch(ArgumentException) {}
        retry.SetBounds(324,215,105,32); retry.Text = "Set up";
        cancel.SetBounds(439,215,105,32); cancel.Text = "Close";
        logButton.SetBounds(24,265,150,32); logButton.Text = "View setup log";
        Controls.AddRange(new Control[]{stage,detail,progress,compute,retry,cancel,logButton});
        liveLog.SetBounds(24,310,672,225); liveLog.Multiline=true; liveLog.ReadOnly=true;
        liveLog.ScrollBars=ScrollBars.Both; liveLog.WordWrap=false;
        liveLog.Font=new Font("Meiryo",9);
        Controls.Add(liveLog);
        retry.Click += async (s,e) => await Install();
        cancel.Click += (s,e) => { if (running) { cancelled=true; if(cancellation!=null)cancellation.Cancel(); if(job!=null)job.Dispose(); } else Close(); };
        logButton.Click += (s,e) => { if(File.Exists(logPath)) Process.Start(new ProcessStartInfo(logPath){UseShellExecute=true}); };
        FormClosing += (s,e) => { cancelled=true; if(cancellation!=null)cancellation.Cancel(); if(job!=null)job.Dispose(); };
    }

    private void Report(string line) {
        if (line == null) return;
        lock(logLock) File.AppendAllText(logPath, line + Environment.NewLine);
        if(!IsDisposed && IsHandleCreated) BeginInvoke((Action)(()=>{
            if(IsDisposed)return;
            if(liveLog.TextLength>120000)liveLog.Text=liveLog.Text.Substring(liveLog.TextLength-60000);
            liveLog.AppendText(line+Environment.NewLine);
        }));
        if (!line.StartsWith("SETUP ") || IsDisposed) return;
        try {
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(line.Substring(6));
            if(data.ContainsKey("error")) setupError=Convert.ToString(data["error"]);
            BeginInvoke((Action)(() => {
                if (IsDisposed || !running) return;
                stage.Text = Convert.ToString(data["stage"]);
                detail.Text = Convert.ToString(data["detail"]);
                object fraction;
                if (data.TryGetValue("progress", out fraction) && fraction != null) {
                    progress.Style = ProgressBarStyle.Continuous;
                    progress.Value = (int)Math.Max(0, Math.Min(100, Convert.ToDouble(fraction)*100));
                } else progress.Style = ProgressBarStyle.Marquee;
            }));
        } catch(Exception) { /* Unstructured installer output remains in the log. */ }
    }

    private async Task Install() {
        if (running) return;
        running=true; cancelled=false; setupError=null; retry.Enabled=false; compute.Enabled=false; cancel.Text="Cancel";
        cancellation=new CancellationTokenSource();
        stage.Text="Preparing your app"; detail.Text="Checking and downloading required components";
        progress.Style=ProgressBarStyle.Marquee;
        try {
            string python=await PrepareRuntime(Profiles[compute.SelectedIndex],Report,cancellation.Token);
            cancellation.Token.ThrowIfCancellationRequested();
            string script=Path.Combine(root,"scripts","setup-runtime.py");
            Report("Starting Python setup: "+python+"\nScript: "+script);
            using(var process=new Process()) {
                process.StartInfo=new ProcessStartInfo(python,"-u \""+script+"\" "+Profiles[compute.SelectedIndex]+" --wait-for-start") {
                    WorkingDirectory=root, UseShellExecute=false, CreateNoWindow=true,
                    RedirectStandardInput=true, RedirectStandardOutput=true, RedirectStandardError=true,
                    StandardOutputEncoding=System.Text.Encoding.UTF8, StandardErrorEncoding=System.Text.Encoding.UTF8
                };
                process.StartInfo.EnvironmentVariables.Remove("PYTHONPATH");
                process.StartInfo.EnvironmentVariables.Remove("PYTHONHOME");
                process.StartInfo.EnvironmentVariables["PYTHONNOUSERSITE"]="1";
                process.StartInfo.EnvironmentVariables["PYTHONUTF8"]="1";
                process.OutputDataReceived+=(s,e)=>Report(e.Data);
                process.ErrorDataReceived+=(s,e)=>Report(e.Data);
                process.Start();
                job=new ProcessJob(process);
                process.BeginOutputReadLine(); process.BeginErrorReadLine();
                process.StandardInput.WriteLine("GO"); process.StandardInput.Close();
                await Task.Run(()=>process.WaitForExit());
                if(cancelled)throw new OperationCanceledException();
                if(process.ExitCode!=0 || !File.Exists(Path.Combine(root,".runtime","ready.json")))
                    throw new InvalidOperationException(setupError ?? "Setup could not finish. Check your connection and free disk space, then retry. The setup log has details.");
            }
            running=false;
            if(!IsDisposed) { DialogResult=DialogResult.OK; Close(); }
        } catch(Exception error) {
            if(!IsDisposed) {
                stage.Text=cancelled?"Setup cancelled":"Setup needs attention";
                detail.Text=cancelled?"Resume when ready. Downloaded files and completed installation steps are kept.":error.Message;
                progress.Style=ProgressBarStyle.Continuous; progress.Value=0;
            }
        } finally {
            if(job!=null){job.Dispose();job=null;}
            if(cancellation!=null){cancellation.Dispose();cancellation=null;}
            running=false;
            if(!IsDisposed){retry.Text="Resume";retry.Enabled=true;compute.Enabled=true;cancel.Text="Close";}
        }
    }
}
