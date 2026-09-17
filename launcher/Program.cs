using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using System.Threading;
using System.Security.Cryptography;
using System.Text;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        string root = ResolveRoot(AppDomain.CurrentDomain.BaseDirectory);
        string key;
        using(var hash=SHA256.Create()) key=BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(root.ToLowerInvariant()))).Replace("-", "");
        using(var instance=new Mutex(false, "Local\\EasyJapaneseSubtitles-"+key)) {
            bool acquired=false;
            try {
                try { acquired=instance.WaitOne(0); } catch(AbandonedMutexException) { acquired=true; }
                if(!acquired) { MessageBox.Show("The app or its setup is already running.", "Easy Japanese Subtitles"); return; }
                try { Run(root); }
                catch(Exception error) { MessageBox.Show("The app could not start setup. Check that the app folder is writable.\n\n"+error.Message, "Easy Japanese Subtitles", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            } finally { if(acquired)instance.ReleaseMutex(); }
        }
    }

    internal static string ResolveRoot(string directory)
    {
#if PORTABLE_RELEASE
        return Path.Combine(Path.GetFullPath(directory), "_internal");
#else
        return Path.GetFullPath(Path.Combine(directory, "..", ".."));
#endif
    }

    internal static bool RuntimeMatches(string root)
    {
        string config = Path.Combine(root, ".runtime", "venv", "pyvenv.cfg");
        if (!File.Exists(config)) return false;
        string expected = Path.GetFullPath(Path.Combine(root, ".runtime", "python"));
        foreach (string line in File.ReadAllLines(config)) {
            if (line.StartsWith("home = ", StringComparison.OrdinalIgnoreCase))
                return String.Equals(line.Substring(7).Trim().TrimEnd('\\'), expected.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase);
        }
        return false;
    }

    private static void Run(string root)
    {
        string python = Path.Combine(root, ".runtime", "venv", "Scripts", "pythonw.exe");
        string tools=Path.Combine(root,".runtime","ffmpeg","ffmpeg-9.0.1-essentials_build","bin");
        if (!RuntimeMatches(root) || !File.Exists(python) || !File.Exists(Path.Combine(root,".runtime","ready.json")) ||
            !File.Exists(Path.Combine(tools,"ffmpeg.exe")) || !File.Exists(Path.Combine(tools,"ffprobe.exe")))
        {
            Application.EnableVisualStyles();
            using(var setup = new SetupWindow(root)) {
                if(setup.ShowDialog()!=DialogResult.OK) return;
            }
            python=Path.Combine(root,".runtime","venv","Scripts","pythonw.exe");
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
                process.StartInfo.EnvironmentVariables.Remove("PYTHONHOME");
                process.StartInfo.EnvironmentVariables.Remove("PYTHONPATH");
                string runtimeDir = Path.Combine(root, ".runtime");
                string tempDir = Path.Combine(runtimeDir, "tmp");
                Directory.CreateDirectory(tempDir);
                process.StartInfo.EnvironmentVariables["TEMP"] = tempDir;
                process.StartInfo.EnvironmentVariables["TMP"] = tempDir;
                process.StartInfo.EnvironmentVariables["HF_HOME"] = Path.Combine(runtimeDir, "models", "huggingface");
                process.StartInfo.EnvironmentVariables["HF_HUB_CACHE"] = Path.Combine(runtimeDir, "models", "huggingface", "hub");
                process.StartInfo.EnvironmentVariables["XDG_CACHE_HOME"] = Path.Combine(runtimeDir, "cache");
                process.OutputDataReceived += (sender, e) => { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
                process.ErrorDataReceived += (sender, e) => { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                if (process.ExitCode != 0)
                    MessageBox.Show("The app could not finish starting or closed unexpectedly.\n\nCheck that Microsoft Edge WebView2 Runtime is installed. The startup log has details.\n\nDetails were saved to:\n" + logPath, "Easy Japanese Subtitles", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        catch (Exception error)
        {
            MessageBox.Show("The app could not start. Check that the folder is writable and the private Python environment exists.\n\n" + error.Message, "Easy Japanese Subtitles", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
