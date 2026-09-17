using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class SetupWindow : Form
{
    private readonly string root, logPath;
    private readonly Label stage = new Label(), detail = new Label();
    private readonly ProgressBar progress = new ProgressBar();
    private readonly Button retry = new Button(), cancel = new Button(), logButton = new Button();
    private readonly ComboBox compute = new ComboBox();
    private bool running, cancelled;
    private ProcessJob job;
    private readonly object logLock = new object();

    public SetupWindow(string project) {
        root = project;
        Directory.CreateDirectory(Path.Combine(root, ".app-data", "logs"));
        logPath = Path.Combine(root, ".app-data", "logs", "setup-" + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + ".log");
        Text = "Setting up Easy Japanese Subtitles";
        Font = new Font("Meiryo", 10);
        ClientSize = new Size(570, 300);
        BackColor = Color.FromArgb(244,245,240);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        stage.SetBounds(24,24,520,32); stage.Text = "Preparing your app";
        stage.Font = new Font(Font, FontStyle.Bold);
        detail.SetBounds(24,65,520,65);
        detail.Text = "Required components will be downloaded into the app folder. This window closes when setup finishes.";
        progress.SetBounds(24,145,520,18); progress.Style = ProgressBarStyle.Continuous;
        compute.SetBounds(24,185,290,32); compute.DropDownStyle = ComboBoxStyle.DropDownList;
        compute.Items.AddRange(new object[]{"CUDA runtime (NVIDIA)", "CPU runtime"}); compute.SelectedIndex = 0;
        retry.SetBounds(324,185,105,32); retry.Text = "Set up";
        cancel.SetBounds(439,185,105,32); cancel.Text = "Close";
        logButton.SetBounds(24,235,150,32); logButton.Text = "View setup log";
        Controls.AddRange(new Control[]{stage,detail,progress,compute,retry,cancel,logButton});
        retry.Click += async (s,e) => await Install();
        cancel.Click += (s,e) => { if (running) { cancelled=true; if(job!=null)job.Dispose(); } else Close(); };
        logButton.Click += (s,e) => { if(File.Exists(logPath)) Process.Start(new ProcessStartInfo(logPath){UseShellExecute=true}); };
        FormClosing += (s,e) => { cancelled=true; if(job!=null)job.Dispose(); };
    }

    private void Report(string line) {
        if (line == null) return;
        lock(logLock) File.AppendAllText(logPath, line + Environment.NewLine);
        if (!line.StartsWith("SETUP ") || IsDisposed) return;
        try {
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(line.Substring(6));
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
        running=true; cancelled=false; retry.Enabled=false; compute.Enabled=false; cancel.Text="Cancel";
        stage.Text="Preparing your app"; detail.Text="Checking and downloading required components";
        progress.Style=ProgressBarStyle.Marquee;
        try {
            string powershell=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
            string script=Path.Combine(root,"scripts","setup-private-runtime.ps1");
            using(var process=new Process()) {
                process.StartInfo=new ProcessStartInfo(powershell,"-NoProfile -ExecutionPolicy Bypass -File \""+script+"\" -Resume -WaitForStart -Compute "+(compute.SelectedIndex==0?"cu128":"cpu")) {
                    WorkingDirectory=root, UseShellExecute=false, CreateNoWindow=true,
                    RedirectStandardInput=true, RedirectStandardOutput=true, RedirectStandardError=true
                };
                process.StartInfo.EnvironmentVariables.Remove("PSModulePath");
                process.OutputDataReceived+=(s,e)=>Report(e.Data);
                process.ErrorDataReceived+=(s,e)=>Report(e.Data);
                process.Start();
                job=new ProcessJob(process);
                process.BeginOutputReadLine(); process.BeginErrorReadLine();
                process.StandardInput.WriteLine("GO"); process.StandardInput.Close();
                await Task.Run(()=>process.WaitForExit());
                if(cancelled)throw new OperationCanceledException();
                if(process.ExitCode!=0 || !File.Exists(Path.Combine(root,".runtime","ready.json")))
                    throw new InvalidOperationException("Setup could not finish. Check your connection and free disk space, then retry. The setup log has details.");
            }
            running=false;
            if(!IsDisposed) { DialogResult=DialogResult.OK; Close(); }
        } catch(Exception error) {
            if(!IsDisposed) {
                stage.Text=cancelled?"Setup cancelled":"Setup needs attention";
                detail.Text=cancelled?"You can retry when ready. Verified downloads are kept.":error.Message;
                progress.Style=ProgressBarStyle.Continuous; progress.Value=0;
            }
        } finally {
            if(job!=null){job.Dispose();job=null;}
            running=false;
            if(!IsDisposed){retry.Text="Retry";retry.Enabled=true;compute.Enabled=true;cancel.Text="Close";}
        }
    }
}
