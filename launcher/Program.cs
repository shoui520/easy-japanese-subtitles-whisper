using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // Developer launcher lives in <repository>/build/launcher, not a release package.
        string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", ".."));
        string python = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(python))
        {
            MessageBox.Show("Setup is needed before the app can start.\n\nRun scripts\\setup-dev.ps1 in the project folder, then open Easy Japanese Subtitles again.\n\nSee README.md for setup instructions.", "Easy Japanese Subtitles", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        try
        {
            string logDir = Path.Combine(root, ".app-data", "logs");
            Directory.CreateDirectory(logDir);
            string logPath = Path.Combine(logDir, "startup-" + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + ".log");
            using (StreamWriter log = new StreamWriter(logPath))
            using (Process process = new Process())
            {
                log.AutoFlush = true;
                process.StartInfo = new ProcessStartInfo(python, "-m app.main")
                {
                    WorkingDirectory = root,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                process.StartInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
                process.StartInfo.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
                process.OutputDataReceived += (sender, e) => { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
                process.ErrorDataReceived += (sender, e) => { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                if (process.ExitCode != 0)
                    MessageBox.Show("The app could not finish starting or closed unexpectedly.\n\nCheck that scripts\\setup-dev.ps1 completed and Microsoft Edge WebView2 Runtime is installed.\n\nDetails were saved to:\n" + logPath, "Easy Japanese Subtitles", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        catch (Exception error)
        {
            MessageBox.Show("The app could not start. Check that the folder is writable and the private Python environment exists.\n\n" + error.Message, "Easy Japanese Subtitles", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
