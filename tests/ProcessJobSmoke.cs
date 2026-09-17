using System;
using System.Diagnostics;

internal static class ProcessJobSmoke {
    private static int Main(string[] args) {
        using(var parent=new Process()) {
            parent.StartInfo=new ProcessStartInfo(args[0], "-u -c \"import sys,subprocess,time;sys.stdin.readline();p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);print(p.pid,flush=True);time.sleep(60)\"") {
                UseShellExecute=false, CreateNoWindow=true, RedirectStandardInput=true, RedirectStandardOutput=true
            };
            parent.Start();
            using(var job=new ProcessJob(parent)) {
                parent.StandardInput.WriteLine("GO"); parent.StandardInput.Close();
                int childId=int.Parse(parent.StandardOutput.ReadLine());
                using(var child=Process.GetProcessById(childId)) {
                    job.Dispose();
                    if(!parent.WaitForExit(5000) || !child.WaitForExit(5000))return 1;
                }
            }
        }
        Console.WriteLine("PASS: installer job terminates parent and child");
        return 0;
    }
}
